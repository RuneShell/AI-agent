# built-in


# 3rd party
import yaml

# custom
from .configs import LOG_DASHBOARD_URL, LOG_POLLING_INTERVAL, BROKER_HTTP_SERVER_URL

from .model.load_model import load_model
from .harness.engine import Engine
from .harness.module import ModuleHost
from .harness.tool_research.research_module import ResearchModule
from .harness.tool_web.web_module import WebModule

from .log_poller import LogPoller
from .myLogger import Logger

from .envWrap import merge_dicts_by_keys

#-------------------------------------------------
# Config
#-------------------------------------------------

with open("local.yaml", "r") as f:
    local_config = yaml.safe_load(f)

MODEL_ID = local_config.get("MODEL_ID")
USER_MESSAGE = local_config.get("USER_MESSAGE")
RESEARCH_DB_CONFIG = local_config["RESEARCH_DB_CONFIG"] # psycopg.connect() 인자 (host, port, dbname, user, password) # TODO: 이거 최신 갱신됨?
RESEARCH_DB_OPTIONS = local_config["RESEARCH_DB_OPTIONS"] # TODO
DISCORD_WEBHOOK_URL = local_config.get("keys", {}).get("DISCORD_WEBHOOK_URL", "")


logger = Logger(log_dir="./logs", runner_name="record", console=True, file=True, discord=False)




def new_poller(source: str) -> LogPoller:
    return LogPoller(source, LOG_DASHBOARD_URL, interval=LOG_POLLING_INTERVAL)


#-------------------------------------------------
# Main loop
#-------------------------------------------------
def main():
    """
    
    """

    model = load_model(MODEL_ID)


    # Generate Life-cycled modules.
    engine   = Engine(model_id=MODEL_ID, model=model, poller=new_poller("Engine"))
    research = ResearchModule(model, RESEARCH_DB_CONFIG, RESEARCH_DB_OPTIONS, poller=new_poller("Tool: Research"))
    web      = WebModule(*BROKER_HTTP_SERVER_URL, poller=new_poller("Tool: Web"))

    # Inject required tools each other.
    # engine_tools    = engine.tools()
    research_tools  = research.tools()
    web_tools       = web.tools()
    engine.inject_external_tools(merge_dicts_by_keys([research_tools, web_tools],
                                                     ["research", "extend_research", "chunk_document",
                                                      "web_search", "web_fetch", "web_find"]))
    research.inject_external_tools(merge_dicts_by_keys([web_tools], 
                                                       ["web_search", "web_fetch", "web_find"]))
    web.inject_external_tools(merge_dicts_by_keys([research_tools], 
                                                  ["chunk_document"]))


    # Generate Engine and run main agent loop - with Dashboard Poller.
    with ModuleHost(engine, research, web): # 앞에서부터 켜고, 뒤에서부터 끈다.
        engine.run_main_agent_loop()


if __name__ == "__main__":
    main()