from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import time
import warnings
from pathlib import Path
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


def _normalize_path_for_compare(path: str) -> str:
    return os.path.normcase(os.path.normpath(str(path).strip()))


def _get_windows_default_chrome_user_data_dir() -> str | None:
    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    if not local_app_data:
        return None
    return str(Path(local_app_data) / "Google" / "Chrome" / "User Data")


def _is_windows_default_chrome_user_data_dir(path: str) -> bool:
    if os.name != "nt":
        return False
    default_path = _get_windows_default_chrome_user_data_dir()
    if not default_path:
        return False
    return _normalize_path_for_compare(path) == _normalize_path_for_compare(default_path)


def _cleanup_chrome_lock_files(user_data_dir: Path, profile_dir_name: str) -> None:
    root_lock_names = ["SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile"]
    profile_lock_names = ["LOCK", "lockfile"]

    for name in root_lock_names:
        candidate = user_data_dir / name
        if candidate.exists():
            try:
                candidate.unlink()
            except Exception:
                pass

    profile_dir = user_data_dir / profile_dir_name
    for name in profile_lock_names:
        candidate = profile_dir / name
        if candidate.exists():
            try:
                candidate.unlink()
            except Exception:
                pass


def _resolve_automation_user_data_dir(account: dict[str, Any], settings: dict[str, str]) -> Path:
    configured = str(settings.get("automation_user_data_root", "")).strip()
    if configured:
        root = Path(configured)
    else:
        root = Path(__file__).resolve().parent.parent / "temp" / "chrome_profiles"
    root.mkdir(parents=True, exist_ok=True)

    account_key = str(account.get("id") or account.get("name") or "account").strip()
    account_key = re.sub(r"[^a-zA-Z0-9_-]+", "_", account_key).strip("_") or "account"
    return (root / f"acct_{account_key}").resolve()


def _clone_profile_for_automation(
    account: dict[str, Any],
    source_user_data_dir: str,
    chrome_profile: str,
    settings: dict[str, str],
) -> tuple[str | None, str | None]:
    source_root = Path(source_user_data_dir)
    source_profile_dir = source_root / chrome_profile
    if not source_profile_dir.exists():
        return None, f"No existe el perfil {chrome_profile} en {source_user_data_dir}"

    target_root = _resolve_automation_user_data_dir(account, settings)
    target_profile_dir = target_root / chrome_profile

    force_refresh = str(settings.get("clone_default_chrome_profile_force_refresh", "false")).strip().lower() == "true"
    if target_profile_dir.exists() and force_refresh:
        shutil.rmtree(target_profile_dir, ignore_errors=True)

    target_root.mkdir(parents=True, exist_ok=True)

    source_local_state = source_root / "Local State"
    target_local_state = target_root / "Local State"
    if source_local_state.exists():
        try:
            shutil.copy2(source_local_state, target_local_state)
        except Exception as exc:
            return None, f"No se pudo copiar Local State para automatizacion: {_compact_error_text(exc)}"

    if not target_profile_dir.exists():
        try:
            shutil.copytree(source_profile_dir, target_profile_dir, dirs_exist_ok=True)
        except Exception as exc:
            return None, f"No se pudo clonar perfil {chrome_profile} para automatizacion: {_compact_error_text(exc)}"

    _cleanup_chrome_lock_files(target_root, chrome_profile)
    return str(target_root), None


def render_description(template: str, values: dict[str, str]) -> str:
    text = str(template)
    for key, value in values.items():
        text = text.replace(f"{{{key}}}", str(value).strip())
    return " ".join(text.split()).strip()


def _is_chrome_running() -> bool:
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq chrome.exe"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return "chrome.exe" in (result.stdout or "").lower()
    except Exception:
        return False


def _terminate_chrome_processes() -> None:
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/IM", "chrome.exe"],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except Exception:
        pass


def _compact_error_text(exc: Exception) -> str:
    detail = str(exc).strip()
    if not detail:
        detail = exc.__class__.__name__
    normalized = " ".join(detail.replace("\r", " ").replace("\n", " ").split())
    if len(normalized) > 320:
        return normalized[:317] + "..."
    return normalized


def _ensure_windows_asyncio_subprocess_policy() -> tuple[bool, str | None]:
    if os.name != "nt":
        return True, None

    proactor_policy_cls = getattr(asyncio, "WindowsProactorEventLoopPolicy", None)
    selector_policy_cls = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if proactor_policy_cls is None:
        return True, None

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            current_policy = asyncio.get_event_loop_policy()
    except Exception as exc:
        return False, f"No se pudo leer la politica de asyncio: {_compact_error_text(exc)}"

    if isinstance(current_policy, proactor_policy_cls):
        return True, None

    if selector_policy_cls is not None and isinstance(current_policy, selector_policy_cls):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                asyncio.set_event_loop_policy(proactor_policy_cls())
            return True, None
        except Exception as exc:
            detail = _compact_error_text(exc)
            return False, f"No se pudo cambiar asyncio a Proactor en Windows: {detail}"

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            asyncio.set_event_loop_policy(proactor_policy_cls())
        return True, None
    except Exception as exc:
        detail = _compact_error_text(exc)
        return False, f"No se pudo forzar una politica asyncio compatible en Windows: {detail}"


def _normalize_user_data_dir(value: str) -> str:
    cleaned = str(value or "").strip().strip('"').strip("'")
    cleaned = re.sub(
        r"^\s*(?:user\s*data|ruta\s*user\s*data\s*chrome|profile\s*path)\s*:\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"^file:///", "", cleaned, flags=re.IGNORECASE)
    slash_match = re.match(r"^/([a-zA-Z])/(.*)$", cleaned)
    if slash_match:
        cleaned = f"{slash_match.group(1).upper()}:/{slash_match.group(2)}"
    return cleaned.strip()


def _normalize_chrome_profile(value: str) -> str:
    cleaned = str(value or "").strip().strip('"').strip("'")
    cleaned = re.sub(
        r"^\s*(?:perfil\s*de\s*chrome|chrome\s*profile|profile)\s*:\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    normalized = cleaned.replace("\\", "/").rstrip("/")
    if "/" in normalized:
        normalized = normalized.split("/")[-1]
    return normalized.strip()


def upload_with_playwright(
    account: dict[str, Any],
    video_path: str,
    description: str,
    settings: dict[str, str],
) -> tuple[bool, str | None, int]:
    start = time.time()

    upload_url = settings.get("tiktok_upload_url", "https://www.tiktok.com/upload")
    file_input_selector = settings.get("tiktok_file_input_selector", "input[type='file']")
    description_selector = settings.get("tiktok_description_selector", "div[contenteditable='true']")
    upload_button_selector = settings.get(
        "tiktok_upload_button_selector",
        "[data-e2e='submit-button'], [data-e2e='post_video_button']",
    )
    success_selector = settings.get(
        "tiktok_success_selector",
        "[data-e2e='upload-success'], [data-e2e='upload-success-message']",
    )
    captcha_selector = settings.get(
        "tiktok_captcha_selector",
        "iframe[src*='captcha'], div[class*='captcha']",
    )
    preview_wait_ms = int(settings.get("tiktok_preview_wait_ms", "12000"))
    publish_timeout_seconds = int(settings.get("tiktok_publish_timeout_seconds", "180"))
    headless = settings.get("playwright_headless", "false").lower() == "true"
    force_close_chrome = settings.get("force_close_chrome_before_upload", "true").lower() == "true"
    force_close_wait_seconds = int(settings.get("force_close_chrome_wait_seconds", "2"))

    user_data_dir = _normalize_user_data_dir(str(account["chrome_user_data_dir"]))
    chrome_profile = _normalize_chrome_profile(str(account["chrome_profile"]))
    video = Path(video_path).resolve()
    source_profile_dir = Path(user_data_dir) / chrome_profile

    if not Path(user_data_dir).exists():
        return False, f"No existe User Data valido: {user_data_dir}", int(time.time() - start)

    if not source_profile_dir.exists():
        return False, f"No existe el perfil {chrome_profile} en {user_data_dir}", int(time.time() - start)

    if force_close_chrome and _is_chrome_running():
        _terminate_chrome_processes()
        if force_close_wait_seconds > 0:
            time.sleep(force_close_wait_seconds)

    if _is_chrome_running():
        return (
            False,
            f"Chrome esta abierto. Cierra todas las ventanas de Chrome antes de subir con el perfil {chrome_profile}",
            int(time.time() - start),
        )

    launch_user_data_dir = user_data_dir
    clone_default_profile = str(settings.get("clone_default_chrome_profile", "true")).strip().lower() == "true"
    if _is_windows_default_chrome_user_data_dir(user_data_dir):
        if not clone_default_profile:
            return (
                False,
                "Chrome bloqueo DevTools sobre el User Data por defecto. Activa clone_default_chrome_profile=true",
                int(time.time() - start),
            )
        cloned_dir, clone_error = _clone_profile_for_automation(account, user_data_dir, chrome_profile, settings)
        if clone_error:
            return False, clone_error, int(time.time() - start)
        if not cloned_dir:
            return False, "No se pudo preparar un perfil de automatizacion", int(time.time() - start)
        launch_user_data_dir = cloned_dir

    policy_ok, policy_error = _ensure_windows_asyncio_subprocess_policy()
    if not policy_ok:
        return False, policy_error, int(time.time() - start)

    try:
        with sync_playwright() as playwright:
            try:
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=launch_user_data_dir,
                    channel="chrome",
                    headless=headless,
                    viewport={"width": 1440, "height": 900},
                    args=[
                        f"--profile-directory={chrome_profile}",
                        "--disable-blink-features=AutomationControlled",
                    ],
                )
            except Exception as exc:
                raw_detail = str(exc)
                detail = _compact_error_text(exc)
                raw_lower = raw_detail.lower()
                if "target page, context or browser has been closed" in raw_lower or "exitcode=21" in raw_lower:
                    detail = f"Chrome se cerro al abrir el perfil {chrome_profile}. Cierra Chrome y prueba de nuevo"
                elif "devtools remote debugging requires a non-default data directory" in raw_lower:
                    detail = (
                        "Chrome rechazo DevTools en el User Data por defecto. "
                        "Se requiere un perfil clonado para automatizacion"
                    )
                elif "user data" in raw_lower or "profile" in raw_lower or "lock" in raw_lower:
                    detail = f"No se pudo abrir el perfil {chrome_profile}. Cierra Chrome en ese perfil. Detalle: {detail}"
                elif "notimplementederror" in raw_lower:
                    detail = (
                        "Playwright no pudo crear subprocess en Windows por una politica asyncio incompatible. "
                        "Reinicia backend y vuelve a intentar"
                    )
                return False, detail, int(time.time() - start)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(upload_url, wait_until="domcontentloaded", timeout=90000)

                if captcha_selector and page.locator(captcha_selector).count() > 0:
                    return False, "captcha_detectado", int(time.time() - start)

                page.wait_for_selector(file_input_selector, timeout=60000)
                page.set_input_files(file_input_selector, str(video))
                page.wait_for_timeout(preview_wait_ms)

                if description_selector:
                    box = page.locator(description_selector).first
                    box.click(timeout=20000)
                    page.keyboard.press("Control+A")
                    page.keyboard.press("Backspace")
                    page.keyboard.type(description, delay=12)

                submit = page.locator(upload_button_selector).first
                submit.click(timeout=25000)

                deadline = time.time() + publish_timeout_seconds
                while time.time() < deadline:
                    if captcha_selector and page.locator(captcha_selector).count() > 0:
                        return False, "captcha_detectado", int(time.time() - start)
                    if success_selector and page.locator(success_selector).count() > 0:
                        return True, None, int(time.time() - start)
                    page.wait_for_timeout(1000)

                return False, "no se confirmo la subida dentro del tiempo limite", int(time.time() - start)
            finally:
                context.close()
    except NotImplementedError:
        return (
            False,
            "Playwright fallo por politica asyncio incompatible en Windows. Reinicia backend y reintenta",
            int(time.time() - start),
        )
    except PlaywrightTimeoutError:
        return False, "timeout en la automatizacion", int(time.time() - start)
    except Exception as exc:
        detail = _compact_error_text(exc)
        if "notimplementederror" in detail.lower():
            detail = "Playwright fallo al iniciar Chrome en segundo plano. Reinicia backend y vuelve a intentar"
        return False, detail, int(time.time() - start)
