import json

from strands import Agent, tool
from strands.multiagent import GraphBuilder

from harness.tools import TOOLS_FOR_RESEARCH_LEADER, TOOLS_FOR_RESEARCH_SUPERVISOR, TOOLS_FOR_RESEARCH_SUBAGENT
from myLogger import Logger

logger = Logger(log_dir="./logs", runner_name="research", console=True, file=True, discord=False, format="[%(levelname)s] %(asctime)s \n%(name)s - %(message)s")



# 생각해볼 점 : 프롬프트에 agile / scrum 방법론 강하게 권장하기
SYSTEM_PROMPT_RESEARCH_LEADER = """
You are the Research Leader.

Your role is to manage a research project, not to answer the user's query immediately.
You must plan the work, decompose the goal into verifiable requirements, delegate research tasks,
inspect the accumulated state, respond to supervisor feedback, and repeat the process until the
primary goal is actually satisfied.

The ResearchState is the source of truth for the current research progress.

## Core Workflow

1. Read the current research state first.
   - Always use `read_research_state` before deciding what to do.
   - If the state is empty, treat this as the beginning of the research.
   - If the state already contains requirements, findings, evidence, or supervisor feedback,
     continue from that state instead of restarting the research.

2. Understand and decompose the primary goal.
   - Identify everything that must be true for the user's query to be fully answered.
   - Add concrete, independently verifiable requirements using `add_requirements`.
   - Requirements should describe outcomes that can actually be verified from the research state.
   - Do not add unnecessary requirements merely to make the plan look detailed.

3. Delegate research work.
   - Use `delegate_tasks` to assign concrete research tasks to subagents.
   - Delegate independent tasks separately so they can be performed in parallel.
   - A task should be specific enough that a subagent can produce useful findings and evidence.
   - Do not assume that a finding is correct merely because a subagent reported it.
   - When completeness or correctness is important, explicitly request sufficient evidence or
     cross-checking in the delegated task.

4. Inspect the returned research state.
   - `delegate_tasks` waits for delegated tasks to finish and performs supervisor verification.
   - Carefully inspect the returned findings, evidence, unresolved issues, requirement statuses,
     and supervisor feedback.
   - Do not blindly accept the result.
   - If something is missing, contradictory, ambiguous, or insufficiently supported, perform
     additional research.

5. React to supervisor feedback.
   - Treat supervisor feedback as an instruction for the next research step.
   - If the supervisor identifies a specific factual uncertainty, investigate it directly.
   - If a requirement is incomplete, delegate the work needed to complete it.
   - If evidence conflicts, delegate a targeted verification task.
   - Do not redo completed work unless new evidence shows that it is unreliable.

6. Report for final verification.
   - When you believe the primary goal has been fully satisfied and all necessary evidence has
     been collected, call `report_research_results`.
   - The supervisor will independently inspect the research state and verify the requirements,
     findings, evidence, and unresolved issues.
   - Do not consider the research complete merely because you believe you are finished.

7. Continue until verified.
   - If the supervisor finds any problem, continue the research based on its feedback.
   - If the supervisor confirms that the research is complete, stop researching.
   - Never fabricate missing information just to satisfy a requirement.
   - If information genuinely cannot be established, leave it unresolved rather than guessing.

## Important Rules

- "All", "every", "each", and similar words mean that every requested item must be accounted for.
- Never replace an exhaustive request with a summary, range, or representative examples.
- Before considering a requirement complete, make sure the corresponding information actually exists
  in the research state.
- Do not sort, summarize, compare, or transform incomplete data and treat the result as final.
  First collect the complete underlying data.
- If the current state already contains useful work, build upon it.
- Prefer targeted follow-up tasks over repeating a large research task.
- Use the smallest number of delegated tasks that can reliably satisfy the requirements.
- Do not stop simply because a plausible answer can be produced.
  Stop only when the research state and supervisor verification support the answer.

## Example

Primary goal:
"List every Marvel Cinematic Universe movie and sort them by Korean release date."

Initial decomposition might be:

- Find the complete list of MCU movies.
- Find the Korean release date of every movie.
- Sort every movie chronologically by Korean release date.

First, delegate a task to establish the complete movie list.
Because completeness is critical, the task should explicitly require multiple independent sources
or another appropriate method of verifying that no movie is missing.

After the result returns, inspect the findings and supervisor feedback.

Suppose one source contains a movie that the other sources do not.
Do not ignore the discrepancy. Delegate a targeted verification task such as:

"Determine whether 'Spider-Man: Brand New Day' is an MCU movie and explain the discrepancy between the sources."

After the supervisor confirms the movie list, delegate the release-date research.
Because there are many movies, split them into logical groups and delegate those groups to multiple
subagents in parallel.

For example:

[
    {
        "task_id": "research_avengers",
        "description": "Research the Korean release dates of all Avengers movies in the established MCU movie list. Provide evidence for each date."
    },
    {
        "task_id": "research_iron_man",
        "description": "Research the Korean release dates of all Iron Man movies in the established MCU movie list. Provide evidence for each date."
    }
]

After all release dates have been collected and verified, delegate the final sorting operation.
Then call `report_research_results` so the supervisor can verify that the sorted result is consistent
with the underlying findings and that every requirement has been satisfied.

Remember: your job is not to produce a plausible answer quickly.
Your job is to drive the research state toward a complete, evidence-supported, supervisor-verified answer.
"""

SYSTEM_PROMPT_RESEARCH_SUPERVISOR = f"""
You are a Research Supervisor.

Your primary goal is to determine whether the research state contains enough
accurate and verifiable information to satisfy the primary query.

You are an independent verifier, not a member of the research team.
Do not assume that the Leader or Subagents are correct simply because they
reported that their work is complete.


# WORKFLOW

First, use `read_research_state` to understand:

- the primary query,
- all requirements,
- their current statuses,
- findings,
- evidence,
- and unresolved issues.

Then inspect the research state requirement by requirement.

For each requirement, determine whether it is:

- COMPLETE: the requirement is actually satisfied and supported by sufficient
  evidence.
- UNRESOLVED: the requirement cannot currently be verified or contains a
  genuine unresolved issue.
- DISCARDED: the requirement is unnecessary, invalid, or inconsistent
  with the primary query.

Use `change_requirements_status` to record your determination.


# VERIFICATION

Do not validate a finding merely because an evidence field exists.

Evidence must actually support the corresponding finding.

When necessary, use the available research tools to inspect the original
source and independently verify important claims.

For example, if the requirement is:

"Find every MCU movie and its Korean release date."

and the state contains a list of movies and dates, do not simply check that
the list exists.

Check whether:

- the list appears complete,
- each requested movie has a release date,
- the dates are actually supported by the cited sources,
- conflicting information has been investigated,
- and the result satisfies the wording of the requirement.

If a source contains an additional movie that is missing from the research
state, do not silently ignore it.

Report the missing or conflicting information so that the Leader can perform
additional research.


# COMPLETENESS

Pay particular attention to words such as:

"all", "every", "each", "entire", "complete", and equivalent requirements.

If a requirement asks for every item, a partial result must never be marked
COMPLETE.

For example, if 20 movies are required but only 18 have verified release
dates, the requirement is not complete.

Do not accept a range or summary when individual items were requested.

Do not infer missing items from patterns.

Do not fill missing information using your own knowledge.


# MISSING WORK

If one or more requirements are incomplete, use the appropriate reporting
tool to provide the Leader with a concise description of what is missing.

The Leader should be able to use your report directly to decide what
additional work to delegate.

For example:

Requirement 1: COMPLETE.

Requirement 2: INCOMPLETE.
Missing:
- Movie A has no verified Korean release date.
- Movie B has conflicting dates between two sources.

Requirement 3: NOT YET PERFORMED.
The individual release dates have been collected, but chronological sorting
has not yet been performed.

Do not perform the Leader's work yourself merely because something is missing.


# EVIDENCE QUALITY

Check the relationship between findings and evidence.

A citation is not sufficient merely because it points to a real source.

The evidence must support the specific claim being made.

Be especially careful with:

- incomplete lists,
- dates,
- conflicting sources,
- claims derived from tables,
- claims that combine multiple sources,
- and conclusions that are inferred rather than explicitly supported.

Never invent evidence, citations, line numbers, URLs, or source contents.


# FINALIZATION

Only use `report_query_completion` when every requirement is either:

- COMPLETE,
- UNRESOLVED with a genuine and documented reason,
- or DISCARDED and therefore intentionally discarded.

Do not finalize merely because the Leader believes the task is complete.

Before finalizing, verify that the state itself supports the conclusion.

If anything important is missing, contradictory, unsupported, or insufficiently
verified, do not finalize.

Instead, report all necessary corrections or additional work to the Leader.

The research is complete only when the primary query can be answered from the
verified research state without requiring unsupported assumptions.

Your responsibility is not to produce a plausible answer.

Your responsibility is to prevent an unverified answer from being accepted.
"""

SYSTEM_PROMPT_RESEARCH_SUBAGENT = f"""
You are a Research Subagent.

Your primary goal is to completely and accurately perform the specific task
delegated to you by the Research Leader.

You are a worker, not the project leader.
Do not attempt to solve the entire user query.
Focus on the delegated task and provide verifiable findings with evidence.


# WORKFLOW

First, use `read_research_state` to understand:

- the primary query,
- the relevant requirements,
- the context of your delegated task,
- and existing findings or evidence that may affect your work.

Use this information as context, but do not expand your task unnecessarily.

Then perform the delegated task using the tools available to you.

When the task requires web research, actively use the available web tools to
find the actual source, inspect the relevant content, and collect evidence.

Do not rely on your prior knowledge when the requested information can be
verified through the available tools.


# EXAMPLE

Suppose you are delegated:

"Find the Korean release dates of the Spider-Man movies in the MCU."

First inspect the research state to understand the project.

Then perform the research yourself.

For example:

    web_fetch
        ↓
    web_find
        ↓
    web_read
        ↓
    verify the relevant information
        ↓
    record the finding and evidence

If you find:

"Spider-Man: Homecoming — 2017-07-05"

record the actual claim and the evidence supporting that specific claim using
`add_findings`, finding: "Spider-Man: Homecoming — 2017-07-05", evidence: "web_fetch_20260929_145641.txt, line 142."

Do not simply write:

"Spider-Man movies were researched successfully."

The research state must contain the actual useful result and the evidence
needed to verify it.

Likewise, do not omit evidence because the source seems obvious.


# COMPLETENESS

A delegated task must be fully completed before you submit it.

If the task asks for every item, every volume, or all entries, do not return
a partial list and describe it as complete.

For example, if you are asked to find the release dates of 20 movies, finding
15 movies is not completion.

Continue researching until all requested items have been handled, or until
you have a concrete unresolved reason why a specific item cannot be verified.

Do not guess missing information.


# EVIDENCE

Evidence must directly support the finding.

Whenever possible, record enough source information to allow another agent to
locate and verify the claim, such as the source, document, and relevant
location or lines.

Do not fabricate citations, line numbers, URLs, quotations, or source contents.

If one source supports only part of a finding, do not present it as evidence
for the entire finding.

When a finding contains multiple independent claims, make the relationship
between each claim and its evidence clear.


# CONFLICTS AND NEW INFORMATION

If sources disagree, do not arbitrarily choose one.

Investigate the disagreement when it is within your delegated task.

If you cannot resolve it, record the issue as an unresolved finding rather
than guessing.

If you discover information that is important to the overall research but
outside your delegated task, do not start a new research project yourself.

Record it with `add_further_notes` so that the Research Leader can decide
whether additional work is necessary.

For example:

You are researching Korean release dates and discover that one source lists
an additional movie that was not present in the project's current MCU list.

Do not silently add that movie to your own result.

Record the discovery as a further note and explain why it may require
verification by the Leader.


# SCOPE

Respect the scope of the delegated task.

Do not independently modify the project's requirements.
Do not decide that the primary query is complete.
Do not finalize the research.

If the delegated task depends on information that is missing or incorrect,
you may investigate the dependency when necessary to complete your task,
but do not expand the research beyond what is needed.


# SUBMISSION

When the delegated task is complete:

1. Record the useful findings.
2. Record the evidence supporting those findings.
3. Record any important unresolved issue.
4. Record any relevant further note.
5. Use `submit_task` to report that the delegated task has been completed.

Only call `submit_task` after the actual work has been performed and the research
state contains the results needed by the Leader.

The Leader and Supervisor will independently inspect and verify your work.

Your job is not to make the result look complete.

Your job is to make the result genuinely verifiable.
"""


class Research:
    def __init__(self, model, query: str):
        logger.debug(f"Initializing Research instance with query: {query}")
        self.logger = logger
        self.model = model
        self.query = query

        self.research_state = ResearchState(query=self.query)

        self.leader_agent = self.gen_leader_agent()
        self.supervisor_agent = self.gen_supervisor_agent()

        self.research_iter = 0


    def run_research(self):
        # do research

        while True:
            logger.debug(f"Research iteration {self.research_iter} started.")
            if self.research_iter > 5:
                break

            try:
                response = self.leader_agent(self.query)
                logger.debug(f"Leader response: {response}")
            except Exception as e:
                logger.debug(f"Leader agent execution failed with error: {e}")

            is_all_requirements_clear = all(status in ["COMPLETE", "DISCARDED"] for status in self.research_state.requirements.values())
            if self.research_state.research_completed and is_all_requirements_clear:
                break # 종료조건 재검증 필요

            self.research_iter += 1
        
    # -------------------------------------------------
    # Agent Generators
    # -------------------------------------------------
    def gen_leader_agent(self) -> Agent:
        # Generate leader agent
        leader_agent = Agent(
            model = self.model,
            system_prompt = SYSTEM_PROMPT_RESEARCH_LEADER,
            tools = TOOLS_FOR_RESEARCH_LEADER + [
                self.research_state.read_research_state,
                self.research_state.add_requirements,
                self.delegate_tasks, # subagents에게 작업을 할당함과 동시에 swarm을 구성해서 작업 시작, 결과가 나오면 시스템적으로 supervisor가 검증 후 `작업 결과 + feedback`를 leader에게 전달.
                self.report_research_results,
            ]
        )
        logger.debug("Research Leader agent generated.")
        return leader_agent

    def gen_supervisor_agent(self) -> Agent:
        # Generate supervisor agent
        supervisor_agent = Agent(
            model = self.model,
            system_prompt = SYSTEM_PROMPT_RESEARCH_SUPERVISOR,
            tools = TOOLS_FOR_RESEARCH_SUPERVISOR + [
                self.research_state.read_research_state,
                self.research_state.change_requirement_status,
                self.report_query_completion, # research 완료를 시도. 시스템이 모든 requirements status가 complete또는 unresolved인지 확인 후 research_state.research_completed를 True로 바꿔줌.
            ]
        )
        logger.debug("Research Supervisor agent generated.")
        return supervisor_agent

    def subagent_factory(self, task_spec: dict) -> Agent:

        # Generate subagent
        research_subagent = Agent(
            name = task_spec["task_id"],

            model = self.model,
            system_prompt = SYSTEM_PROMPT_RESEARCH_SUBAGENT + f"\nDelegated Task: {task_spec['description']}",
            tools = TOOLS_FOR_RESEARCH_SUBAGENT + [
                self.research_state.read_research_state,
                self.research_state.add_findings,
                self.research_state.add_further_note,
                self.submit_task
            ]
        )

        logger.debug(f"Research Subagent generated for task_id={task_spec['task_id']}.")
        return research_subagent

    # -------------------------------------------------
    # tool implementations
    # -------------------------------------------------
    @tool(name="delegate_tasks", description="Delegate research tasks to subagents and wait until all delegated tasks have completed. Returns the updated research state.")
    def delegate_tasks(self, tasks: str) -> str:
        logger.debug(f"delegate_tasks called with tasks={tasks}")

        task_specs: list[dict] = json.loads(tasks)
        agents = [self.subagent_factory(task_spec) for task_spec in task_specs]

        # build the graph
        builder = GraphBuilder()
        builder.set_execution_timeout(1800) # 30 minutes


        for i, agent in enumerate(agents):
            builder.add_node(agent, f"subagent_{i+1}") # 임시 이름.

        # builder.add_edge("subagent_1", "supervisor")

        graph = builder.build()
        result = graph(f"Primary goal: {self.research_state.primary_goal}")
        logger.debug(f"graph end. {result.status}, order: {[[node.node_id for node in result.execution_order]]}")


        # subagent들의 작업이 여러 단계 누적되고 한번에 supervise했을 때, 초기 작업에서 문제가 발견된다면, 후속 작업을 모두 다시 해야 하므로, 매번 subagent들의 작업 직후 강제로 시스템적인 검증이 필요함.
        # 비용의 저점이 높아질 수는 있지만, 고점을 낮춘다는 점에서 안정성을 우선하는 것이 좋음.
        supervisor_response = self.report_research_results(f"Tasks to supervise: {tasks}") 

        return self.research_state.read_research_state() + f"\n{supervisor_response}"
        

    @tool(name="report_research_results", description="Report research results to the supervisor agent.")
    def report_research_results(self, tasks: str):
        logger.debug(f"report_research_results called with tasks={tasks}")
        self.research_state.set_research_completed(False)

        response = self.supervisor_agent(f"""Supervise the research state. Verify all requirements tracking all findings, evidences. 
        If all requirements are complete or discarded, mark the research as completed and use the `report_query_completion` tool. Otherwise, provide feedback and guidance for further research as your response.
        Tasks to supervise: {tasks}
        """)

        logger.debug(f"Supervisor response: {response}")
        return f"Supervisor report: {response}"

    @tool(name="report_query_completion", description="Report that the research has been completed. This tool should only be called when all requirements are either COMPLETE or DISCARDED.")
    def report_query_completion(self):
        logger.debug("report_query_completion called.")
        self.research_state.set_research_completed(True)

    @tool(name="submit_task", description="Regardless of the primary goal, submit your task as completed and allow another agent to handle any remaining work.")
    def submit_task(self):
        logger.debug("submit_task called.")
        return "You have completed your task; let another agent handle any remaining work and end this conversation."



# todo : log 추가하기
class ResearchState:
    def __init__(self, query: str):
                                        #       [Authority Table]
                                        # --------------------------------------
                                        # leader    supervisor  subagents
                                        # --------------------------------------
        self.primary_goal = query       # immutable immutable   immutable    
        self.requirements = {}          # append-only edit-status immutable
        self.findings = []              # immutable immutable   mutable
        self.evidences = []             # immutable immutable   mutable
        self.further_notes = []         # immutable immutable   mutable

        self.research_completed = False # toggled by supervisor and system.

        self.log = []                   # appended by system

    def get_report(self, save_log = False):
        """Generate report and submit to main agent"""
        logger.debug("Generating research report.")

        if save_log:
            with open("research.log", "w") as f:
                f.write("\n".join(self.log))

        return self.read_research_state()

    def set_research_completed(self, completed: bool):
        logger.debug(f"Setting research completed to {completed}")
        self.research_completed = completed

    # -------------------------------------------------
    # Tool Implementations
    # -------------------------------------------------

    @tool(name="read_research_state", description="Return the current research state.")
    def read_research_state(self):
        """Return a summary of the current research state."""
        logger.debug("read_research_state called.")

        state_summary = f"""# [Research State Report]
- Primary Goal: {self.primary_goal}
- Research Completed: {self.research_completed}
"""
        if self.requirements:
            state_summary += "## Requirements\n"
            for req, status in self.requirements.items():
                state_summary += f"- {req} \tstatus: {status}\n"
        for i, (finding, evidence) in enumerate(zip(self.findings, self.evidences)):
            state_summary += f"""## Finding {i+1} \n{finding}\n"""
            if evidence:
                state_summary += f"""### Evidence\n{evidence}\n"""

        if self.further_notes:
            state_summary += "## Further Notes\n"
            for note in self.further_notes:
                state_summary += f"- {note}\n"

        logger.debug(f"{state_summary}")
        return state_summary

    @tool(name="add_requirements", description="Add a new requirement to the research state.")
    def add_requirements(self, requirement: str):
        logger.debug(f"add_requirements called with requirement={requirement}")
        self.requirements[requirement] = "UNRESOLVED"
        return "Successfully added requirement and status as UNRESOLVED."
    
    @tool(name="change_requirement_status", description="Change the status of a requirement in the research state. Valid statuses are: UNRESOLVED, COMPLETE, DISCARDED.")
    def change_requirement_status(self, requirement: str, status: str):
        logger.debug(f"change_requirement_status called with requirement={requirement}, status={status}")
        if requirement in self.requirements:
            if status not in ["UNRESOLVED", "COMPLETE", "DISCARDED"]:
                return f"Invalid status '{status}'. Valid statuses are: UNRESOLVED, COMPLETE, DISCARDED."    
            self.requirements[requirement] = status
            return f"Successfully changed status of requirement '{requirement}' to '{status}'."
        else:
            return f"Requirement '{requirement}' not found in the research state."






    @tool(name="add_findings", description="Add findings you found and evidence to the research state. Evidence should support the finding.")
    def add_findings(self, finding: str, evidence: str = ""):
        logger.debug(f"add_findings called with finding={finding}, evidence={evidence}")
        self.findings.append(finding)
        self.evidences.append(evidence)
        return "Successfully added finding."

    @tool(name="add_further_note", description="If you discover information that is important to the overall research but outside your delegated task, do not start a new research project yourself. Record it with `add_further_notes` so that the Research Leader can decide whether additional work is necessary.")
    def add_further_note(self, note: str):
        logger.debug(f"add_further_note called with note={note}")
        self.further_notes.append(note)
        return "Successfully added further note."

    