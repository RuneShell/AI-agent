
# built-in
import re

# 3rd party
from strands import Agent, tool, ToolContext
from strands.tools.executors import SequentialToolExecutor
from strands.types.exceptions import MaxTokensReachedException

# custom
from ..tools import get_tools
from .chunker import Chunker
from .db import TreeOfContentTable

from ...configs import CHUNK_MAX_BYTES
from ...envWrap import read_md



class ResearchAgents:
    planner: Agent|None = None

    def __init__(self, model):
        self.workers: list[Agent] = []

        # 1. Planner # 문제를 쪼개 달성해야 할 구체적인 목표인 Goal로 나눔, 각 goal에 INtent를 설정
        self.system_prompt_planner = read_md(r"harness/system_prompts/planner.md")
        # prompt += characteristics

        # 2. Worker # 주어진 Intent를 수행.
        self.system_prompt_worker = read_md(r"harness/system_prompts/worker.md")

        # 2.1. Supervisor # 증거를 2차 검증 / primary goal이 충족되는지 확인.
        self.system_prompt_supervisor = read_md(r"harness/system_prompts/superivisor.md")

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
    def _reset_planner(self):
        if self.planner:
            self.planner.shutdown()
            self.planner = None

        prompt = self.system_prompt_planner
        self.planner = Agent(
            model = self.model,
            system_prompt = prompt,
            tools = get_tools("research_planner")
        )
        return self.planner
        # TODO : logger
    def execute_planner(self, task_report: str):
        # Planner can be reused in condition.
        planner = self._reset_planner()

        prompt = "" + task_report
        response = planner(prompt)

        # TODO : logger
        return response

    # ──────── Worker ────────
    def _execute_worker(self, gid: int | None, goal: str, intent: str) -> str:
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

        return str(response)

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


class SegmentAgent:
    MAX_TURNS          = 16   # to stop agent from calling tools endlessly
    MAX_FAILURE_LENGTH = 300  # bytes. chunk already fills context.
    MAX_STALL_COUNT    = 3    # consecutive Segment attempts without progress
    REALIGN_TAIL_BYTES = CHUNK_MAX_BYTES // 2 * 1//4  # a: end of left leaf
    REALIGN_HEAD_BYTES = CHUNK_MAX_BYTES // 2 * 3//4  # b: start of right leaf. a < b

    def __init__(self, model, toc: TreeOfContentTable, docid: int):
        self.model = model
        self.toc = toc
        self.docid = docid

        self.chunk: Chunker.Chunk                  # lines the agent can see. filled by Segment(), Realign()
        self.failure: str = ""                     # last recoverable error -> prepended on retry
        self.fatal_error: Exception | None = None  # unrecoverable error in tool -> raised by Segment(), Realign()
        self.level_nodes: list[tuple[int, str, int, int]] = []  # orphans of the height being merged. filled by Merge()
        self.latest_merged_end: int = 0                         # end of latest merged node in this height. 0: none yet

        self.system_prompt = read_md(r"harness/system_prompts/segmenter.md")
        sections = dict(re.findall(r"^# (\w+)\n(.*?)(?=^# |\Z)", self.system_prompt, flags=re.M | re.S))  # {"Common": ..., "Segment": ...}
        self.system_prompt_segmenter = sections["Common"] + sections["Segment"]
        self.system_prompt_realigner = sections["Common"] + sections["Realign"]
        self.system_prompt_merger    = sections["Common"] + sections["Merge"]
        self.insert_node = self._create_insert_node()
        self.update_node = self._create_update_node()
        self.merge_nodes = self._create_merge_nodes()

    # ──────── ToC build loop ────────
    def Segment(self, chunker: Chunker) -> list[int]:
        boundaries: list[int] = []  # chunk boundary lines. passed to Realign()
        cursor, stall_count = 1, 0
        while cursor <= chunker.line_count:
            chunk = self.chunk = chunker.take_chunk(cursor)
            self.fatal_error = None

            # build prompt
            previous = "(none)"
            last_leaf = self.toc.get_orphans(self.docid, cursor - 1, cursor - 1)
            if last_leaf:
                toc_nodeid, content, start, end = last_leaf[0]
                previous = f"N{toc_nodeid} L{start}~L{end}: {content}"
            prompt = ((f"[Previous attempt failed] {self.failure}\n" if self.failure else "") + # prepend failure of previous attempt
                    f"[Previous leaf] {previous}\n"
                    f"---\n"
                    f"[Position] L{chunk.start_line}~L{chunk.end_line} ({'end of document' if chunk.is_last else 'more lines follow'})\n\n"
                    f"[Chunk]\n{chunk.text}")
            self.failure = ""

            # generate Agent
            segmenter = Agent(
                model = self.model,
                system_prompt = self.system_prompt_segmenter,
                tools = [self.insert_node, self.update_node],
                tool_executor = SequentialToolExecutor(),  # parallel execution mixes line order
            )

            # run Agent
            try:
                segmenter(prompt, limits={"turns": self.MAX_TURNS})
            except MaxTokensReachedException: # token이 Segment()의 절반이라 터질 일이 없는데?
                self.failure = "Output was too long."

            if self.fatal_error:
                raise self.fatal_error

            # check progress
            next_cursor = self.toc.get_next_line(self.docid)
            if next_cursor > cursor:
                self.failure, stall_count = "", 0
                if next_cursor <= chunker.line_count:
                    boundaries.append(next_cursor)
            else:
                self.failure = self.failure or "Nothing was registered."
                stall_count += 1
                if stall_count >= self.MAX_STALL_COUNT:
                    raise RuntimeError(f"Segmenter made no progress at L{cursor} {stall_count} times in a row: {self.failure}")
            cursor = next_cursor

        return boundaries

    def Realign(self, chunker: Chunker, boundaries: list[int]):
        for boundary in boundaries:
            leaves = self.toc.get_orphans(self.docid, boundary - 1, boundary) # get chunk[i-1], chunk[i]
            if len(leaves) != 2:
                continue  # a later Segment extended a leaf over this boundary
            (left_id, left_content, left_start, left_end), (right_id, right_content, right_start, right_end) = leaves

            # build prompt
            tail = chunker.take_chunk(left_end,    max_bytes=self.REALIGN_TAIL_BYTES, backward=True)
            head = chunker.take_chunk(right_start, max_bytes=self.REALIGN_HEAD_BYTES)
            self.chunk = Chunker.Chunk(start_line=tail.start_line, end_line=head.end_line, is_last=head.is_last, text="")  # range check of update_node
            self.fatal_error = None
            prompt = (f"[Left leaf] N{left_id} L{left_start}~L{left_end}: {left_content}\n"
                      f"{tail.text}\n"
                      f"---\n"
                      f"[Right leaf] N{right_id} L{right_start}~L{right_end}: {right_content}\n"
                      f"{head.text}")

            # generate Agent
            realigner = Agent(
                model = self.model,
                system_prompt = self.system_prompt_realigner,
                tools = [self.update_node],
                tool_executor = SequentialToolExecutor(),
            )

            # run Agent
            try:
                realigner(prompt, limits={"turns": self.MAX_TURNS})
            except MaxTokensReachedException:
                pass  # original boundary is still valid

            if self.fatal_error:
                raise self.fatal_error

    def Merge(self):
        last_line = self.toc.get_next_line(self.docid) - 1
        stall_count = 0
        while True:  # 1 loop = 1 height
            self.level_nodes = self.toc.get_orphans(self.docid, 1, last_line)
            if len(self.level_nodes) <= 1:
                return  # root에 도달
            self.latest_merged_end = 0

            while self.latest_merged_end < last_line:  # 1 loop = 1 window. ends when the whole height is merged
                # current height에 있는 node들을 정해진 format으로 agent에게 전달. (fill window up to CHUNK_MAX_BYTES)
                records, used_bytes = [], 0
                for toc_nodeid, content, start, end in self.level_nodes:
                    if start <= self.latest_merged_end:
                        continue
                    record = f"N{toc_nodeid} L{start}~L{end}: {content}"
                    used_bytes += len(record.encode("utf-8")) + 1  # +1: "\n"
                    if records and used_bytes > CHUNK_MAX_BYTES:
                        break
                    records.append(record)
                    window_end = end
                window_start = self.latest_merged_end + 1
                self.chunk = Chunker.Chunk(start_line=window_start, end_line=window_end, is_last=window_end == last_line, text="")  # range check of merge_nodes
                self.fatal_error = None

                # build prompt
                # 만약 context를 초과한다면 **보류**방식으로 남기도록 할 것. (is_last가 아니면 마지막 묶음은 보류. system prompt의 규칙)
                position = "end of this level" if self.chunk.is_last else "more nodes follow"
                prompt = ((f"[Previous attempt failed] {self.failure}\n" if self.failure else "") +
                          f"[Position] L{window_start}~L{window_end} ({position})\n\n"
                          f"[Nodes]\n" + "\n".join(records))
                self.failure = ""

                # generate Agent
                merger = Agent(
                    model = self.model,
                    system_prompt = self.system_prompt_merger,
                    tools = [self.merge_nodes],
                    tool_executor = SequentialToolExecutor(),  # parallel execution mixes line order
                )

                # run Agent. agent는 tool을 호출해서 parent node를 만들어 table에 집어넣음.
                previous_end = self.latest_merged_end
                try:
                    merger(prompt, limits={"turns": self.MAX_TURNS})
                except MaxTokensReachedException:
                    self.failure = "Output was too long."

                if self.fatal_error:
                    raise self.fatal_error

                # check progress. merge_nodes updates latest_merged_end
                if self.latest_merged_end > previous_end:
                    self.failure, stall_count = "", 0
                else:
                    self.failure = self.failure or "Nothing was merged."
                    stall_count += 1
                    if stall_count >= self.MAX_STALL_COUNT:
                        raise RuntimeError(f"Merger made no progress at L{window_start} {stall_count} times in a row: {self.failure}")

    # ──────── agent tool ────────
    def _create_insert_node(self):
        @tool(name="insert_node", context=True,
              description="Register the next segment. `start` must be the line right after the previous segment.")
        def insert_node(content: str, start: int, end: int, tool_context: ToolContext) -> str:
            try:
                next_line = self.toc.get_next_line(self.docid)
                if start != next_line:        return self._reject(f"`start` must be L{next_line}, got L{start}.")  # captcha: check agent knows where it is
                if end > self.chunk.end_line: return self._reject(f"`end` must be <= L{self.chunk.end_line}, got L{end}.")

                toc_nodeid = self.toc.insert_node(self.docid, content, start, end)
            except ValueError as e: return self._reject(str(e))
            except Exception as e:  return self._stop(tool_context, e)

            return f"N{toc_nodeid} saved: L{start}~L{end}."

        return insert_node

    def _create_update_node(self):
        @tool(name="update_node", context=True,
              description="Fix the content of a registered segment, or move its end. The next segment's start follows the new end.")
        def update_node(toc_nodeid: int, end: int | None = None, content: str | None = None, *,
                        tool_context: ToolContext) -> str:
            first_end = self.chunk.start_line - 1  # boundary must stay inside lines the agent can see
            try:
                if end is not None and not first_end <= end <= self.chunk.end_line:
                    return self._reject(f"`end` must be in L{first_end}~L{self.chunk.end_line}, got L{end}.")

                changed = self.toc.update_node(self.docid, toc_nodeid, content=content, end=end)
            except ValueError as e: return self._reject(str(e))
            except Exception as e:  return self._stop(tool_context, e)

            ranges = ", ".join(f"N{node_id}: L{node_start}~L{node_end}" for node_id, (node_start, node_end) in changed.items())
            neighbors = [node_id for node_id in changed if node_id != toc_nodeid]
            return f"{ranges}. Check if N{neighbors[0]}'s content still fits." if neighbors else f"{ranges}."

        return update_node

    def _create_merge_nodes(self):
        @tool(name="merge_nodes", context=True,
              description="Group the nodes in L`start`~L`end` under a new parent. `start` must be the line right after the previous group.")
        def merge_nodes(content: str, start: int, end: int, tool_context: ToolContext) -> str:
            level_ends = [node_end for _id, _content, _start, node_end in self.level_nodes]
            try:
                if start != self.latest_merged_end + 1: return self._reject(f"`start` must be L{self.latest_merged_end + 1}, got L{start}.")  # captcha: check agent knows where it is
                if end > self.chunk.end_line:           return self._reject(f"`end` must be <= L{self.chunk.end_line}, got L{end}.")
                if end not in level_ends:               return self._reject(f"No node of this level ends at L{end}.")  # also keeps start, end on the same height

                # a single node left at the end cannot have a parent. include it silently.
                rest = [node_end for node_end in level_ends if node_end > end]
                if len(rest) == 1:
                    end = rest[0]

                toc_nodeid = self.toc.insert_node(self.docid, content, start, end)
            except ValueError as e: return self._reject(str(e))
            except Exception as e:  return self._stop(tool_context, e)

            self.latest_merged_end = end
            return f"N{toc_nodeid} saved: L{start}~L{end}."

        return merge_nodes

    # ──────── Sub Methods ────────
    def _reject(self, message: str) -> str:
        self.failure = message.encode("utf-8")[:self.MAX_FAILURE_LENGTH].decode("utf-8", errors="ignore")
        return message

    def _stop(self, tool_context: ToolContext, error: Exception) -> str:
        self.fatal_error = error
        tool_context.invocation_state["request_state"]["stop_event_loop"] = True  # to stop wasting turns. Segment() raises it.
        return f"Stopped by system error: {type(error).__name__}"
