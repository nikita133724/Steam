from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess
import sys
import time
import uuid

from src.paths import APP_NAME, get_data_dir, get_install_dir, get_installed_exe
from src.update_manager import UpdateManager

APPLY_UPDATE_ARG = "--apply-update"
VCRUNTIME_FILES = ("vcruntime140.dll", "msvcp140.dll")


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _restart(exe: Path) -> None:
    subprocess.Popen([str(exe)], cwd=str(exe.parent))


def _desktop_dir_candidates() -> list[Path]:
    candidates: list[Path] = []
    public_desktop = os.getenv("PUBLIC")
    if public_desktop:
        candidates.append(Path(public_desktop) / "Desktop")
    user_profile = os.getenv("USERPROFILE")
    if user_profile:
        candidates.append(Path(user_profile) / "Desktop")
    one_drive = os.getenv("OneDrive")
    if one_drive:
        candidates.append(Path(one_drive) / "Desktop")
    candidates.append(Path.home() / "Desktop")
    unique: list[Path] = []
    seen = set()
    for candidate in candidates:
        key = str(candidate).lower()
        if key not in seen:
            unique.append(candidate)
            seen.add(key)
    return unique


def _find_vc_runtime_installer() -> Path | None:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    for relative in ("assets/vcredist_x64.exe", "assets/VC_redist.x64.exe"):
        candidate = base / relative
        if candidate.exists():
            return candidate
    return None


def _has_vc_runtime() -> bool:
    if sys.platform != "win32":
        return True
    system_root = Path(os.getenv("SystemRoot", r"C:\Windows"))
    search_dirs = [Path(sys.executable).resolve().parent, system_root / "System32", system_root / "SysWOW64"]
    for dll_name in VCRUNTIME_FILES:
        if not any((directory / dll_name).exists() for directory in search_dirs):
            return False
    return True


def ensure_windows_runtime() -> dict:
    if sys.platform != "win32":
        return {"ok": True, "checked": False}

    if _has_vc_runtime():
        return {"ok": True, "checked": True}

    installer = _find_vc_runtime_installer()
    if installer is None:
        return {
            "ok": False,
            "checked": True,
            "message": "Microsoft VC++ Redistributable is missing.",
            "manual_installer": None,
        }

    try:
        completed = subprocess.run(
            [str(installer), "/install", "/quiet", "/norestart"],
            check=False,
            timeout=180,
        )
        if completed.returncode in {0, 1638, 3010} and _has_vc_runtime():
            return {"ok": True, "checked": True, "installed": True}
        return {
            "ok": False,
            "checked": True,
            "message": f"VC++ Redistributable silent install failed with code {completed.returncode}.",
            "manual_installer": str(installer),
        }
    except Exception as exc:
        return {
            "ok": False,
            "checked": True,
            "message": f"VC++ Redistributable install error: {exc}",
            "manual_installer": str(installer),
        }


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


def _ensure_desktop_shortcut(target_exe: Path) -> None:
    if sys.platform != "win32" or not _is_frozen():
        return

    try:
        import winshell  # type: ignore[import-not-found]
        from win32com.client import Dispatch  # type: ignore[import-not-found]
    except Exception:
        return

    try:
        desktop_dir = None
        for candidate in [Path(winshell.desktop()), *_desktop_dir_candidates()]:
            if candidate.exists():
                desktop_dir = candidate
                break
        if desktop_dir is None:
            desktop_dir = Path(winshell.desktop())
            desktop_dir.mkdir(parents=True, exist_ok=True)
        shortcut_path = desktop_dir / f"{APP_NAME}.lnk"
        shell = Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(str(shortcut_path))

        current_target = getattr(shortcut, "TargetPath", "") or getattr(shortcut, "Targetpath", "")
        current_workdir = getattr(shortcut, "WorkingDirectory", "") or getattr(shortcut, "Workingdirectory", "")
        current_icon = getattr(shortcut, "IconLocation", "") or getattr(shortcut, "Iconlocation", "")

        desired_target = str(target_exe)
        desired_workdir = str(target_exe.parent)
        desired_icon = str(target_exe)

        if (
            str(current_target) != desired_target
            or str(current_workdir) != desired_workdir
            or str(current_icon) != desired_icon
        ):
            shortcut.TargetPath = str(target_exe)
            shortcut.WorkingDirectory = str(target_exe.parent)
            # Prefer the embedded EXE icon (set by build flags).
            shortcut.IconLocation = str(target_exe)
            shortcut.Save()
        print(f"Desktop shortcut ready: {shortcut_path}")
    except Exception:
        # Ярлык не должен блокировать запуск приложения.
        return


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

    _ensure_desktop_shortcut(installed_exe)
    return None
