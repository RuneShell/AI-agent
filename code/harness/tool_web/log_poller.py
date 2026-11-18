# 1. built-in
import time
import threading

# 2. third-party
import requests

# 3. custom




class LogPoller:
    """여러 모듈의 위젯 정보를 모아 dashboard 서버(/report)로 주기적/즉시 POST한다.
        - pull: register(key, provider) -> key로 등록된 provider()를 이용해 poller가 주기적으로 값을 가져감.
        - push: update(key, widgets, urgent=False)    -> module이 값이 바뀔 때 직접 widget을 보냄.
    """

    def __init__(self, name: str, url: str, interval=5.0):
        self.name = name
        self.url = url
        self.interval = interval

        # register() 에 의해 등록된, widget을 생성하는 callable 목록.
        self._widget_providers = {}      # key -> provider() -> list[dict]
        # push()에 의해 등록된, dashboard로 보낼 widget 목록.
        self._pushed_widgets = {} # key -> list[dict]

        # self._payload = {"source": self.name, "widgets": []}
        self._lock = threading.Lock() # 한 번에 하나의 send_loop만 허용
        self._stop_event = threading.Event()
        self._wake_event = threading.Event() # urgent=True인 update() 호출 시, _send_loop()을 즉시 trigger.
        self._session: requests.Session = None # keep-alive로 연결 유지.
        self._send_timeout = 1.0


    # ──────── life cycle ────────
    def start(self):
        self._session = requests.Session()
        self._send_thread = threading.Thread(target=self._send_loop, daemon=True)
        self._send_thread.start()
    def stop(self):
        if hasattr(self, "_send_thread"):
            self._stop_event.set()
            self._send_thread.join()
            self._session.close()

    # with으로 열고 닫는 데 사용.
    def __enter__(self):
        self.start()
        return self
    def __exit__(self, *exc):
        self.stop()


    # ──────── module API ────────
    # poller <-pull- module
    def register(self, key: str, provider: callable):
        with self._lock:
            self._widget_providers[key] = provider
    def unregister(self, key: str):
        with self._lock:
            self._widget_providers.pop(key, None)
            self._pushed_widgets.pop(key, None)

    # poller <-push- module
    def update(self, key: str, widgets: list[dict], urgent=False):
        with self._lock:
            self._pushed_widgets[key] = widgets
            if urgent:
                self._wake_event.set()

    # ──────── polling ────────
    def _build_payload(self):
        widgets = []

        # extend pulled widgets
        for key, provider in list(self._widget_providers.items()):
            try:
                widgets.extend(provider())
            except Exception as e:
                print(f"Error in provider {key}: {e}")
        # extend pushed widgets
        for items in {k: list(v) for k, v in self._pushed_widgets.items()}.values():
            widgets.extend(items)

        payload = {"source": self.name, "widgets": widgets}
        return payload

    def _send_loop(self):
        server_connected = False
        server_connection_failed = 0
        
        while not self._stop_event.is_set():
            self._wake_event.clear() # 이번에는 urgent가 없다고 가정하고 시작.

            try:
                response = self._session.post(self.url, json=self._build_payload(), timeout=self._send_timeout)
                response.raise_for_status() # raise HTTPError for bad responses (4xx and 5xx)

                # if no error
                if not server_connected:
                    print(f"Connected to dashboard server at {self.url}")
                    server_connected = True
                    server_connection_failed = 0
            except requests.exceptions.Timeout as e: # When server is down.
                server_connection_failed += 1
                # retry 5 times
                if server_connection_failed > 5: 
                    print(f"Connection Timeout..")
                    server_connected = False
                    # TODO: 이 다음에 뭐 해야할지 몰라서 일단 break
                    break
            except Exception as e:
                print("Unexpected Error:", e)

            self._wake_event.wait(self.interval) # wait for either urgent update or interval timeout


