from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


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
    profile_dir = Path(user_data_dir) / chrome_profile

    if not Path(user_data_dir).exists():
        return False, f"No existe User Data valido: {user_data_dir}", int(time.time() - start)

    if not profile_dir.exists():
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

    try:
        with sync_playwright() as playwright:
            try:
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    channel="chrome",
                    headless=headless,
                    viewport={"width": 1440, "height": 900},
                    args=[
                        f"--profile-directory={chrome_profile}",
                        "--disable-blink-features=AutomationControlled",
                    ],
                )
            except Exception as exc:
                detail = _compact_error_text(exc)
                detail_lower = detail.lower()
                if "target page, context or browser has been closed" in detail_lower or "exitcode=21" in detail_lower:
                    detail = f"Chrome se cerro al abrir el perfil {chrome_profile}. Cierra Chrome y prueba de nuevo"
                elif "user data" in detail_lower or "profile" in detail_lower or "lock" in detail_lower:
                    detail = f"No se pudo abrir el perfil {chrome_profile}. Cierra Chrome en ese perfil. Detalle: {detail}"
                elif "notimplementederror" in detail_lower:
                    detail = f"Playwright no pudo iniciar correctamente para {chrome_profile}. Reinicia el backend y cierra Chrome"
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
    except PlaywrightTimeoutError:
        return False, "timeout en la automatizacion", int(time.time() - start)
    except Exception as exc:
        detail = _compact_error_text(exc)
        if "notimplementederror" in detail.lower():
            detail = "Playwright fallo al iniciar Chrome en segundo plano. Reinicia backend y vuelve a intentar"
        return False, detail, int(time.time() - start)
