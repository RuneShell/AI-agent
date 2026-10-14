
# built-in

# 3rd party
from strands import Agent

# custom
from harness.tools import get_tools

from envWrap import read_md



class ResearchAgents:
    planner: Agent = None
    workers: dict[int, Agent] = None

    def __init__(self):
        self.system_prompt_planner = read_md(r"harness/system_prompts/planner.md")
        self.system_prompt_worker = read_md(r"harness/system_prompts/worker.md")



    def set_planner(self, tools, goals, prompt) -> Agent:
        planner = Agent(
            model = None, # TODO : set model
            system_prompt = self.system_prompt_planner,
            tools = None # TODO : set tools
        )
        # TODO : logger
        self.planner = planner

    def set_worker(self) -> Agent:
        worker = Agent(
            model = None, # TODO : set model
            system_prompt = self.system_prompt_worker,
            tools = None # TODO : set tools
        )   
        # TODO : logger
        return worker



    def Plan(self):
        pass
        # Set Planner agent

        tools = get_tools("research_planner")
        goals = get_goals()
        prompt = self.system_prompt_planner + "\n" + user_input

        self.set_planner()
        # TODO : run planner - new session, get response

    def Execute(self, worker): # ?
        pass
        # Set Worker Agent
        # TODO : tool set
        # TODO : system prompt + Intent + workdir..
        # TODO : resotre prev session - using exploration DB ID, intent ID
        #
        # TODO : run worker - resume session or compacted session / return 
        
    