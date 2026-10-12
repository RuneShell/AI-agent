# built-in


# 3rd party
from strands import Agent
import yaml

# custom
from model.load_model import load_model
from harness.system_prompt import get_ego
from harness.tools import initialize_tools_for_main
from memory.sessions import get_memory_session_manager

from myLogger import Logger



#-------------------------------------------------
# Config
#-------------------------------------------------

with open("local.yaml", "r") as f:
    local_config = yaml.safe_load(f)

MODEL_ID = local_config.get("MODEL_ID")
USER_MESSAGE = local_config.get("USER_MESSAGE")
DISCORD_WEBHOOK_URL = local_config.get("keys", {}).get("DISCORD_WEBHOOK_URL", "")


logger = Logger(log_dir="./logs", runner_name="record", console=True, file=True, discord=False)


#-------------------------------------------------
# core
#-------------------------------------------------


# tool policy는 항상 personality보다 우선한다.
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


# Generate agent.
model= load_model(MODEL_ID)

TOOLS_FOR_MAIN = initialize_tools_for_main(model=model)

agent = Agent(
    model = model,
    session_manager = get_memory_session_manager(session_id="main_session"),
    system_prompt = SYSTEM_PROMPT,
    tools = TOOLS_FOR_MAIN,
    # callback_handler = None,
)

#-------------------------------------------------
# Main loop
#-------------------------------------------------
if __name__ == "__main__":
    response = agent(USER_MESSAGE)

    while True:
        user_message = input("User: ")
        if user_message.lower() in ["exit", "quit", "bye"]:
            break


        response = agent(user_message)
        # print(f"Agent: {response}")