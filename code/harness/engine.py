# built-in


# 3rd party
from strands import Agent
import yaml

# custom
from model.load_model import load_model
from harness.system_prompt import get_ego
from harness.tools import get_tools
from memory.sessions import get_memory_session_manager




from myLogger import Logger



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




class Engine:
    def __init__(self, model_id):
        self.model = load_model(model_id)

        # Init main agent.
        self.main_agent = Agent(
            model = self.model,
            session_manager = get_memory_session_manager(session_id="main_session"),
            system_prompt = SYSTEM_PROMPT,
            tools = get_tools("main_agent"),
            # callback_handler = None,
        )


    def run_main_agent_loop(self):
        while True:
            user_message = input("User: ")
            if user_message.lower() in ["exit", "quit", "bye"]:
                break

            response = self.main_agent(user_message)
            # print(f"Agent: {response}")