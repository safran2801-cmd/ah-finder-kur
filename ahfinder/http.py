"""HTTP-Wrapper um `requests` mit Parallel-Fetch (ersetzt curl_multi)."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Mapping, Optional

import requests

USER_AGENT = "AlpenHuettenFinder/1.0 (+python-streamlit)"


def _headers(extra: Optional[Mapping[str, str]] = None) -> dict:
    h = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if extra:
        h.update(extra)
    return h


def http_get(url: str, timeout: int = 15, headers: Optional[Mapping[str, str]] = None) -> dict:
    try:
        r = requests.get(url, timeout=(min(10, timeout), timeout), headers=_headers(headers))
        return {"code": r.status_code, "body": r.text, "error": ""}
    except requests.RequestException as e:
        return {"code": 0, "body": None, "error": str(e)}


def http_post(
    url: str,
    payload: Any,
    timeout: int = 30,
    headers: Optional[Mapping[str, str]] = None,
) -> dict:
    body = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    h = _headers(headers)
    if "Content-Type" not in h:
        h["Content-Type"] = "application/json"
    try:
        r = requests.post(url, data=body, timeout=(min(10, timeout), timeout), headers=h)
        return {"code": r.status_code, "body": r.text, "error": ""}
    except requests.RequestException as e:
        return {"code": 0, "body": None, "error": str(e)}


def http_multi_get(items: Mapping[Any, str], timeout: int = 15, max_workers: int = 8) -> dict:
    """Parallele GET-Anfragen, gibt ein Dict {key -> Response} zurück."""
    if not items:
        return {}
    results: dict = {}
    workers = min(max_workers, max(1, len(items)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(http_get, url, timeout): key for key, url in items.items()}
        for fut, key in futures.items():
            try:
                results[key] = fut.result()
            except Exception as e:  # noqa: BLE001
                results[key] = {"code": 0, "body": None, "error": str(e)}
    return results
