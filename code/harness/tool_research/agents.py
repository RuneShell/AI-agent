
# built-in

# 3rd party
from strands import Agent

# custom
from harness.tools import get_tools
from harness.tool_research.db import ResearchDB

from envWrap import read_md



class ResearchAgents:
    planner: Agent = None
    workers: dict[int, Agent] = None

    def __init__(self, model: Agent):
        self.system_prompt_planner = read_md(r"harness/system_prompts/planner.md")
        # prompt += characteristics
        self.system_prompt_worker = read_md(r"harness/system_prompts/worker.md")
        self.model = model



    def reset_planner(self) -> Agent:
        if self.planner:
            self.planner.shutdown()

        prompt = self.system_prompt_planner

        planner = Agent(
            model = self.model,
            system_prompt = prompt,
            tools = get_tools("research_planner")
        )
        # TODO : logger
        self.planner = planner

    def execute_planner(self, task_report: str):
        # Planner can be reused in condition.
        if self.planner is None:
            self.reset_planner()

        prompt = "" + task_report
        response = self.planner(prompt)

        # TODO : logger
        return response

    def execute_worker(self, intent: str) -> Agent:
        worker = Agent(
            model = self.model,
            system_prompt = self.system_prompt_worker,
            tools = None # TODO : set tools
        )   

        # 일단 pause고 뭐고간에 일단 구현 안하고 바로 더함.
        # TODO : 전용 workdir이 필요할 수도.
        self.workers.append(worker)
        # TODO : logger


        prompt = "" + intent
        response = worker(prompt)

        self.workers.remove(worker)

        return response



    def Plan(self, task_report: str):
        # Set Planner agent

        self.reset_planner()
        # TODO : Planner set goals with `?` tool.
        response = self.execute_planner(task_report)

    def Execute(self, intent: str): # ?
        # Set Worker Agent
        
        # TODO : resotre prev session - using exploration DB ID, intent ID
        # TODO : run worker - resume session or compacted session / return 
        self.execute_worker(intent)
        
    