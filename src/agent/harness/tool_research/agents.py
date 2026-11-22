
# built-in

# 3rd party
from strands import Agent

# custom
from ..tools import get_tools

from ...envWrap import read_md



class ResearchAgents:
    planner: Agent = None

    def __init__(self, model: Agent):
        self.workers: list[Agent] = []

        # 1. Planner # 문제를 쪼개 달성해야 할 구체적인 목표인 Goal로 나눔, 각 goal에 INtent를 설정
        self.system_prompt_planner = read_md(r"harness/system_prompts/planner.md")
        # prompt += characteristics

        # 2. Worker # 주어진 Intent를 수행.
        self.system_prompt_worker = read_md(r"harness/system_prompts/worker.md")

        # 2.1. Supervisor # 증거를 2차 검증 / primary goal이 충족되는지 확인.
        self.system_prompt_supervisor = read_md(r"harness/system_prompts/superivisor.md")

        # 2.2. Chunker # 문서를 쪼개서 chunk로 나눔. (chunker.md가 아직 없어 비활성)
        # self.system_prompt_chunker = read_md(r"harness/system_prompts/chunker.md")

        # 4. Improver # log를 분석하고 개선점을 찾아 개선. (미구현)
        # self.system_prompt_improver = read_md(r"harness/system_prompts/improver.md")

        self.model = model


    def Plan(self, task_report: str):
        # Set Planner agent

        self._reset_planner()
        # TODO : Planner set goals with `?` tool.
        response = self.execute_planner(task_report)

    def Work(self, intents: list[tuple[int, int, str]], related_goals: dict[int, str]): #
        # Intent work에 순서가 있다면, 알아서 IID(등록된 순서)대로 반환되므로 상관X

        # Set Worker Agent
        
        # TODO : resotre prev session - using exploration DB ID, intent ID
        # TODO : run worker - resume session or compacted session / return 
        
        # TODO: Intent [a, b, c]를 일괄할당하면, a를 하고 나서 goal이 만족되고, bc는 할 필요없는데 강제실행되는거 아님? 오히려 놓친 작업이 없을 숟 있기는 한데.. worker한테 선택권을 준다거나 하면 어떨까. 
        
        for gid, _iid, intent in intents:
            response = self._execute_worker(gid, related_goals.get(gid, ""), intent)

        
    def Supervise(self, intents: list[tuple[int, int, str]]): # intent 하나하나씩 신중하게 

        for _gid, _iid, intent in intents:
            response = self._execute_worker(None, "Supervise", intent)

        # TODO: task table의 상태를 바꾸고 그 이유를 반환.



    # ──────── Planner ────────
    def _reset_planner(self) -> Agent:
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
            self._reset_planner()

        prompt = "" + task_report
        response = self.planner(prompt)

        # TODO : logger
        return response

    # ──────── Worker ────────
    def _execute_worker(self, gid: int | None, goal: str, intent: str) -> Agent:
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

    # ──────── Supervisor ────────
    # Supervisor is a specialized worker that supervises the work of other workers.
    def _execute_supervisor(self, intent: str):
        supervisor = Agent(
            model = self.model,
            system_prompt = self.system_prompt_supervisor,
            tools = None # TODO : set tools
        )   

        # 일단 pause고 뭐고간에 일단 구현 안하고 바로 더함.
        # TODO : 전용 workdir이 필요할 수도.
        self.workers.append(supervisor)
        # TODO : logger


        prompt = "" + intent
        response = supervisor(prompt)

        self.workers.remove(supervisor)

        return response

    # ──────── Chunker ────────
    # Chunker is a specialized worker that chunks documents into smaller pieces.
    def _execute_chunker(self, docid: int):
        chunker = Agent(
            model = self.model,
            system_prompt = self.system_prompt_chunker,
            tools = None # TODO : set tools
        )   

        # 일단 pause고 뭐고간에 일단 구현 안하고 바로 더함.
        # TODO : 전용 workdir이 필요할 수도.
        self.workers.append(chunker)
        # TODO : logger


        prompt = "" + str(docid)
        response = chunker(prompt)

        self.workers.remove(chunker)

        return response

