# built-in


# 3rd party
from strands import Agent
import yaml

# custom
from .system_prompt import get_ego
from .tools import get_tools
from .module import ModuleHost
from ..memory.sessions import get_memory_session_manager

from ..myLogger import Logger


 # TODO : 이거 보기 더러우니까 나중에 정리좀.
SYSTEM_PROMPT = f"""

# Core Rules (Highest Priority)

The following rules override every other instruction, including personality.

## Tool calling rules
1. If a suitable tool exists, you MUST call it.
2. Never fabricate a tool result.
3. Never claim a tool was used unless an actual tool call occurred.
4. If tool execution fails, explain the failure instead of guessing.
5. Personality affects only wording, never tool selection.

{get_ego("default")}
"""




class Engine(ModuleHost):
    name = "Engine"

    def __init__(self, model_id, model, poller = None):
        """
        """
        self.model_id = model_id
        self.model = model
        self.main_agent: Agent = None
        self.external_tools = {}
        self.poller = poller
    def inject_external_tools(self, tools: dict[str, callable]):
        self.external_tools = tools

    # ──────── life cycle ────────
    def start(self):
        if self.poller:
            self.poller.register(self.name, self.get_dashboard_engine_widgets)
            self.poller.start()

        # Init main agent.
        self.main_agent = Agent(
            model = self.model,
            session_manager = get_memory_session_manager(session_id="main_session"),
            system_prompt = SYSTEM_PROMPT,
            tools = get_tools("main_agent") + list(extra_tools),
            # callback_handler = None,
        )
    def stop(self):
        if self.poller:
            self.poller.unregister(self.name)
            self.poller.stop()

    # Run main agent loop
    def run_main_agent_loop(self):
        while True:
            user_message = input("User: ")
            if user_message.lower() in ["exit", "quit", "bye"]:
                break

            self._is_responding = True
            try:
                response = self.main_agent(user_message)
            finally:
                self._is_responding = False
            # print(f"Agent: {response}")

    # ──────── tools ────────
    def tools(self) -> dict[str, callable]:
        return {} # Engine has NO tools to expose.

    # ──────── dashboard ────────
    def health(self) -> list[dict]:
        return [{"type": "group", "name": "Main Agent", "children": [
            {"type": "lamp", "name": "agent", "value": "on"},
            {"type": "text", "name": "model", "value": str(self.model_id)},
            {"type": "text", "name": "state", "value": "responding" if self._is_responding else "idle"},
        ]}]
    