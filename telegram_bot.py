import time
import threading
import requests
from collections import deque
from config import BOT_TOKEN, CHAT_ID

class TelegramBot:

    def __init__(self, token, chat_id):
        self._token   = token
        self._chat_id = chat_id
        self._queue   = deque()
        self._lock    = threading.Lock()
        self._url     = (
            f"https://api.telegram.org"
            f"/bot{token}/sendMessage"
        )

    def send(self, msg):
        with self._lock:
            self._queue.append(str(msg))

    def run(self):
        while True:
            try:
                msg = None
                with self._lock:
                    if self._queue:
                        msg = self._queue.popleft()
                if msg:
                    for _ in range(3):
                        try:
                            requests.post(
                                self._url,
                                data={
                                    "chat_id": self._chat_id,
                                    "text"   : msg,
                                },
                                timeout=10
                            )
                            break
                        except Exception:
                            time.sleep(2)
                else:
                    time.sleep(0.1)
            except Exception as e:
                print(f"[TG ERR] {e}")
                time.sleep(2)
