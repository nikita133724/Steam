import random
from datetime import datetime
from src.logger import Logger


class AccountManager:
    def __init__(self, config):
        self.config = config
        self.accounts = config.load_accounts()
        self.next_id = self._get_next_id()
    
    def _get_next_id(self):
        if not self.accounts:
            return 1
        return max(a["id"] for a in self.accounts) + 1
    
    def get_accounts(self):
        return self.accounts
    
    def add_account(self, name):
        """Добавляет новый аккаунт без прокси пока"""
        account = {
            "id": self.next_id,
            "name": name,
            "domain": None,  # Будет задан при первом запуске
            "proxy": None,
            "created_at": datetime.now().isoformat(),
            "user_agent": self._generate_user_agent(),
            "locale": "ru-RU",
            "timezone": "Europe/Moscow"
        }
        
        self.accounts.append(account)
        self.config.save_accounts(self.accounts)
        self.next_id += 1
        
        Logger.get_instance().info(f"Created account: {name}")
        return account
    
    def delete_account(self, account_id):
        """Удаляет аккаунт"""
        self.accounts = [a for a in self.accounts if a["id"] != account_id]
        self.config.save_accounts(self.accounts)
        
        # Удаляем профиль
        profile_path = self.config.get_profile_path(account_id)
        if profile_path.exists():
            import shutil
            shutil.rmtree(profile_path)
        
        Logger.get_instance().info(f"Deleted account ID: {account_id}")
        return True
    
    def update_domain(self, account_id, domain):
        """Обновляет домен аккаунта"""
        for account in self.accounts:
            if account["id"] == account_id:
                account["domain"] = domain
                self.config.save_accounts(self.accounts)
                Logger.get_instance().info(f"Updated domain for {account['name']}: {domain}")
                return True
        return False

    def update_proxy(self, account_id, proxy, timezone=None):
        """Обновляет прокси аккаунта"""
        for account in self.accounts:
            if account["id"] == account_id:
                account["proxy"] = proxy
                if timezone:
                    account["timezone"] = timezone
                self.config.save_accounts(self.accounts)
                Logger.get_instance().info(f"Updated proxy for {account['name']}")
                return True
        return False

    
    def _generate_user_agent(self):
        """Генерирует реальный User-Agent"""
        chrome_versions = ["120.0.0.0", "121.0.0.0", "122.0.0.0", "123.0.0.0", "124.0.0.0"]
        version = random.choice(chrome_versions)
        
        return f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version} Safari/537.0"

    def reset_accounts(self):
        """Очищает аккаунты в памяти (после удаления data-файлов)."""
        self.accounts = []
        self.next_id = 1

