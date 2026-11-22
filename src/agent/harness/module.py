# 1. built-in
from typing import Protocol, Any

# 2. third-party

# 3. custom


class ToolModule(Protocol):
    """main agent 옆에 붙는 고급 tool 묶음(tool_web, tool_research ...)의 규격.
        - start()/stop(): 서버, 브라우저, 자기 LogPoller 등 수명이 있는 자원을 기동/종료.
        - tools(): agent에 노출할 tool 목록.
    """
    name: str
    # ──────── init ────────
    def inject_external_tools(self, tools: list[Any]) -> None: ...
    # ──────── life cycle ────────
    def start(self) -> None: ...
    def stop(self) -> None: ...
    # ──────── agent tools ────────
    def tools(self) -> dict[str, callable]: ...
    # ──────── dashboard ────────
    def health(self) -> list[dict]: ... # Dashboard에 표시할 상태 카드. (`poller=None`이면 무시됨)


class ModuleHost:
    """ToolModule들의 기동/종료 순서를 관리한다. `with`로 사용.
        - modules는 의존 순서대로 전달할 것. (기동: 앞→뒤 / 종료: 뒤→앞)
        - dashboard는 모른다. 보고는 각 모듈이 자기 LogPoller로 직접 한다.
    """

    def __init__(self, modules: list[ToolModule]):
        self.modules = modules
        self._started = []

    # ──────── life cycle ────────
    def start(self):
        try:
            for module in self.modules:
                module.start()
                self._started.append(module)
        except Exception:
            self.stop() # 중간에 실패하면 이미 켠 것만 되돌림.
            raise
    def stop(self):
        for module in reversed(self._started):
            try:
                module.stop()
            except Exception as e: # 하나가 실패해도 나머지는 계속 종료.
                print(f"Error stopping module {module.name}: {e}")
        self._started = []


    def __enter__(self):
        self.start()
        return self
    def __exit__(self, *exc):
        self.stop()

    # ──────── agent API ────────
    def tools(self) -> list[Any]:
        return [tool for module in self.modules for tool in module.tools()]
