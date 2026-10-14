# built-in


# 3rd party
import yaml

# custom
from harness.engine import Engine

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


engine = Engine(model_id=MODEL_ID)

#-------------------------------------------------
# Main loop
#-------------------------------------------------
if __name__ == "__main__":
    engine.run_main_agent_loop()