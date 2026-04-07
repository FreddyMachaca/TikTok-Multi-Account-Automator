from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any


class JobManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {}
        self._reset_locked()

    def _reset_locked(self) -> None:
        self._state = {
            "running": False,
            "status": "idle",
            "total": 0,
            "completed": 0,
            "failed": 0,
            "skipped": 0,
            "current_task": "",
            "start_time": None,
            "end_time": None,
            "stop_requested": False,
            "stop_reason": None,
            "log": [],
            "log_cursor": 0,
            "account_progress": {},
            "failures": [],
            "summary": None,
        }

    def start_job(self, total: int, accounts: list[dict[str, Any]], videos: list[str]) -> None:
        with self._lock:
            self._reset_locked()
            account_progress: dict[str, Any] = {}
            per_account_total = len(videos)
            for account in accounts:
                account_progress[str(account["id"])] = {
                    "account_id": account["id"],
                    "name": account["name"],
                    "speed": float(account.get("speed", 1.0)),
                    "total": per_account_total,
                    "completed": 0,
                    "failed": 0,
                    "skipped": 0,
                    "current_video": "",
                    "status": "pendiente",
                }
            self._state.update(
                {
                    "running": True,
                    "status": "running",
                    "total": total,
                    "current_task": "Iniciando proceso",
                    "start_time": time.time(),
                    "account_progress": account_progress,
                }
            )
            self._append_log_locked("INFO", f"Job iniciado con {total} operaciones")

    def is_running(self) -> bool:
        with self._lock:
            return bool(self._state["running"])

    def should_stop(self) -> bool:
        with self._lock:
            return bool(self._state["stop_requested"])

    def request_stop(self, reason: str | None = None) -> None:
        with self._lock:
            if self._state["stop_requested"]:
                return
            self._state["stop_requested"] = True
            self._state["stop_reason"] = reason or "Detencion solicitada"
            self._append_log_locked("WARN", self._state["stop_reason"])

    def set_current_task(self, task: str) -> None:
        with self._lock:
            self._state["current_task"] = task

    def set_account_task(self, account_id: int, video: str, status: str) -> None:
        with self._lock:
            card = self._state["account_progress"].get(str(account_id))
            if not card:
                return
            card["current_video"] = video
            card["status"] = status

    def add_log(
        self,
        level: str,
        message: str,
        account_id: int | None = None,
        video_filename: str | None = None,
    ) -> None:
        with self._lock:
            self._append_log_locked(level, message, account_id, video_filename)

    def _append_log_locked(
        self,
        level: str,
        message: str,
        account_id: int | None = None,
        video_filename: str | None = None,
    ) -> None:
        self._state["log_cursor"] += 1
        item = {
            "id": self._state["log_cursor"],
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "level": level,
            "message": message,
            "account_id": account_id,
            "video_filename": video_filename,
        }
        self._state["log"].append(item)
        if len(self._state["log"]) > 500:
            self._state["log"] = self._state["log"][-500:]

    def mark_success(self, account_id: int, video: str, duration: int) -> None:
        with self._lock:
            self._state["completed"] += 1
            card = self._state["account_progress"].get(str(account_id))
            if card:
                card["completed"] += 1
                card["status"] = "ok"
                card["current_video"] = video
            self._append_log_locked("OK", f"{video} subido en {duration}s", account_id, video)

    def mark_failed(self, account_id: int, video: str, error: str, duration: int) -> None:
        with self._lock:
            self._state["failed"] += 1
            card = self._state["account_progress"].get(str(account_id))
            if card:
                card["failed"] += 1
                card["status"] = "error"
                card["current_video"] = video
            self._state["failures"].append(
                {
                    "account_id": account_id,
                    "video": video,
                    "error": error,
                    "duration_seconds": duration,
                }
            )
            self._append_log_locked("ERR", f"{video} fallo: {error}", account_id, video)

    def mark_skipped(self, account_id: int, video: str, reason: str) -> None:
        with self._lock:
            self._state["skipped"] += 1
            card = self._state["account_progress"].get(str(account_id))
            if card:
                card["skipped"] += 1
                card["status"] = "saltado"
                card["current_video"] = video
            self._append_log_locked("SKIP", f"{video} omitido: {reason}", account_id, video)

    def finish(self, status: str = "completed") -> None:
        with self._lock:
            if not self._state["running"]:
                return
            self._state["running"] = False
            self._state["status"] = status
            self._state["end_time"] = time.time()
            elapsed = self._elapsed_locked()
            done = self._done_locked()
            self._state["current_task"] = "Proceso finalizado"
            self._state["summary"] = {
                "total_planned": self._state["total"],
                "total_processed": done,
                "success_count": self._state["completed"],
                "failed_count": self._state["failed"],
                "skipped_count": self._state["skipped"],
                "elapsed_seconds": elapsed,
                "failed_items": list(self._state["failures"]),
                "status": status,
            }
            self._append_log_locked("INFO", f"Job finalizado con estado {status}")

    def _done_locked(self) -> int:
        return int(self._state["completed"] + self._state["failed"] + self._state["skipped"])

    def _elapsed_locked(self) -> int:
        start = self._state["start_time"]
        if not start:
            return 0
        end = self._state["end_time"] or time.time()
        return max(0, int(end - start))

    def _remaining_locked(self) -> int | None:
        total = int(self._state["total"])
        done = self._done_locked()
        if done <= 0 or total <= 0:
            return None
        remaining = total - done
        if remaining <= 0:
            return 0
        elapsed = self._elapsed_locked()
        avg = elapsed / done
        return int(avg * remaining)

    def get_progress(self, since: int = 0) -> dict[str, Any]:
        with self._lock:
            done = self._done_locked()
            total = int(self._state["total"])
            percent = round((done / total) * 100, 2) if total > 0 else 0.0
            logs = list(self._state["log"])
            new_logs = [item for item in logs if int(item["id"]) > since]
            cards = list(self._state["account_progress"].values())
            start = self._state["start_time"]
            start_iso = datetime.fromtimestamp(start).isoformat() if start else None
            return {
                "running": self._state["running"],
                "status": self._state["status"],
                "total": total,
                "completed": int(self._state["completed"]),
                "failed": int(self._state["failed"]),
                "skipped": int(self._state["skipped"]),
                "done": done,
                "progress_percent": percent,
                "current_task": self._state["current_task"],
                "start_time": start_iso,
                "elapsed_seconds": self._elapsed_locked(),
                "remaining_seconds": self._remaining_locked(),
                "stop_requested": self._state["stop_requested"],
                "stop_reason": self._state["stop_reason"],
                "log_cursor": int(self._state["log_cursor"]),
                "new_logs": new_logs,
                "logs": logs[-100:],
                "account_cards": cards,
                "summary": self._state["summary"],
            }
