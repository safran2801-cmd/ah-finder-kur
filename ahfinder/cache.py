"""Datei-basierter Cache (JSON), verhaltensgleich zur PHP-Version.

Schlüssel werden als MD5-Hash in .json-Dateien abgelegt. Jede
Datei enthält `expires` (Unix-Zeit) und `value` (beliebiges JSON).
Abgelaufene Einträge werden beim Lesen gelöscht.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Optional

from .config import CONFIG


def _path(key: str) -> Path:
    return CONFIG["cache"]["dir"] / (hashlib.md5(key.encode("utf-8")).hexdigest() + ".json")


def cache_get(key: str) -> Optional[Any]:
    path = _path(key)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or "expires" not in data or "value" not in data:
        return None
    if data["expires"] < time.time():
        try:
            path.unlink()
        except OSError:
            pass
        return None
    return data["value"]


def cache_set(key: str, value: Any, ttl: int) -> None:
    path = _path(key)
    payload = json.dumps(
        {"expires": int(time.time() + ttl), "value": value},
        ensure_ascii=False,
    )
    try:
        CONFIG["cache"]["dir"].mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
    except OSError:
        pass
