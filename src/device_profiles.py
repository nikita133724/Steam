from __future__ import annotations

import json
import random
from pathlib import Path
import sys


def _load_profiles() -> list[dict]:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    data_path = base / "assets" / "device_profiles.json"
    with data_path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    profiles = data.get("profiles", [])
    if not profiles:
        raise RuntimeError("device_profiles.json does not contain any profiles")
    return profiles


DEVICE_PROFILES = _load_profiles()
DEVICE_PROFILES_BY_ID = {profile["id"]: profile for profile in DEVICE_PROFILES}
DEFAULT_DEVICE_PROFILE = dict(DEVICE_PROFILES[0])


def _copy_profile(profile: dict) -> dict:
    return json.loads(json.dumps(profile))


def get_random_device_profile() -> dict:
    return _copy_profile(random.choice(DEVICE_PROFILES))


def normalize_device_profile(profile: dict | None) -> dict:
    if not profile:
        return get_random_device_profile()

    profile_id = profile.get("id")
    if profile_id in DEVICE_PROFILES_BY_ID:
        merged = _copy_profile(DEVICE_PROFILES_BY_ID[profile_id])
        merged.update({k: v for k, v in profile.items() if v is not None})
        return merged

    merged = _copy_profile(DEFAULT_DEVICE_PROFILE)
    merged.update({k: v for k, v in profile.items() if v is not None})
    return merged
