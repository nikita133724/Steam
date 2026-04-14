import hashlib
import json
from pathlib import Path
import sys

EXE_PATH = Path("dist/Multiaccount.exe")

def sha256(file_path):
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def main(version, url):
    if not EXE_PATH.exists():
        raise FileNotFoundError(f"Missing build output: {EXE_PATH}")

    manifest = {
        "version": version,
        "url": url,
        "sha256": sha256(EXE_PATH)
    }

    with open("manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


if __name__ == "__main__":
    version = sys.argv[1]  # ВАЖНО: без lstrip("v")

    main(
        version=version,
        url=f"https://github.com/nikita133724/Steam/releases/download/{version}/Multiaccount.exe"
    )