from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import Config
from src.device_profiles import DEVICE_PROFILES, normalize_device_profile
from src.update_manager import UpdateManager
from src.url_utils import normalize_target_url


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def check_json_assets() -> None:
    for relative in ("assets/ru.json", "assets/en.json", "assets/device_profiles.json"):
        with (ROOT / relative).open("r", encoding="utf-8") as fh:
            json.load(fh)


def check_device_profiles() -> None:
    assert_true(len(DEVICE_PROFILES) >= 100, "device profile pool must contain at least 100 profiles")
    sample = normalize_device_profile(DEVICE_PROFILES[0])
    assert_true(bool(sample.get("user_agent")), "device profile must contain user_agent")
    assert_true(bool(sample.get("viewport")), "device profile must contain viewport")


def check_url_normalization() -> None:
    assert_true(
        normalize_target_url("example.com") == "https://example.com",
        "URL normalization failed for bare hostname",
    )
    assert_true(
        normalize_target_url("https://example.com/path") == "https://example.com/path",
        "URL normalization changed valid URL unexpectedly",
    )


def check_config_and_updates() -> None:
    config = Config()
    manager = UpdateManager(current_exe=Path(sys.executable))
    version = manager.read_local_version()
    assert_true(bool(version), "local version must not be empty")
    manifest_url = manager.manifest_url()
    assert_true(manifest_url.endswith("/manifest.json"), "manifest URL must end with manifest.json")
    assert_true(config.resource_path("assets/repository.txt").exists(), "repository.txt must be bundled")


def main() -> int:
    check_json_assets()
    check_device_profiles()
    check_url_normalization()
    check_config_and_updates()
    print("smoke-check: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
