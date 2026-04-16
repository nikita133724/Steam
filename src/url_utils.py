from __future__ import annotations

from urllib.parse import urlparse


def normalize_target_url(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        raise ValueError("URL is empty")

    candidate = raw if "://" in raw else f"https://{raw}"
    parsed = urlparse(candidate)

    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("Only http/https URLs are supported")
    if not parsed.hostname:
        raise ValueError("Host is missing")
    if any(char.isspace() for char in candidate):
        raise ValueError("URL contains spaces")

    return candidate
