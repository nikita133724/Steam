from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import requests

from src.paths import get_data_dir

DEFAULT_REPOSITORY = "nikita133724/Steam"


class UpdateManager:
    def __init__(self, current_exe: Path, current_version: str = "0.0.0"):
        self.current_exe = current_exe
        self.current_version = current_version
        self.data_dir = get_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.version_file = self.data_dir / "version.json"
        self.pending_file = self.data_dir / "pending_update.json"

    def _read_bundled_version(self) -> str | None:
        try:
            base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
            version_file = base / "assets" / "version.txt"
            if not version_file.exists():
                return None
            value = version_file.read_text(encoding="utf-8").strip()
            return value or None
        except Exception:
            return None

    def _read_bundled_repository(self) -> str | None:
        try:
            base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
            repository_file = base / "assets" / "repository.txt"
            if not repository_file.exists():
                return None
            value = repository_file.read_text(encoding="utf-8").strip()
            return value or None
        except Exception:
            return None

    def manifest_url(self) -> str:
        repository = (
            os.getenv("MULTIACCOUNT_REPOSITORY")
            or self._read_bundled_repository()
            or DEFAULT_REPOSITORY
        )
        return f"https://github.com/{repository}/releases/latest/download/manifest.json"

    def read_local_version(self) -> str:
        if not self.version_file.exists():
            return self._read_bundled_version() or self.current_version
        try:
            data = json.loads(self.version_file.read_text(encoding="utf-8"))
            return data.get("version") or self._read_bundled_version() or self.current_version
        except Exception:
            return self._read_bundled_version() or self.current_version

    def write_local_version(self, version: str):
        self.version_file.write_text(
            json.dumps({"version": version}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def read_pending_update(self) -> dict:
        if not self.pending_file.exists():
            return {}
        try:
            return json.loads(self.pending_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def write_pending_update(self, version: str, sha256: str = ""):
        self.pending_file.write_text(
            json.dumps({"version": version, "sha256": sha256}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def clear_pending_update(self):
        self.pending_file.unlink(missing_ok=True)

    def get_staged_exe(self) -> Path:
        return self.current_exe.with_suffix(self.current_exe.suffix + ".new")

    def has_pending_update(self) -> bool:
        pending = self.read_pending_update()
        return bool(pending.get("version")) and self.get_staged_exe().exists()

    def fetch_manifest(self, timeout: int = 8) -> dict:
        response = requests.get(self.manifest_url(), timeout=timeout)
        response.raise_for_status()
        return response.json()

    def check_for_update(self, timeout: int = 8) -> dict:
        manifest = self.fetch_manifest(timeout=timeout)
        self.sync_current_with_manifest(manifest)
        latest_version = str(manifest.get("version") or "")
        current_version = self.read_local_version()
        if not latest_version or latest_version == current_version:
            self.clear_pending_update()
            self.get_staged_exe().unlink(missing_ok=True)
            return {
                "update_available": False,
                "current_version": current_version,
                "latest_version": latest_version or current_version,
                "manifest": manifest,
            }
        return {
            "update_available": True,
            "current_version": current_version,
            "latest_version": latest_version,
            "manifest": manifest,
        }

    def _hash_file(self, path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest().lower()

    def mark_installed(self, version: str):
        self.write_local_version(version)
        self.clear_pending_update()

    def sync_current_with_manifest(self, manifest: dict) -> bool:
        version = str(manifest.get("version") or "")
        expected_hash = str(manifest.get("sha256") or "").lower()
        if not version or not expected_hash or not self.current_exe.exists():
            return False

        if self._hash_file(self.current_exe) != expected_hash:
            return False

        if self.read_local_version() != version:
            self.write_local_version(version)
        self.clear_pending_update()
        self.get_staged_exe().unlink(missing_ok=True)
        return True

    def stage_update(self, manifest: dict, timeout: int = 30) -> bool:
        return self.download_update(manifest, timeout=timeout)

    def download_update(
        self,
        manifest: dict,
        timeout: int = 30,
        progress_callback=None,
        status_callback=None,
        log_callback=None,
    ) -> bool:
        version = str(manifest.get("version") or "")
        url = manifest.get("url")
        expected_hash = str(manifest.get("sha256") or "").lower()
        if not version or not url:
            return False

        local_version = self.read_local_version()
        if version == local_version:
            self.clear_pending_update()
            self.get_staged_exe().unlink(missing_ok=True)
            return False

        target_new = self.get_staged_exe()
        target_new.parent.mkdir(parents=True, exist_ok=True)

        pending = self.read_pending_update()
        if pending.get("version") == version and target_new.exists():
            if expected_hash and self._hash_file(target_new) != expected_hash:
                target_new.unlink(missing_ok=True)
                self.clear_pending_update()
            else:
                if progress_callback:
                    progress_callback(100)
                return True
        else:
            target_new.unlink(missing_ok=True)

        if status_callback:
            status_callback("Downloading update...")
        if progress_callback:
            progress_callback(0)
        with requests.get(url, stream=True, timeout=timeout) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length") or 0)
            downloaded = 0
            with target_new.open("wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0 and progress_callback:
                            progress_callback(min(100, int(downloaded * 100 / total)))

        if status_callback:
            status_callback("Verifying update...")
        if expected_hash and self._hash_file(target_new) != expected_hash:
            target_new.unlink(missing_ok=True)
            raise ValueError("Downloaded update hash mismatch")

        self.write_pending_update(version, expected_hash)
        if progress_callback:
            progress_callback(100)
        if log_callback:
            log_callback(f"Update {version} downloaded to {target_new}")
        return True
