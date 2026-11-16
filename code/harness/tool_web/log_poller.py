# 1. built-in
import time
import threading

# 2. third-party
import requests

# 3. custom




class LogPoller:
    def __init__(self, name, url, interval=5):
        self.name = name
        self.url = url
        self.interval = interval

        self._payload = {"source": self.name, "widgets": []}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

        self._subscribers = {}


    def start(self):
        self._send_thread = threading.Thread(target=self._send_loop, daemon=True)
        self._send_thread.start()
    def _send_loop(self):
        while not self._stop_event.is_set():
            try:
                with self._lock:
                    response = requests.post(self.url, json=self._payload, timeout=1)
                if response.status_code != 200:
                    print(response.status_code)
            except requests.exceptions.Timeout as e: # When server is down.
                print(f"Connection Timeout..")
            except requests.exceptions.RequestException as e:
                print(f"Request failed: {e}")
            time.sleep(self.interval)

    def stop(self):
        if hasattr(self, "_send_thread"):
            self._stop_event.set()
            self._send_thread.join()


    # get payloads using Observer Pattern.
    def