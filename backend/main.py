from __future__ import annotations

import asyncio
import os
import re
import threading
import time
import warnings
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from database import (
    create_account,
    delete_account,
    ensure_default_settings,
    ensure_schema,
    get_account,
    get_active_accounts,
    get_all_accounts,
    get_daily_success_count,
    get_history,
    get_settings,
    register_upload,
    set_settings,
    update_account,
    was_already_uploaded,
)
from job_manager import JobManager
from uploader import render_description, upload_with_playwright
from video_processor import cleanup_temp_file, process_video_speed

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
VIDEOS_DIR = PROJECT_ROOT / "videos"
TEMP_DIR = PROJECT_ROOT / "temp"
SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mov"}

VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="TikTok Multi-Account Automator", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

job_manager = JobManager()
_upload_thread: threading.Thread | None = None
_upload_thread_lock = threading.Lock()


class AccountCreatePayload(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    chrome_profile: str = Field(min_length=1, max_length=100)
    chrome_user_data_dir: str = Field(min_length=1)
    speed: float = Field(default=1.0, ge=1.0, le=1.3)
    active: bool = True
    is_primary: bool = False


class AccountUpdatePayload(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    chrome_profile: str | None = Field(default=None, min_length=1, max_length=100)
    chrome_user_data_dir: str | None = Field(default=None, min_length=1)
    speed: float | None = Field(default=None, ge=1.0, le=1.3)
    active: bool | None = None
    is_primary: bool | None = None


def _default_settings() -> dict[str, Any]:
    return {
        "hashtags": "#viral #fyp #trending",
        "description_template": "{title} {hashtags}",
        "brand_hashtag": "#BoliviaNewsBO",
        "fixed_location_hashtags": "#LaPazBolivia #Bolivia",
        "primary_youtube_mention": "@bolivianews-bo",
        "secondary_primary_mention": "@bolivia.news4",
        "primary_description_template": "{title}",
        "secondary_description_template": "{title}",
        "delay_between_uploads": "25",
        "videos_folder": str(VIDEOS_DIR.resolve()),
        "max_daily_per_account": "15",
        "force_close_chrome_before_upload": "true",
        "force_close_chrome_wait_seconds": "2",
        "clone_default_chrome_profile": "true",
        "clone_default_chrome_profile_force_refresh": "false",
        "automation_user_data_root": str((TEMP_DIR / "chrome_profiles").resolve()),
        "playwright_headless": os.getenv("PLAYWRIGHT_HEADLESS", "false"),
        "tiktok_upload_url": "https://www.tiktok.com/upload",
        "tiktok_file_input_selector": "input[type='file']",
        "tiktok_description_selector": "div[contenteditable='true']",
        "tiktok_upload_button_selector": "[data-e2e='submit-button'], [data-e2e='post_video_button']",
        "tiktok_success_selector": "[data-e2e='upload-success'], [data-e2e='upload-success-message']",
        "tiktok_captcha_selector": "iframe[src*='captcha'], div[class*='captcha']",
        "tiktok_preview_wait_ms": "12000",
        "tiktok_publish_timeout_seconds": "180",
    }


def _ensure_windows_asyncio_policy() -> None:
    if os.name != "nt":
        return

    proactor_policy_cls = getattr(asyncio, "WindowsProactorEventLoopPolicy", None)
    selector_policy_cls = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if proactor_policy_cls is None:
        return

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        current_policy = asyncio.get_event_loop_policy()
    if selector_policy_cls is not None and isinstance(current_policy, selector_policy_cls):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            asyncio.set_event_loop_policy(proactor_policy_cls())
        return

    if not isinstance(current_policy, proactor_policy_cls):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            asyncio.set_event_loop_policy(proactor_policy_cls())


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(str(value))
    except Exception:
        return default


def _resolve_videos_folder(settings: dict[str, str]) -> Path:
    raw = str(settings.get("videos_folder", "")).strip()
    if not raw:
        return VIDEOS_DIR.resolve()
    folder = Path(raw)
    if folder.is_absolute():
        return folder
    return (PROJECT_ROOT / folder).resolve()


def _list_video_files(folder: Path) -> list[str]:
    if not folder.exists():
        return []
    videos = [
        path.name
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS
    ]
    return sorted(videos)


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


def _normalize_account_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    if "chrome_user_data_dir" in normalized and normalized["chrome_user_data_dir"] is not None:
        normalized["chrome_user_data_dir"] = _normalize_user_data_dir(str(normalized["chrome_user_data_dir"]))
    if "chrome_profile" in normalized and normalized["chrome_profile"] is not None:
        normalized["chrome_profile"] = _normalize_chrome_profile(str(normalized["chrome_profile"]))
    return normalized


def _sanitize_existing_accounts() -> None:
    accounts = get_all_accounts()
    for account in accounts:
        account_id = int(account["id"])
        current_user_data = str(account.get("chrome_user_data_dir", "")).strip()
        current_profile = str(account.get("chrome_profile", "")).strip()
        normalized_user_data = _normalize_user_data_dir(current_user_data)
        normalized_profile = _normalize_chrome_profile(current_profile)
        updates: dict[str, Any] = {}
        if normalized_user_data and normalized_user_data != current_user_data:
            updates["chrome_user_data_dir"] = normalized_user_data
        if normalized_profile and normalized_profile != current_profile:
            updates["chrome_profile"] = normalized_profile
        if updates:
            update_account(account_id, updates)


def _join_caption_parts(parts: list[str]) -> str:
    return " ".join(part.strip() for part in parts if str(part).strip()).strip()


def _remove_tokens(text: str, tokens: list[str]) -> str:
    cleaned = text
    for token in tokens:
        value = str(token).strip()
        if value:
            cleaned = cleaned.replace(value, " ")
    return " ".join(cleaned.split()).strip()


def _build_account_description(account: dict[str, Any], video_filename: str, settings: dict[str, str]) -> str:
    title = Path(video_filename).stem.replace("_", " ").strip()
    is_primary = bool(account.get("is_primary", False))

    brand_hashtag = settings.get("brand_hashtag", "#BoliviaNewsBO").strip()
    fixed_location_hashtags = settings.get("fixed_location_hashtags", "#LaPazBolivia #Bolivia").strip()
    primary_youtube_mention = settings.get("primary_youtube_mention", "@bolivianews-bo").strip()
    secondary_primary_mention = settings.get("secondary_primary_mention", "@bolivia.news4").strip()

    mandatory_block = _join_caption_parts(
        [
            primary_youtube_mention if is_primary else secondary_primary_mention,
            fixed_location_hashtags,
            brand_hashtag,
        ]
    )

    template_key = "primary_description_template" if is_primary else "secondary_description_template"
    template_value = settings.get(template_key, "{title}")

    raw_text = render_description(
        template_value,
        {
            "title": title,
            "brand_hashtag": brand_hashtag,
            "fixed_location_hashtags": fixed_location_hashtags,
            "youtube_mention": primary_youtube_mention,
            "secondary_mention": secondary_primary_mention,
            "mandatory_block": mandatory_block,
        },
    )

    base_text = _remove_tokens(
        raw_text,
        [
            mandatory_block,
            brand_hashtag,
            fixed_location_hashtags,
            primary_youtube_mention,
            secondary_primary_mention,
        ],
    )
    return _join_caption_parts([base_text, mandatory_block])


def _run_upload_job(accounts: list[dict[str, Any]], videos: list[str], settings: dict[str, str]) -> None:
    delay_between_uploads = max(0, _safe_int(settings.get("delay_between_uploads"), 25))
    max_daily = max(1, _safe_int(settings.get("max_daily_per_account"), 15))
    videos_folder = _resolve_videos_folder(settings)

    total_operations = len(accounts) * len(videos)
    daily_success = {int(account["id"]): get_daily_success_count(int(account["id"])) for account in accounts}
    if not job_manager.is_running():
        job_manager.start_job(total_operations, accounts, videos)
    job_manager.add_log("INFO", f"Iniciando procesamiento de {len(videos)} videos en {len(accounts)} cuentas")

    try:
        stop_all = False
        for video_filename in videos:
            if stop_all:
                break
            source_video_path = videos_folder / video_filename
            for account in accounts:
                account_id = int(account["id"])
                account_name = str(account["name"])
                speed = float(account.get("speed", 1.0))

                if job_manager.should_stop():
                    stop_all = True
                    break

                job_manager.set_current_task(f"{video_filename} -> {account_name}")
                job_manager.add_log(
                    "PROC",
                    f"Preparando {video_filename} para {account_name}",
                    account_id,
                    video_filename,
                )

                if daily_success.get(account_id, 0) >= max_daily:
                    job_manager.mark_skipped(account_id, video_filename, "limite diario alcanzado")
                    continue

                if was_already_uploaded(account_id, video_filename):
                    job_manager.mark_skipped(account_id, video_filename, "ya existe subida exitosa")
                    continue

                if not source_video_path.exists():
                    error_text = "archivo no encontrado"
                    register_upload(account_id, video_filename, "failed", 0, error_text)
                    job_manager.mark_failed(account_id, video_filename, error_text, 0)
                    continue

                processed_path = str(source_video_path)
                try:
                    job_manager.set_account_task(account_id, video_filename, "preparando")
                    if abs(speed - 1.0) > 1e-9:
                        processed_path = process_video_speed(str(source_video_path), speed, str(TEMP_DIR))
                        job_manager.add_log(
                            "PROC",
                            f"{video_filename} procesado a {speed:.1f}x para {account_name}",
                            account_id,
                            video_filename,
                        )
                except Exception as exc:
                    error_text = str(exc)
                    register_upload(account_id, video_filename, "failed", 0, error_text)
                    job_manager.mark_failed(account_id, video_filename, error_text, 0)
                    continue

                description = _build_account_description(account, video_filename, settings)

                success = False
                attempts = 0
                last_error = ""
                failure_registered = False
                last_duration = 0

                while attempts < 3:
                    attempts += 1
                    if job_manager.should_stop():
                        break

                    job_manager.set_account_task(account_id, video_filename, f"subiendo intento {attempts}")
                    job_manager.add_log(
                        "PROC",
                        f"Iniciando intento {attempts}/3 para {video_filename} en {account_name}",
                        account_id,
                        video_filename,
                    )
                    ok, error, duration = upload_with_playwright(account, processed_path, description, settings)
                    last_duration = duration

                    if ok:
                        register_upload(account_id, video_filename, "success", duration, None)
                        job_manager.mark_success(account_id, video_filename, duration)
                        daily_success[account_id] = daily_success.get(account_id, 0) + 1
                        success = True
                        break

                    last_error = error or "error desconocido"

                    if "captcha" in last_error.lower():
                        register_upload(account_id, video_filename, "failed", duration, last_error)
                        job_manager.mark_failed(account_id, video_filename, last_error, duration)
                        job_manager.request_stop("Captcha detectado. Resolver y reintentar.")
                        failure_registered = True
                        break

                    if attempts < 3 and not job_manager.should_stop():
                        job_manager.add_log(
                            "WARN",
                            f"Fallo intento {attempts}/3 para {video_filename} en {account_name}. Motivo: {last_error}. Reintento en 30s",
                            account_id,
                            video_filename,
                        )
                        time.sleep(30)

                if not success and not failure_registered:
                    final_error = last_error or "proceso detenido"
                    register_upload(account_id, video_filename, "failed", last_duration, final_error)
                    job_manager.mark_failed(account_id, video_filename, final_error, last_duration)

                cleanup_temp_file(processed_path, str(TEMP_DIR))

                if job_manager.should_stop():
                    stop_all = True
                    break

                if delay_between_uploads > 0:
                    job_manager.set_current_task(f"Esperando {delay_between_uploads}s antes de la siguiente subida")
                    job_manager.add_log("INFO", f"Delay de seguridad {delay_between_uploads}s")
                    time.sleep(delay_between_uploads)

        if job_manager.should_stop():
            job_manager.finish("stopped")
        else:
            job_manager.finish("completed")
    except Exception as exc:
        job_manager.add_log("ERR", f"Error critico: {str(exc)}")
        if job_manager.is_running():
            job_manager.finish("failed")


@app.on_event("startup")
def on_startup() -> None:
    _ensure_windows_asyncio_policy()
    ensure_schema()
    ensure_default_settings(_default_settings())
    _sanitize_existing_accounts()


@app.get("/")
def root() -> RedirectResponse:
    if FRONTEND_DIR.exists():
        return RedirectResponse(url="/static/index.html")
    return RedirectResponse(url="/docs")


@app.get("/accounts")
def list_accounts() -> list[dict[str, Any]]:
    return get_all_accounts()


@app.post("/accounts", status_code=201)
def add_account(payload: AccountCreatePayload) -> dict[str, Any]:
    normalized_payload = _normalize_account_payload(payload.model_dump())
    return create_account(normalized_payload)


@app.put("/accounts/{account_id}")
def edit_account(account_id: int, payload: AccountUpdatePayload) -> dict[str, Any]:
    normalized_payload = _normalize_account_payload(payload.model_dump(exclude_none=True))
    account = update_account(account_id, normalized_payload)
    if account is None:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")
    return account


@app.delete("/accounts/{account_id}")
def remove_account(account_id: int) -> dict[str, Any]:
    deleted = delete_account(account_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")
    return {"deleted": True}


@app.get("/settings")
def read_settings() -> dict[str, str]:
    return get_settings()


@app.post("/settings")
def write_settings(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    if not payload:
        raise HTTPException(status_code=400, detail="Payload vacio")
    set_settings(payload)
    return {"saved": True, "settings": get_settings()}


@app.get("/videos")
def list_videos() -> dict[str, Any]:
    settings = get_settings()
    folder = _resolve_videos_folder(settings)
    folder.mkdir(parents=True, exist_ok=True)
    videos = _list_video_files(folder)
    return {
        "folder": str(folder),
        "total": len(videos),
        "videos": videos,
    }


@app.post("/upload")
def start_upload() -> dict[str, Any]:
    global _upload_thread

    with _upload_thread_lock:
        if job_manager.is_running():
            raise HTTPException(status_code=409, detail="Ya hay un proceso de subida en ejecucion")

        settings = get_settings()
        accounts = get_active_accounts()
        if not accounts:
            raise HTTPException(status_code=400, detail="No hay cuentas activas")

        folder = _resolve_videos_folder(settings)
        videos = _list_video_files(folder)
        if not videos:
            raise HTTPException(status_code=400, detail="No se encontraron videos .mp4 o .mov")

        total_operations = len(videos) * len(accounts)
        job_manager.start_job(total_operations, accounts, videos)
        job_manager.add_log("INFO", "Job en cola, preparando entorno de subida")

        _upload_thread = threading.Thread(
            target=_run_upload_job,
            args=(accounts, videos, settings),
            daemon=True,
        )
        _upload_thread.start()

        return {
            "status": "iniciado",
            "videos": len(videos),
            "accounts": len(accounts),
            "total_operations": total_operations,
        }


@app.get("/progress")
def read_progress(since: int = Query(default=0, ge=0)) -> dict[str, Any]:
    return job_manager.get_progress(since)


@app.post("/stop")
def stop_upload() -> dict[str, Any]:
    if not job_manager.is_running():
        return {"status": "idle", "message": "No hay job en ejecucion"}
    job_manager.request_stop("Detenido manualmente por el usuario")
    return {"status": "stopping"}


@app.get("/history")
def read_history(
    account_id: int | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[dict[str, Any]]:
    return get_history(account_id=account_id, start_date=start_date, end_date=end_date, limit=limit)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.getenv("APP_HOST", "0.0.0.0"),
        port=int(os.getenv("APP_PORT", "8000")),
        reload=True,
    )
