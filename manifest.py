import hashlib
import json
from pathlib import Path
import sys


def sha256(file_path: Path):
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def find_exe():
    # 🔥 FIX: onefile = всегда один файл
    exe_path = Path("dist") / "Multiaccount.exe"
    return exe_path if exe_path.exists() else None


def main(version, url):
    exe_path = find_exe()

    if not exe_path:
        raise FileNotFoundError("Missing dist/Multiaccount.exe")

    manifest = {
        "version": version,
        "url": url,
        "sha256": sha256(exe_path)
    }

    with open("manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


if __name__ == "__main__":
    version = sys.argv[1]

    main(
        version=version,
        url=f"https://github.com/nikita133724/Steam/releases/download/{version}/Multiaccount.exe"
    )