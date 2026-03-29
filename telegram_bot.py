import requests
import time

class TelegramBot:

    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.last_update_id = None

        self._clear_old_updates()

    def _clear_old_updates(self):
        url = f"{self.base_url}/getUpdates"
        response = requests.get(url)
        data = response.json()

        if "result" in data and data["result"]:
            self.last_update_id = data["result"][-1]["update_id"]

    def send_message(self, text):
        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text
        }
        for attempt in range(3):  # 3 tentatives
            try:
                r = requests.post(url, data=payload, timeout=10)
                if r.status_code == 200:
                    return
            except Exception as e:
                print(f"⚠ Telegram send error (attempt {attempt+1}): {e}")
                time.sleep(2)

    def get_updates(self):
        url = f"{self.base_url}/getUpdates"
        params = {}
        if self.last_update_id:
            params["offset"] = self.last_update_id + 1

        for attempt in range(3):  # 3 tentatives
            try:
                response = requests.get(url, params=params, timeout=10)
                data = response.json()

                if "result" not in data:
                    return []

                updates = data["result"]
                if updates:
                    self.last_update_id = updates[-1]["update_id"]
                return updates

            except Exception as e:
                print(f"⚠ Telegram get_updates error (attempt {attempt+1}): {e}")
                time.sleep(2)

        return []  # retourner liste vide si toutes les tentatives échouent