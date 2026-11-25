# 1. built-in
import os
from enum import Enum, auto
from typing import Callable

# 2. third-party
from strands import tool

# 3. custom
from ..module import ToolModule
from .agents import ResearchAgents, SegmentAgent
from .db import (ResearchDB,
                 DocumentTable, TreeOfContentTable, AnnotationTable,
                 TaskTable, GoalTable, IntentTable,
                 FindingTable, EvidenceTable)

from .chunker import Chunker

from ...configs import REPORT_MAX_BYTES
from ...log_poller import LogPoller


class ResearchStatus(Enum):
    PENDING = auto()    # 대기중
    RUNNING = auto()    # 진행중..

    DONE = auto()       # 완료.
    FAILED = auto()     # 불가능하다고 판단(근거가 있어야 함), 사용자의 개입 필요
    TIMEOUT = auto()    # 지정된 시간을 초과

    DISCARDED = auto()  # 폐기했으나 아직 지우진 않음



class ResearchModule(ToolModule):
    """tool_research를 main agent 옆에 붙이는 ToolModule. (규격: harness/module.py)
        - Research DB와 자기 LogPoller의 수명을 소유한다.
        - Task별 상태는 DB에 있으므로, 흐름 메서드는 TID만 받는다.
    """
    name = "Tool: Research"

    def __init__(self, model, db_config: dict, db_options: dict = {}, poller: LogPoller|None = None):
        self.model = model
        self.external_tools = {}

        self.db_config = db_config
        self.db_options = {}
        self.db: ResearchDB|None = None # None이면 정지 상태.

        self.poller = poller
    def inject_external_tools(self, tools: dict[str, Callable]) -> None:
        self.external_tools = tools


    # ──────── life cycle ────────
    def start(self):
        if self.poller:
            self.poller.register(self.name, self.health)
            self.poller.start()

        # ──── init DB ────
        try:
            self.db = ResearchDB(self.db_config, self.db_options)

            self.document   = DocumentTable(self.db)
            self.toc        = TreeOfContentTable(self.db)
            self.annotation = AnnotationTable(self.db)
            self.task       = TaskTable(self.db)
            self.goal       = GoalTable(self.db)
            self.intent     = IntentTable(self.db)
            self.finding    = FindingTable(self.db)
            self.evidence   = EvidenceTable(self.db)

            # DO NOT change order, Foreign Key will be broken.
            for table in [self.document, self.toc, self.annotation,
                          self.task, self.goal, self.intent,
                          self.finding, self.evidence]:
                table.init_table()

        except Exception:
            self.stop() # ModuleHost는 실패한 모듈을 되돌리지 않으므로 여기서 정리.
            raise
    def stop(self):
        # ──── close DB ────
        try:
            if self.db:
                self.db.close()
        finally:
            self.db = None
            if self.poller:
                self.poller.unregister(self.name)
                self.poller.stop()

    # ──────── main agent tools ────────
    def tools(self) -> dict[str, Callable]:
        return {
            "research"       : self._create_research(),
            "extend_research": self._create_extend_research(),
            "toc_document" : self._create_toc_document(),
        }

    def _create_research(self):
        @tool(name="research", description="""
        Order agent leader to research a topic and returns a summary of the findings.
        Only thing you need to do is to offer a concrete, detailed and clear research query... and just wait for the result.
        """)
        def research(primary_goal: str) -> str:
            tid = self.task.insert_task(primary_goal)
            self._Run(tid)
            return self._try_report(tid) # TODO: supervisor가 call하는 거 아니었나?

        return research

    def _create_extend_research(self):
        @tool(name="extend_research", description="")
        def extend_research(TID: int, new_goal: str) -> str:
            self._extend_research(TID, new_goal)
            return self._try_report(TID) # TODO.

        return extend_research

    def _create_toc_document(self):
        @tool(name="toc_document", description="")
        def toc_document(filepath: str) -> str:
            # TODO: 파일 경로 확인 - DB에 등록 - 자동 chunking loop 시작 - return chunk report
            if not(os.path.exists(filepath) and os.path.isfile(filepath)):
                return f"File not exists: {filepath}"

            # Insert doc info to DocumentTable
            chunker = Chunker.from_file(filepath)  # before insert_document: normalize may change filepath
            dir, filename = os.path.split(chunker.filepath)
            docid = self.document.insert_document(dir, filename)

            # ───── Build ToC report ────
            toc_report = self._build_toc(docid, chunker)
            return toc_report

                
        return toc_document

    # ──────── sub-agent tools ────────
    role_tools = {
        "planner":  [], # get db summary
        "worker": [],  # web tools, db_
        "supervisor": [], 
    }

    # ──────── research flow ────────
    def _Run(self, tid: int): # TODO: 사람이 수동으로 RUN을 break할 수 있어야.
    # planner lifecycle???
        # llm.set(TID)???

        # Plan()과 Work()의 무한 루프. 만약 planner가 report를 제대로 작성하면 loop break

        agents = ResearchAgents(model = self.model)
        self.task.set_task_status(tid, ResearchStatus.RUNNING.name)

        # ──── loop ────
        while True:
            status = self.task.get_task_status(tid)
            if status != ResearchStatus.RUNNING.name:
                break

            # ──── Plan ────
            # Task -> Goals, Goals -> Intents
            agents.Plan(self.task.get_task_report(tid)) # heartbeat?

            open_intents = self.intent.get_open_intents(tid)

            # Offer worker agent Intent with related goal if exists.
            gids = [gid for gid, _, _ in open_intents if gid is not None] # gid가 없으면 제외.
            related_goals = self.goal.get_goals(tid, gids = gids)
            related_goals = {gid: goal for gid, goal, _status in related_goals}

            # ──── Execute ────
            agents.Work(open_intents, related_goals)


    def _build_toc(self, docid: int, chunker: Chunker) -> str:
        """
        content 
            -(Chunker: system)-> content chunks
            -(Segmenter: agent)-> Table of Contents (Segment chunk and make leaf nodes)
            -(Segmenter: agent)-> Table of Contents (Realign node borders that cut off by chunking)
            -(Segmenter: agent)-> Table of Contents (Merge leafs to parent nodes—making wider toc)
            -(Toc Build: system)-> ToC report
        """
        # 1. Chunker → 2. Segmenter
        segmenter  = SegmentAgent(self.model, self.toc, docid)
        boundaries = segmenter.Segment(chunker)

        # 3. Realign
        segmenter.Realign(chunker, boundaries)

        # 4. Merge
        segmenter.Merge()

        # 5. build report
        root_id, root_content, _start, last_line = self.toc.get_orphans(docid, 1, chunker.line_count)[0]  # after Merge, root is the only orphan
        root_children = self.toc.get_children(docid, root_id)

        # 5.1. pick levels by BFS, until REPORT_MAX_BYTES
        records = {}  # {toc_nodeid: (indented record, children)}. nodes shown in report
        level, depth, used_bytes = root_children, 0, 0
        while level:
            level_records = {}
            for toc_nodeid, content, start, end in level:
                children = self.toc.get_children(docid, toc_nodeid)
                level_records[toc_nodeid] = ("  " * depth + f"N{toc_nodeid} L{start}~L{end} ({len(children)} children): {content}", children)
            used_bytes += sum(len(record.encode("utf-8")) + 1 for record, _ in level_records.values())  # +1: "\n"
            if records and used_bytes > REPORT_MAX_BYTES:
                break  # 1st level is always shown
            records.update(level_records)
            level = [child for _, children in level_records.values() for child in children]
            depth += 1

        # 5.2. write in DFS order
        lines = [f"[Document] DOCID {docid}, {chunker.filepath} (L1~L{last_line})",
                 f"[Title] {root_content}",
                 ""]
        stack = list(reversed(root_children))
        while stack:
            toc_nodeid = stack.pop()[0]
            if toc_nodeid in records:
                record, children = records[toc_nodeid]
                lines.append(record)
                stack += reversed(children)

        toc_report = "\n".join(lines)
        return toc_report
            


    # ──────── report ? ────────
    def _try_report(self, tid: int):
        # supervisor를 worker로 포함시켜도 되나?
        """checklist
        if      all(Intent.status = NOT "OPEN") # system checks them.
            and all(Finding supported by their Evidences)  # supervisor checks them.
            and sum(Finding) supports Primary Goal. # supervisor checks them.
        then    write a report
                return report
        """

        # 1. Check: Intent
        open_intents = self.intent.get_open_intents(tid)
        if open_intents:
            return "에러1"

        # 2. Findings ↔ Evidences # TODO: 너무 지나치게 agent를 의심하는 거 아닌가? 그래도 필요할 떄가 있을 수 있지.
        open_findings = self.finding.get_open_findings(tid)
        open_findings = {finding_id: (finding, is_direct) for finding_id, finding, is_direct in open_findings}
        evidences =     {finding_id: self.evidence.get_evidences(tid, finding_id) for finding_id in open_findings.keys()}

        for open_finding_id, (finding, is_direct) in open_findings.items(): #
            intent = "" # TODO: 작성.
            self.intent.insert_intent(tid, None, "supervise...prompt ...?") # GID=None, supervise intent # finding-wise.

        # 3. Findings ↔ Primary Goal
        findings = self.finding.get_findings(tid)
        self.intent.insert_intent(tid, None, "supervise...prompt ...?") # GID=None, supervise intent


        # call Supervisor
        open_intents = self.intent.get_open_intents(tid)
        agents = ResearchAgents(model = self.model)
        agents.Supervise(open_intents)

        # ═══ ⏸ agent 대기 · ▶ 결과 이어받기 ═══

        # write new report if all checks passed
        report = ""
        if self.task.get_task_status(tid) == ResearchStatus.DONE.name:
            # TODO: write report
            report = ""


        # save and return
        # TODO: logger에 별도파일저장 interface도 만들까?
        with open(f"report_{tid}.md", "a", encoding="utf-8") as f: # 기존 report가 있다면 추가.
            f.write(report)
        return report



    def _extend_research(self, tid: int, followup_goal: str):
        # TODO: 이전 goal, intent를 요약해야 하나?
        # Document DB: 수정 불필요 (동일 문서를 이어 작업할 수 있음)
        # Progress DB: 굳이 필요한가?
        # Research DB: 이전 task에서 했던 report로 대체. indirect finding은 다시 도움이 될 지도. TODO: report를 누적할 것인가?

        self.task.extend_task(tid, followup_goal)
        # TODO: 이전 report를 planner가 갖도록.
        self._Run(tid)

    def _discard_research(self, tid: int):
        # temporary research는 일단 DISCARDED로 표시하고, 나중에 DB에서 삭제.
        self.task.set_task_status(tid, ResearchStatus.DISCARDED.name)


    def Pause(self, tid: int):
        # 이전 기억을 저장했다 불러오려면, Worker에게조차 session을 써야 하나?
        pass

    def Resume(self, tid: int):
        pass


    # ──────── dashboard ────────
    def health(self) -> list[dict]:
        return [] # TODO:
