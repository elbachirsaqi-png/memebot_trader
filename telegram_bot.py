import requests

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
        requests.post(url, data=payload)

    def get_updates(self):

        url = f"{self.base_url}/getUpdates"

        params = {}
        if self.last_update_id:
            params["offset"] = self.last_update_id + 1

        response = requests.get(url, params=params)
        data = response.json()

        if "result" not in data:
            return []

        updates = data["result"]

        if updates:
            self.last_update_id = updates[-1]["update_id"]

        return updates