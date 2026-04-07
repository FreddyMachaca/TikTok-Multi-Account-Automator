from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path


def _build_atempo(speed: float) -> str:
    remaining = float(speed)
    parts: list[str] = []
    while remaining > 2.0:
        parts.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        parts.append("atempo=0.5")
        remaining *= 2.0
    parts.append(f"atempo={remaining:.6f}")
    return ",".join(parts)


def process_video_speed(video_path: str, speed: float, temp_dir: str) -> str:
    speed = float(speed)
    if speed < 1.0 or speed > 1.3:
        raise ValueError("La velocidad debe estar entre 1.0 y 1.3")

    source = Path(video_path)
    if not source.exists():
        raise FileNotFoundError(f"No existe el video: {video_path}")

    if abs(speed - 1.0) < 1e-9:
        return str(source)

    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg no esta disponible en el sistema")

    target_dir = Path(temp_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    output_name = f"{source.stem}_spd_{speed:.2f}_{uuid.uuid4().hex[:8]}{source.suffix}"
    output_path = target_dir / output_name

    setpts_value = 1 / speed
    atempo_filter = _build_atempo(speed)

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-filter:v",
        f"setpts={setpts_value:.6f}*PTS",
        "-filter:a",
        atempo_filter,
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    process = subprocess.run(cmd, capture_output=True, text=True)
    if process.returncode != 0:
        detail = process.stderr.strip() or process.stdout.strip() or "Error desconocido de FFmpeg"
        raise RuntimeError(detail)

    return str(output_path)


def cleanup_temp_file(path: str, temp_dir: str) -> None:
    if not path:
        return
    candidate = Path(path)
    root = Path(temp_dir).resolve()
    try:
        resolved = candidate.resolve()
    except FileNotFoundError:
        return
    if root not in resolved.parents:
        return
    if resolved.exists() and resolved.is_file():
        os.remove(resolved)
