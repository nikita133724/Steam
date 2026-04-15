from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess
import sys
import time
import uuid

from src.paths import get_data_dir, get_install_dir, get_installed_exe
from src.update_manager import UpdateManager

APPLY_UPDATE_ARG = "--apply-update"


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _restart(exe: Path) -> None:
    subprocess.Popen([str(exe)], cwd=str(exe.parent))


def _cleanup_bootstrap_dir(data_dir: Path) -> Path:
    bootstrap_dir = data_dir / "bootstrap"
    bootstrap_dir.mkdir(parents=True, exist_ok=True)
    for path in bootstrap_dir.glob("MultiaccountUpdater-*.exe"):
        try:
            path.unlink()
        except OSError:
            pass
    return bootstrap_dir


def _launch_update_helper(current_exe: Path, installed_exe: Path, staged_exe: Path, version: str) -> None:
    bootstrap_dir = _cleanup_bootstrap_dir(get_data_dir())
    helper_exe = bootstrap_dir / f"MultiaccountUpdater-{uuid.uuid4().hex}.exe"
    shutil.copy2(current_exe, helper_exe)
    subprocess.Popen(
        [str(helper_exe), APPLY_UPDATE_ARG, str(installed_exe), str(staged_exe), version],
        cwd=str(bootstrap_dir),
    )


def _apply_staged_update(target_exe: Path, staged_exe: Path) -> bool:
    backup = target_exe.with_suffix(target_exe.suffix + ".bak")
    for _ in range(120):
        try:
            backup.unlink(missing_ok=True)
            if target_exe.exists():
                target_exe.replace(backup)
            staged_exe.replace(target_exe)
            backup.unlink(missing_ok=True)
            return True
        except PermissionError:
            time.sleep(0.5)
        except FileNotFoundError:
            break
        except Exception:
            if backup.exists() and not target_exe.exists():
                try:
                    backup.replace(target_exe)
                except OSError:
                    pass
            break
    return False


def _run_update_helper(argv: list[str]) -> int:
    if len(argv) < 3:
        return 1

    target_exe = Path(argv[0]).resolve()
    staged_exe = Path(argv[1]).resolve()
    version = argv[2]
    manager = UpdateManager(current_exe=target_exe)

    if not staged_exe.exists():
        manager.clear_pending_update()
        return 1

    if not _apply_staged_update(target_exe, staged_exe):
        return 1

    manager.mark_installed(version)
    _restart(target_exe)
    return 0


def bootstrap_startup(argv: list[str] | None = None) -> int | None:
    argv = argv or []
    install_dir = get_install_dir()
    data_dir = get_data_dir()
    install_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    _cleanup_bootstrap_dir(data_dir)

    if argv and argv[0] == APPLY_UPDATE_ARG:
        return _run_update_helper(argv[1:])

    if sys.platform != "win32" or not _is_frozen():
        return None

    current_exe = Path(sys.executable).resolve()
    installed_exe = get_installed_exe().resolve()

    if current_exe != installed_exe:
        shutil.copy2(current_exe, installed_exe)
        _restart(installed_exe)
        return 0

    manager = UpdateManager(current_exe=installed_exe)
    pending = manager.read_pending_update()
    staged_exe = manager.get_staged_exe()
    if pending.get("version") and staged_exe.exists():
        _launch_update_helper(current_exe, installed_exe, staged_exe, str(pending["version"]))
        return 0

    try:
        manifest = manager.fetch_manifest(timeout=8)
        manager.sync_current_with_manifest(manifest)
        if manager.stage_update(manifest, timeout=30):
            pending = manager.read_pending_update()
            if pending.get("version"):
                _launch_update_helper(current_exe, installed_exe, manager.get_staged_exe(), str(pending["version"]))
                return 0
    except Exception:
        # Сетевые/релизные проблемы не должны блокировать запуск UI.
        pass

    return None
