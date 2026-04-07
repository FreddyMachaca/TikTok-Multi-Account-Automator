from __future__ import annotations

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

    user_data_dir = str(account["chrome_user_data_dir"])
    chrome_profile = str(account["chrome_profile"])
    video = Path(video_path).resolve()

    try:
        with sync_playwright() as playwright:
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
        return False, str(exc), int(time.time() - start)
