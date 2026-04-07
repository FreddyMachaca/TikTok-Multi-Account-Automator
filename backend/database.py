from __future__ import annotations

import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import mysql.connector
from dotenv import load_dotenv
from mysql.connector import pooling

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "tiktok_automator").replace("`", "")
DB_POOL_NAME = os.getenv("DB_POOL_NAME", "tiktok_pool")
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "6"))

_pool: pooling.MySQLConnectionPool | None = None


def _admin_config() -> dict[str, Any]:
    return {
        "host": DB_HOST,
        "port": DB_PORT,
        "user": DB_USER,
        "password": DB_PASSWORD,
        "autocommit": False,
    }


def _db_config() -> dict[str, Any]:
    config = _admin_config()
    config["database"] = DB_NAME
    return config


def _ensure_database_exists() -> None:
    conn = mysql.connector.connect(**_admin_config())
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def _ensure_pool() -> None:
    global _pool
    if _pool is not None:
        return
    _ensure_database_exists()
    _pool = pooling.MySQLConnectionPool(
        pool_name=DB_POOL_NAME,
        pool_size=DB_POOL_SIZE,
        pool_reset_session=True,
        **_db_config(),
    )


def get_connection():
    _ensure_pool()
    return _pool.get_connection()  # type: ignore[union-attr]


def ensure_schema() -> None:
    schema_path = BASE_DIR / "schema.sql"
    script = schema_path.read_text(encoding="utf-8")
    conn = mysql.connector.connect(**_admin_config())
    cursor = conn.cursor()
    try:
        statements = [segment.strip() for segment in script.split(";") if segment.strip()]
        for statement in statements:
            cursor.execute(statement)
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    global _pool
    _pool = None
    _ensure_pool()


def _serialize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _rows_to_dicts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        item = {key: _serialize(value) for key, value in row.items()}
        if "active" in item:
            item["active"] = bool(item["active"])
        normalized.append(item)
    return normalized


def get_all_accounts() -> list[dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT
                a.id,
                a.name,
                a.chrome_profile,
                a.chrome_user_data_dir,
                a.speed,
                a.active,
                a.created_at,
                COALESCE(SUM(CASE WHEN h.status = 'success' THEN 1 ELSE 0 END), 0) AS success_uploads
            FROM accounts a
            LEFT JOIN upload_history h ON h.account_id = a.id
            GROUP BY a.id
            ORDER BY a.created_at DESC
            """
        )
        rows = cursor.fetchall()
        return _rows_to_dicts(rows)
    finally:
        cursor.close()
        conn.close()


def get_active_accounts() -> list[dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT id, name, chrome_profile, chrome_user_data_dir, speed, active, created_at
            FROM accounts
            WHERE active = 1
            ORDER BY created_at ASC
            """
        )
        rows = cursor.fetchall()
        return _rows_to_dicts(rows)
    finally:
        cursor.close()
        conn.close()


def get_account(account_id: int) -> dict[str, Any] | None:
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT
                a.id,
                a.name,
                a.chrome_profile,
                a.chrome_user_data_dir,
                a.speed,
                a.active,
                a.created_at,
                COALESCE(SUM(CASE WHEN h.status = 'success' THEN 1 ELSE 0 END), 0) AS success_uploads
            FROM accounts a
            LEFT JOIN upload_history h ON h.account_id = a.id
            WHERE a.id = %s
            GROUP BY a.id
            """,
            (account_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return _rows_to_dicts([row])[0]
    finally:
        cursor.close()
        conn.close()


def create_account(data: dict[str, Any]) -> dict[str, Any]:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO accounts (name, chrome_profile, chrome_user_data_dir, speed, active, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            """,
            (
                data["name"],
                data["chrome_profile"],
                data["chrome_user_data_dir"],
                float(data.get("speed", 1.0)),
                1 if bool(data.get("active", True)) else 0,
            ),
        )
        account_id = cursor.lastrowid
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    account = get_account(int(account_id))
    if account is None:
        raise RuntimeError("No se pudo crear la cuenta")
    return account


def update_account(account_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
    allowed_fields = {
        "name",
        "chrome_profile",
        "chrome_user_data_dir",
        "speed",
        "active",
    }
    updates: list[str] = []
    values: list[Any] = []
    for key, value in data.items():
        if key not in allowed_fields or value is None:
            continue
        updates.append(f"{key} = %s")
        if key == "active":
            values.append(1 if bool(value) else 0)
        elif key == "speed":
            values.append(float(value))
        else:
            values.append(value)
    if not updates:
        return get_account(account_id)
    conn = get_connection()
    cursor = conn.cursor()
    try:
        values.append(account_id)
        cursor.execute(
            f"UPDATE accounts SET {', '.join(updates)} WHERE id = %s",
            tuple(values),
        )
        conn.commit()
        if cursor.rowcount == 0:
            return None
    finally:
        cursor.close()
        conn.close()
    return get_account(account_id)


def delete_account(account_id: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM accounts WHERE id = %s", (account_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()
        conn.close()


def get_settings() -> dict[str, str]:
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT setting_key, setting_value FROM settings")
        rows = cursor.fetchall()
        return {row["setting_key"]: str(row["setting_value"]) for row in rows}
    finally:
        cursor.close()
        conn.close()


def set_setting(key: str, value: Any) -> None:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO settings (setting_key, setting_value)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)
            """,
            (key, str(value)),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def set_settings(values: dict[str, Any]) -> None:
    if not values:
        return
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.executemany(
            """
            INSERT INTO settings (setting_key, setting_value)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)
            """,
            [(key, str(value)) for key, value in values.items()],
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def ensure_default_settings(defaults: dict[str, Any]) -> None:
    current = get_settings()
    missing = {k: v for k, v in defaults.items() if k not in current or current[k] == ""}
    if missing:
        set_settings(missing)


def register_upload(
    account_id: int,
    filename: str,
    status: str,
    duration_seconds: int,
    error_message: str | None,
) -> None:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO upload_history (account_id, video_filename, status, duration_seconds, error_message, uploaded_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            """,
            (
                account_id,
                filename,
                status,
                int(duration_seconds),
                error_message,
            ),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def was_already_uploaded(account_id: int, filename: str) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT 1
            FROM upload_history
            WHERE account_id = %s AND video_filename = %s AND status = 'success'
            LIMIT 1
            """,
            (account_id, filename),
        )
        return cursor.fetchone() is not None
    finally:
        cursor.close()
        conn.close()


def get_daily_success_count(account_id: int) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM upload_history
            WHERE account_id = %s
              AND status = 'success'
              AND DATE(uploaded_at) = CURDATE()
            """,
            (account_id,),
        )
        row = cursor.fetchone()
        return int(row[0] if row else 0)
    finally:
        cursor.close()
        conn.close()


def get_history(
    account_id: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    conditions: list[str] = []
    params: list[Any] = []

    if account_id is not None:
        conditions.append("h.account_id = %s")
        params.append(account_id)
    if start_date:
        conditions.append("DATE(h.uploaded_at) >= %s")
        params.append(start_date)
    if end_date:
        conditions.append("DATE(h.uploaded_at) <= %s")
        params.append(end_date)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    safe_limit = max(1, min(int(limit), 1000))

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            f"""
            SELECT
                h.id,
                h.account_id,
                a.name AS account_name,
                h.video_filename,
                h.status,
                h.duration_seconds,
                h.error_message,
                h.uploaded_at
            FROM upload_history h
            JOIN accounts a ON a.id = h.account_id
            {where_clause}
            ORDER BY h.uploaded_at DESC
            LIMIT %s
            """,
            tuple(params + [safe_limit]),
        )
        rows = cursor.fetchall()
        return _rows_to_dicts(rows)
    finally:
        cursor.close()
        conn.close()
