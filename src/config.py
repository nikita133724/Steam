from pathlib import Path
import json
import sys
import os
import shutil


class Config:
    def __init__(self):
        self.base_dir = Path.home() / "Multiaccount"
        self.base_dir.mkdir(exist_ok=True)

        self.config_file = self.base_dir / "config.json"
        self.accounts_file = self.base_dir / "accounts.json"

        self.profiles_dir = self.base_dir / "profiles"
        self.logs_dir = self.base_dir / "logs"
        self.browsers_dir = self.base_dir / "browsers"

        self.profiles_dir.mkdir(exist_ok=True)
        self.logs_dir.mkdir(exist_ok=True)
        self.browsers_dir.mkdir(exist_ok=True)

        self.data = self.load_config()
        self.lang = self.load_language()

    # 🔥 FIX: PyInstaller-safe путь
    def resource_path(self, relative):
        base = getattr(sys, "_MEIPASS", Path(__file__).parent.parent)
        return Path(base) / relative

    def load_config(self):
        if self.config_file.exists():
            return json.loads(self.config_file.read_text(encoding="utf-8"))
        return {"language": None, "first_run": True}

    def save_config(self):
        self.config_file.write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    # 🔥 FIXED VERSION (единственная!)
    def load_language(self):
        lang = self.data.get("language", "ru")

        lang_file = self.resource_path(f"assets/{lang}.json")

        if lang_file.exists():
            return json.loads(lang_file.read_text(encoding="utf-8"))

        return {}

    def set_language(self, lang):
        self.data["language"] = lang
        self.save_config()
        self.lang = self.load_language()

    def load_accounts(self):
        if self.accounts_file.exists():
            return json.loads(self.accounts_file.read_text(encoding="utf-8")).get("accounts", [])
        return []

    def save_accounts(self, accounts):
        self.accounts_file.write_text(
            json.dumps({"accounts": accounts}, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    def get_profile_path(self, account_id):
        return self.profiles_dir / f"account_{account_id}"

    def clear_runtime_data(self):
        for path in [self.accounts_file, self.profiles_dir, self.logs_dir, self.browsers_dir]:
            if path.is_file():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                shutil.rmtree(path, ignore_errors=True)

        self.profiles_dir.mkdir(exist_ok=True)
        self.logs_dir.mkdir(exist_ok=True)
        self.browsers_dir.mkdir(exist_ok=True)