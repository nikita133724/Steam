import pkg_resources
import requests
from packaging import version


def _safe_current_version() -> str:
    """Best-effort current version for non-wheel/source installs."""
    try:
        return pkg_resources.get_distribution("open-interpreter").version
    except Exception:
        return "0.0.0"


def check_for_update():
    # Fetch the latest version from the PyPI API
    response = requests.get(f"https://pypi.org/pypi/open-interpreter/json")
    latest_version = response.json()["info"]["version"]

    # Get the current version using pkg_resources
    current_version = _safe_current_version()

    return version.parse(latest_version) > version.parse(current_version)
