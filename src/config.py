import json
import os
from pathlib import Path

class Config:
    def __init__(self):
        self.base_dir = Path.home("Multiaccount")
        self.base_dir.mkdir(exist_ok=True)
        
        self.config_file = self.base_dir / "config.json"
        self.accounts_file = self.base_dir / "accounts.json"
        self.profiles_dir = self.base_dir / "profiles"
        self.logs_dir = self.base_dir / "logs"
        
        self.profiles_dir.mkdir(exist_ok=True)
        self.logs_dir.mkdir(exist_ok=True)
        
        self.data = self.load_config()
        self.lang = self.load_language()
    
    def load_config(self):
        if self.config_file.exists():
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"language": None, "first_run": True}
    
    def save_config(self):
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
    
    def load_language(self):
        lang = self.data.get("language", "ru")
        lang_file = Path(__file__).parent.parent / "assets" / f"{lang}.json"
        if lang_file.exists():
            with open(lang_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    
    def set_language(self, lang):
        self.data["language"] = lang
        self.save_config()
        self.lang = self.load_language()
    
    def get_text(self, key):
        return self.lang.get(key, key)
    
    def load_accounts(self):
        if self.accounts_file.exists():
            with open(self.accounts_file, 'r', encoding='utf-8') as f:
                return json.load(f).get("accounts", [])
        return []
    
    def save_accounts(self, accounts):
        with open(self.accounts_file, 'w', encoding='utf-8') as f:
            json.dump({"accounts": accounts}, f, indent=2, ensure_ascii=False)
    
    def get_profile_path(self, account_id):
        return self.profiles_dir / f"account_{account_id}"
