from __future__ import annotations

import random


DEVICE_PROFILES = [
    {
        "id": "win11_chrome_136",
        "label": "Windows 11 PC",
        "kind": "desktop",
        "brand": "Microsoft",
        "model": "Desktop",
        "os": "Windows 11",
        "browser": "Chrome 136",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.7103.114 Safari/537.36",
        "viewport": {"width": 1600, "height": 900},
        "screen": {"width": 1600, "height": 900},
        "device_scale_factor": 1.0,
        "is_mobile": False,
        "has_touch": False,
        "platform": "Win32",
        "hardware_concurrency": 8,
        "device_memory": 8,
        "max_touch_points": 0,
        "color_scheme": "light",
    },
    {
        "id": "win10_edge_135",
        "label": "Windows 10 PC",
        "kind": "desktop",
        "brand": "Microsoft",
        "model": "Desktop",
        "os": "Windows 10",
        "browser": "Edge 135",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.7049.85 Safari/537.36 Edg/135.0.3179.73",
        "viewport": {"width": 1536, "height": 864},
        "screen": {"width": 1536, "height": 864},
        "device_scale_factor": 1.25,
        "is_mobile": False,
        "has_touch": False,
        "platform": "Win32",
        "hardware_concurrency": 8,
        "device_memory": 8,
        "max_touch_points": 0,
        "color_scheme": "light",
    },
    {
        "id": "pixel_8",
        "label": "Google Pixel 8",
        "kind": "mobile",
        "brand": "Google",
        "model": "Pixel 8",
        "os": "Android 14",
        "browser": "Chrome Mobile 136",
        "user_agent": "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.7103.114 Mobile Safari/537.36",
        "viewport": {"width": 412, "height": 915},
        "screen": {"width": 412, "height": 915},
        "device_scale_factor": 2.625,
        "is_mobile": True,
        "has_touch": True,
        "platform": "Linux armv8l",
        "hardware_concurrency": 8,
        "device_memory": 8,
        "max_touch_points": 5,
        "color_scheme": "light",
    },
    {
        "id": "galaxy_a55",
        "label": "Samsung Galaxy A55",
        "kind": "mobile",
        "brand": "Samsung",
        "model": "Galaxy A55",
        "os": "Android 14",
        "browser": "Chrome Mobile 136",
        "user_agent": "Mozilla/5.0 (Linux; Android 14; SM-A556B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.7103.114 Mobile Safari/537.36",
        "viewport": {"width": 412, "height": 915},
        "screen": {"width": 412, "height": 915},
        "device_scale_factor": 2.625,
        "is_mobile": True,
        "has_touch": True,
        "platform": "Linux armv8l",
        "hardware_concurrency": 8,
        "device_memory": 8,
        "max_touch_points": 5,
        "color_scheme": "light",
    },
    {
        "id": "pixel_9_pro_xl",
        "label": "Google Pixel 9 Pro XL",
        "kind": "mobile",
        "brand": "Google",
        "model": "Pixel 9 Pro XL",
        "os": "Android 15",
        "browser": "Chrome Mobile 136",
        "user_agent": "Mozilla/5.0 (Linux; Android 15; Pixel 9 Pro XL) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.7103.114 Mobile Safari/537.36",
        "viewport": {"width": 448, "height": 998},
        "screen": {"width": 448, "height": 998},
        "device_scale_factor": 3,
        "is_mobile": True,
        "has_touch": True,
        "platform": "Linux armv8l",
        "hardware_concurrency": 8,
        "device_memory": 16,
        "max_touch_points": 5,
        "color_scheme": "light",
    },
    {
        "id": "galaxy_s24",
        "label": "Samsung Galaxy S24",
        "kind": "mobile",
        "brand": "Samsung",
        "model": "Galaxy S24",
        "os": "Android 14",
        "browser": "Chrome Mobile 136",
        "user_agent": "Mozilla/5.0 (Linux; Android 14; SM-S921B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.7103.114 Mobile Safari/537.36",
        "viewport": {"width": 412, "height": 915},
        "screen": {"width": 412, "height": 915},
        "device_scale_factor": 2.625,
        "is_mobile": True,
        "has_touch": True,
        "platform": "Linux armv8l",
        "hardware_concurrency": 8,
        "device_memory": 8,
        "max_touch_points": 5,
        "color_scheme": "light",
    },
]

DEFAULT_DEVICE_PROFILE = DEVICE_PROFILES[0]


def get_random_device_profile() -> dict:
    return dict(random.choice(DEVICE_PROFILES))


def normalize_device_profile(profile: dict | None) -> dict:
    if not profile:
        return dict(get_random_device_profile())

    profile_id = profile.get("id")
    for item in DEVICE_PROFILES:
        if item["id"] == profile_id:
            merged = dict(item)
            merged.update({k: v for k, v in profile.items() if v is not None})
            return merged

    merged = dict(DEFAULT_DEVICE_PROFILE)
    merged.update({k: v for k, v in profile.items() if v is not None})
    return merged
