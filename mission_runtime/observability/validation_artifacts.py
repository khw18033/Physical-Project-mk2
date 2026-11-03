"""Deterministic functional-validation artifacts.

implements: AI-O-01, AI-O-03, AI-L-05, AI-L-08

This module never selects samples by model outcome.  It sorts stable relative
paths and takes a declared prefix, then records hashes so every baseline sees
the same inputs.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class ManifestItem:
    relative_path: str
    size_bytes: int
    sha256: str


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def select_frame_paths(frame_root: Path, *, video_limit: int, frame_limit: int) -> list[Path]:
    videos = sorted(path for path in frame_root.iterdir() if path.is_dir())[:video_limit]
    frames = sorted(
        (path for video in videos for path in video.iterdir() if path.suffix.lower() in {".jpg", ".png"}),
        key=lambda path: path.relative_to(frame_root).as_posix(),
    )
    return frames[:frame_limit]


def build_manifest(frame_root: Path, paths: Iterable[Path], *, purpose: str) -> dict[str, object]:
    items = [
        ManifestItem(
            relative_path=path.relative_to(frame_root).as_posix(),
            size_bytes=path.stat().st_size,
            sha256=sha256_file(path),
        )
        for path in paths
    ]
    return {
        "schema_version": "1.0",
        "purpose": purpose,
        "selection": "lexicographic-video-prefix-then-frame-prefix",
        "root": str(frame_root),
        "count": len(items),
        "items": [asdict(item) for item in items],
    }


def environment_snapshot(*, execution_provider: str) -> dict[str, object]:
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "execution_provider": execution_provider,
    }


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
