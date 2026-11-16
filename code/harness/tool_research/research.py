# built-in
# from dataclasses import dataclass
from enum import Enum, auto
from datetime import datetime

# 3rd party
from strands import Agent

# custom
from harness.tool_research.agents import ResearchAgents
from harness.tool_research.db import ResearchDB, BaseTable

from envWrap import read_md


class ResearchStatus(Enum):
    PENDING = auto()    # 대기중
    RUNNING = auto()    # 진행중..

    DONE = auto()       # 완료.
    FAILED = auto()     # 불가능하다고 판단(근거가 있어야 함), 사용자의 개입 필요
    TIMEOUT = auto()    # 지정된 시간을 초과
    
    DISCARDED = auto()  # 폐기했으나 아직 지우진 않음



# Research 객체는 하나의 main agent 세션에 종속되며, 각각이 고유한 TID로 구분된다.
class Research: 
    def __init__(self, primary_goal: str, model: Agent, db_config: dict, db_options: dict):
        self.primary_goal = primary_goal
        
        self.agents = ResearchAgents()
        #==== DB ====
        # TODO: db를 research마다 생성하는 건 비효율?
        self.db = ResearchDB(db_config, db_options) # init db
        for table_cls in BaseTable.__subclasses__(): # Set tables
            name = table_cls.__name__.lower()
            setattr(self, name, table_cls(self.db))


        #==== Agent Handler ====
        self.model = model
        agents = ResearchAgents(model = model)

        #==== Metadata ====
        self.TID = self.tasktable.insert_task(primary_goal)
        self.db.set_task_status(self.TID, ResearchStatus.PENDING.name)
        self.status = ResearchStatus.PENDING

        # TODO: meta들 연결
        self.created_at = datetime.now()
        elapsed_sec: float = 0.0

        self.primary_goal: str

        #==== Logs ====


    # TID로 r:Research 를 고유하게 검색.
    @classmethod
    def find_by_id(cls, Researches: list["Research"], TID: int):
        return next((r for r in Researches if r.TID == TID), None)


    #==== methods ====
    def Run(self):
    # planner lifecycle???
        # llm.set(TID)???

        # Plan()과 Work()의 무한 루프. 만약 planner가 report를 제대로 작성하면 loop break
        
        self.db.set_task_status(self.TID, ResearchStatus.RUNNING.name)

        while True:
            status = self.db.get_task_status(self.TID)
            if status != ResearchStatus.RUNNING.name:
                break

            # Task -> Goals, Goals -> Intents
            self.agents.Plan(self.db.get_task_report()) # heartbeat?

            open_intents = self.db.get_open_intents(self.TID)
            self.agents.Execute(open_intents)


    def try_report(self):
        # supervisor를 worker로 포함시켜도 되나?
        """checklist
        if
            all(Intent.status = NOT "OPEN") # system checks them.
            and
            all(Finding supported by their Evidences)  # supervisor checks them.
            and
            sum(Finding) supports Primary Goal. # supervisor checks them.
        then
            write a report
            return report
        """

        # 1. Check: Intent 
        open_intents = self.db.get_open_intents(self.TID)
        if open_intents:
            return "에러1"

        # 2. Findings ↔ Evidences # TODO: 너무 지나치게 agent를 의심하는 거 아닌가? 그래도 필요할 떄가 있을 수 있지.
        open_findings = self.db.get_findings(self.TID)
        open_findings = {finding_id: (finding, is_direct) for finding_id, finding, is_direct in open_findings}
        evidences =     {finding_id: self.db.get_evidences(self.TID, finding_id) for finding_id in open_findings.keys()}

        for open_finding_id, (finding, is_direct) in open_findings.items(): # 
            intent = "" # TODO: 작성.
            self.db.insert_intent(self, self.TID, None, "supervise...prompt ...?") # GID=None, supervise intent # finding-wise.

        # 3. Findings ↔ Primary Goal
        findings = self.db.get_findings(self.TID)
        self.db.insert_intent(self, self.TID, None, "supervise...prompt ...?") # GID=None, supervise intent


        # call Supervisor
        open_intents = self.db.get_open_intents(self.TID)
        self.agents.Supervise(open_intents)

        # ═══ ⏸ agent 대기 · ▶ 결과 이어받기 ═══

        # write new report if all checks passed
        if self.db.get_task_status == ResearchStatus.DONE.name:
            # TODO: write report
            report = ""


        # save and return
        # TODO: logger에 별도파일저장 interface도 만들까?
        with open(f"report_{self.TID}.md", "a", encoding="utf-8") as f: # 기존 report가 있다면 추가.
            f.write(report)
        return report

    

    def extend_research(self, tid: int, followup_goal: str):
        # TODO: 이전 goal, intent를 요약해야 하나?
        # Document DB: 수정 불필요 (동일 문서를 이어 작업할 수 있음)
        # Progress DB: 굳이 필요한가?
        # Research DB: 이전 task에서 했던 report로 대체. indirect finding은 다시 도움이 될 지도. TODO: report를 누적할 것인가?

        self.db.extend_task(tid, followup_goal)
        # TODO: 이전 report를 planner가 갖도록.
        self.Run()



    def Pause(self, tid: int):
        # 이전 기억을 저장했다 불러오려면, Worker에게조차 session을 써야 하나?
        pass

    def Resume(self, tid: int):
        pass



    

