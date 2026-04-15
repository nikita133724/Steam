from datetime import datetime
from src.device_profiles import get_random_device_profile, normalize_device_profile
from src.logger import Logger


class AccountManager:
    def __init__(self, config):
        self.config = config
        self.accounts = config.load_accounts()
        self._normalize_accounts()
        self.next_id = self._get_next_id()
        self.logger = Logger.get_instance()

    def _get_next_id(self):
        if not self.accounts:
            return 1
        return max(a["id"] for a in self.accounts) + 1

    def get_accounts(self):
        return self.accounts

    def _normalize_accounts(self):
        changed = False
        for account in self.accounts:
            if not account.get("created_at"):
                account["created_at"] = datetime.now().isoformat()
                changed = True
            normalized_profile = normalize_device_profile(account.get("device_profile"))
            if account.get("device_profile") != normalized_profile:
                account["device_profile"] = normalized_profile
                changed = True
            if not account.get("user_agent"):
                account["user_agent"] = account["device_profile"]["user_agent"]
                changed = True
            if not account.get("locale"):
                account["locale"] = "ru-RU"
                changed = True
            if not account.get("timezone"):
                account["timezone"] = "Europe/Moscow"
                changed = True
        if changed:
            self.config.save_accounts(self.accounts)

    def add_account(self, name):
        account = {
            "id": self.next_id,
            "name": name,
            "domain": None,
            "proxy": None,
            "created_at": datetime.now().isoformat(),
            "device_profile": get_random_device_profile(),
            "user_agent": None,
            "locale": "ru-RU",
            "timezone": "Europe/Moscow"
        }
        account["user_agent"] = account["device_profile"]["user_agent"]

        self.accounts.append(account)
        self.config.save_accounts(self.accounts)
        self.next_id += 1

        self.logger.info(f"Created account: {name}")
        return account

    def delete_account(self, account_id):
        self.accounts = [a for a in self.accounts if a["id"] != account_id]
        self.config.save_accounts(self.accounts)

        profile_path = self.config.get_profile_path(account_id)
        if profile_path.exists():
            import shutil
            shutil.rmtree(profile_path)

        self.logger.info(f"Deleted account ID: {account_id}")
        return True

    def update_domain(self, account_id, domain):
        for account in self.accounts:
            if account["id"] == account_id:
                account["domain"] = domain
                self.config.save_accounts(self.accounts)
                self.logger.info(f"Updated domain for {account['name']}: {domain}")
                return True
        return False

    def update_proxy(self, account_id, proxy, timezone=None):
        for account in self.accounts:
            if account["id"] == account_id:
                account["proxy"] = proxy
                account["proxy_raw"] = (proxy or {}).get("raw")
                if timezone:
                    account["timezone"] = timezone
                self.config.save_accounts(self.accounts)
                self.logger.info(f"Updated proxy for {account['name']}")
                return True
        return False

    def _generate_user_agent(self):
        return get_random_device_profile()["user_agent"]

    def reset_accounts(self):
        """Очищает аккаунты в памяти (после удаления data-файлов)."""
        self.accounts = []
        self.next_id = 1
