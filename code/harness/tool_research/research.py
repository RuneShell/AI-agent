# built-in
# from dataclasses import dataclass
from enum import Enum, auto
from datetime import datetime

# 3rd party
from strands import Agent

# custom
from harness.tool_research.agents import ResearchAgents
from harness.tool_research.db import ResearchDB

from envWrap import read_md


class ResearchStatus(Enum):
    PENDING = auto()
    RUNNING = auto()

    DONE = auto()
    FAILED = auto()
    TIMEOUT = auto()
    
    DISCARDED = auto()




class Research:
    def __init__(self, primary_goal: str, model: Agent):
        self.primary_goal = primary_goal
        
        self.agents = ResearchAgents()
        #==== DB ====
        self.db = ResearchDB()

        #==== Agent Handler ====
        self.model = model
        agents = ResearchAgents(model = model)

        #==== Metadata ====
        self.TID = self.db.insert_task(primary_goal)
        self.status = ResearchStatus.PENDING

        self.created_at = datetime.now()
        elapsed_sec: float = 0.0

        self.primary_goal: str

        #==== Logs ====



    #==== methods ====
    def Run(self):
    # planner lifecycle???
        # llm.set(TID)???

        # TID -> GIDs.
        self.agents.Plan(self.db.get_task_report()) # heartbeat?

        # GIDs -> intents
        intents: list[str] = self.db.get_intents(self.TID)
        for intent in intents:
            self.agents.Execute(intent)


    def Pause(self):
        # 이전 기억을 저장했다 불러오려면, Worker에게조차 session을 써야 하나?
        pass

    def Resume(self):
        pass



    

