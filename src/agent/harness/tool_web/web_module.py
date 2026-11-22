# 1. built-in
import os

# 2. third-party
from strands import tool

# 3. custom
from .broker import Broker

from ...log_poller import LogPoller

from ...configs import DOCUMENT_EXTENSIONS

class WebModule:
    """tool_web을 main agent 옆에 붙이는 ToolModule. (규격: harness/module.py)
        - Broker(HTTP server + browser)와 자기 LogPoller의 수명을 소유한다.
        - agent에는 web tool만 노출하고, Broker는 밖으로 드러내지 않는다.
    """
    name = "Tool: Web"

    def __init__(self, host_ip: str = None, host_port: int = None, poller: LogPoller = None):
        self.server_address = (host_ip, host_port)
        self.external_tools = {}
        self.poller = poller # None이면 dashboard 보고 없이 동작.

        # web fetch - broker server
        self.broker: Broker = None
    def inject_external_tools(self, tools: dict[str, callable]):
        self.external_tools = tools

    # ──────── life cycle ────────
    def start(self):
        if self.broker:
            return

        # poller를 먼저 켜고 나중에 꺼야 Broker의 기동/종료 과정도 dashboard에 보인다.
        if self.poller:
            self.poller.register(self.name, self.health)
            self.poller.start()
            
        try:
            self.broker = Broker(*self.server_address)
            self.broker.start()
        except Exception:
            self.stop() # ModuleHost는 실패한 모듈을 되돌리지 않으므로 여기서 정리.
            raise
    def stop(self):
        try:
            if self.broker:
                self.broker.stop()
        finally:
            self.broker = None
            if self.poller:
                self.poller.unregister(self.name)
                self.poller.stop()

    # ──────── agent tools ────────
    def tools(self) -> dict[str, callable]:
        # 구현된 tool만 노출한다. (web_search / web_find / web_read는 구현 후 추가)
        return {
            "web_search": self._create_web_search(),
            "web_fetch": self._create_web_fetch(),
            "web_find": self._create_web_find(),
        }

    def _create_web_fetch(self):
        @tool(name="web_fetch", description="Fetch a web page by URL and return the result.")
        def web_fetch(url: str) -> str:
            if not self.broker:
                return "Web broker server is not running."
            saved_path = self.broker.fetch(url)

            # saved_path may valid, and Check if it's a Document.
            cond1 =  os.path.splittext(saved_path)[1] in DOCUMENT_EXTENSIONS:
            # if chunking tool is valid
            chunk_document_tool = self.external_tools.get("chunk_document")
            cond2 = chunk_document_tool is not None

            if cond1 and cond2:
                try:
                    chunk_report = chunk_document_tool(saved_path)
                    return f"`{url}` fetched and saved to `{saved_path}`. Chunking report:\n{chunk_report}"
                except Exception as e:
                    return f"`{url}` fetched and saved to `{saved_path}`, but chunking system failed: {e}"
            else:
                return f"`{url}` fetched and saved to `{saved_path}`."


        return web_fetch

    # ──── 미구현 ────
    def _create_web_search(self):
        @tool(name="web_search", description="")
        def web_search(query: str) -> list[dict]:
            return

        return web_search

    def _create_web_find(self):
        @tool(name="web_find", description="")
        def web_find(filename: str, selector: str) -> dict:
            return

        return web_find

    # ──────── dashboard ────────
    def health(self) -> list[dict]:
        broker = self.broker # poller thread에서 호출되므로, 검사 후 None이 되지 않게 고정. (race condition 방지)
        if not broker:
            return []
        return broker.get_dashboard_broker_widgets()
