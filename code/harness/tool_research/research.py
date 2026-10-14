


# built-in
from dataclasses import dataclass
from enum import Enum, auto
from datetime import datetime

# 3rd party


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




@dataclass
class Research:
    #==== Metadata ====

    ID: int
    # isPaused : bool ?
    status: ResearchStatus = ResearchStatus.PENDING

    created_at: datetime
    elapsed_sec: float = 0.0

    primary_goal: str


    #==== Agents ====
    agents = ResearchAgents
    #==== DB ====
    db = ResearchDB
    #==== Logs ====


    #==== methods ====
    def Run(self):
    # planner lifecycle???
        # llm.set(TID)???
        self.agents.Plan() # heartbeat?

        # 반복문
        # TODO : 하나의 intent를 받아옴
        self.agents.Execute()
        

    def Pause(self):
        pass

    def Resume(self):
        pass



    

