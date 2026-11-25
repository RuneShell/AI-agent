"""[db.py: Research DB]
An abstracted DB interface class for research agent.
controls a PostgreSQL db running in a docker container.
""" 

# 1. built-in
import os
from abc import ABC, abstractmethod
from unittest import result # Abstract Base Class


# 3. third-party
import psycopg



# TODO: print, raise Error 모두 logger로 묶기


class ResearchDB:
    """연결·쿼리 실행·테이블 목록만 책임진다."""
    def __init__(self, config: dict, options: dict = {}):
        """params
            - config: how to connect to PostgreSQL
            - options: how to configure ResearchDB
        """

        self.options = options
        """options = {
            "CHECK_SOURCE_DOUBLE": False        # if True, supervisor agent DOUBLE CHECKS the `finding` table with `evidence` table and related documents.
        }
        """

        try:
            self.conn = psycopg.connect(**config, autocommit=True) # 연결을 오래 유지하므로, 실패한 트랜잭션이 이후 쿼리를 막지 않도록.
        except psycopg.OperationalError:
            raise ConnectionError(f"port {config['port']} is closed. Docker container may be down.")
        self.tables: set[str] = set()
        self.refresh_tables()

    def execute_query(self, query, params=None, num_result: int = -1):
        with self.conn.cursor() as cur:
            cur.execute(query, params)

            if cur.description:
                return cur.fetchmany(num_result) if num_result > 0 else cur.fetchall()
            else:  # INSERT, UPDATE, DELETE 쿼리인 경우
                self.conn.commit()
                return []




    def get_table_names(self):
        records = self.execute_query("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_type = 'BASE TABLE'
            ORDER BY table_name;""")

        return [row[0] for row in records]

    def preview_table_records(self, table_name: str, count: int = 10) -> dict:
        if table_name not in self.tables:
            raise ValueError(f"Unknown table: {table_name}")

        with self.conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM %s", (table_name,))
            row = total_count = cur.fetchone()
            total_count = row[0] if row is not None else 0

            cur.execute(f"SELECT * FROM %s LIMIT %s", (table_name, count,))
            records = cur.fetchall()

        return {"total_count": total_count, "records": records}



    # Warning : use this carefully.
    def drop(self, type: str, name: str):
        with self.conn.cursor() as cur:
            if type == "table":
                cur.execute(f"DROP TABLE IF EXISTS %s CASCADE", (name,))
            elif type == "enum":
                cur.execute(f"DROP TYPE IF EXISTS %s CASCADE", (name,))
            else:
                raise ValueError("Invalid type. Use 'table' or 'enum'.")

    def refresh_tables(self):
        rows = self.execute_query("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'""")
        self.tables = {r[0] for r in rows}


        


    def close(self):
        self.conn.close()




class BaseTable(ABC):
    """Abstract Base Class for all tables"""
    name: str
    enums: dict[str, tuple[str, ...]] = {} # {"task_status": ("IDLE", ...)} # 중복 허용 X

    def __init__(self, db: "ResearchDB"):
        self.db = db            # DB를 reference로 받음.

    @property
    @abstractmethod
    def ddl(self) -> str:
        """CREATE TABLE 문"""

    # ── Template Method: 모든 테이블이 동일한 절차를 공유 ──
    def init_table(self):
        if self.name in self.db.tables:
            return
        for enum_name, values in self.enums.items():
            self._create_enum(enum_name, values)
        self.db.execute_query(self.ddl)
        self.db.tables.add(self.name)

    def _create_enum(self, enum_name: str, values: tuple[str, ...]):
        # DDL에는 파라미터 바인딩이 안 되므로 내부 상수만 사용 (외부 입력 금지)
        labels = ", ".join(f"'{v}'" for v in values)
        self.db.execute_query(f"""
            DO $$ BEGIN
                CREATE TYPE {enum_name} AS ENUM ({labels});
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$;""")

    def _check_table_exists(self) -> bool:
        if self.name not in self.db.tables:
            return False
        return True












# ======================== Tables ========================

# ──────────────── 1. Document Tables ────────────────
class DocumentTable(BaseTable):
    """Document table stores a list of documents handled by agents."""
    name = "document"

    @property
    def ddl(self) -> str:
        return f"""
            CREATE TABLE document (
                DOCID SERIAL PRIMARY KEY,
                DIR TEXT NOT NULL,
                NAME TEXT NOT NULL
            );"""

    def insert_document(self, dir: str, name: str):
        # to consistent ABS path
        dir = os.path.normpath(os.path.abspath(dir))

        if not os.path.isfile(os.path.join(dir, name)):
            raise FileNotFoundError(f"File not found: {os.path.join(dir, name)}")

        result = self.db.execute_query(
            "INSERT INTO document (DIR, NAME) VALUES (%s, %s) RETURNING DOCID;",
            (dir, name)
        )
        return result[0][0]
    
    def delete_document(self, name: str):
        self.db.execute_query(
            "DELETE FROM document WHERE NAME = %s;",
            (name,)
        )
        print("Document deleted from database: " + name)


class TreeOfContentTable(BaseTable):
    """`TOC(Tree of Content)` stores the hierarchical structure of a document, allowing for efficient retrieval and management of its sections and subsections."""
    name = "toc"

    MIN_LEAF_CONTENT_LENGTH   = 10
    MAX_LEAF_CONTENT_LENGTH   = 500
    MAX_LEAF_LOC_LENGTH       = 50000   # TODO : 확인 필요
    MIN_PARENT_CONTENT_LENGTH = 50
    MAX_PARENT_CONTENT_LENGTH = 200
    MAX_PARENT_LOC_LENGTH     = 100000  # TODO : 확인 필요

    @property
    def ddl(self) -> str:
        return f"""
            CREATE TABLE toc (
                DOCID       INT NOT NULL REFERENCES document(DOCID) ON DELETE CASCADE,
                TOC_NODEID  INT NOT NULL,
                CONTENT     TEXT NOT NULL,
                ISLEAF      BOOLEAN NOT NULL,
                START_LOC   INT NOT NULL,
                END_LOC     INT NOT NULL,
                PARENT_ID   INT,

                PRIMARY KEY (DOCID, TOC_NODEID),

                FOREIGN KEY (DOCID, PARENT_ID) REFERENCES toc(DOCID, TOC_NODEID)
            );"""


    # def __init__(self):
    #     self.last_modified_line = 0 # 1-based, inclusive-range chunking. 0 means NOT modified yet.

    # ──────── ToC build loop ────────
    def get_next_line(self, docid: int) -> int:
        result = self.db.execute_query("""
            SELECT COALESCE(MAX(END_LOC), 0) + 1
            FROM toc
            WHERE DOCID = %s AND ISLEAF;
            """, (docid,)
        )
        return result[0][0]

    def get_orphans(self, docid: int, start: int, end: int) -> list[tuple[int, str, int, int]]:  # [(toc_nodeid, content, start, end)] overlapping L{start}~L{end}
        # 모든 노드는 어떤 orphan의 범위 안에 있으므로, orphan만 검사해도 겹침을 찾을 수 있다.
        # before Merge, all leaves are orphans.
        return self.db.execute_query("""
            SELECT TOC_NODEID, CONTENT, START_LOC, END_LOC
            FROM toc
            WHERE DOCID = %s AND PARENT_ID IS NULL
                AND START_LOC <= %s
                AND END_LOC >= %s
            ORDER BY START_LOC ASC;
            """, (docid, end, start)
        )

    def get_children(self, docid: int, toc_nodeid: int) -> list[tuple[int, str, int, int]]:  # [(toc_nodeid, content, start, end)] in line order
        return self.db.execute_query("""
            SELECT TOC_NODEID, CONTENT, START_LOC, END_LOC
            FROM toc
            WHERE DOCID = %s AND PARENT_ID = %s
            ORDER BY START_LOC ASC;
            """, (docid, toc_nodeid)
        )

    # ──────── agent tool ────────
    # node.doc_line_range = [START_LOC, END_LOC] (node[i].end + 1 == node[i+1].start)
    def insert_node(self, docid: int, content: str, start: int, end: int) -> int:
        """Creates a leaf on an uncovered range, or a parent over 2+ contiguous orphans."""
        # TODO: 문서 안에 자체 목차가 있을 때에는?
        self._validate_range(start, end)

        # 1. 범위에 걸린 orphan이 자식 후보. 없으면 leaf.
        children = self.get_orphans(docid, start, end)
        is_leaf = not children

        # 2. 자식은 범위를 빈틈없이, 정확히 덮어야 한다.
        expected = start
        for child_id, _content, child_start, child_end in children:
            if child_start < start or child_end > end:
                raise ValueError(f"L{start}~L{end} partially overlaps N{child_id} (L{child_start}~L{child_end}).")
            if child_start != expected:
                raise ValueError(f"L{expected}~L{child_start - 1} inside L{start}~L{end} is not covered by any node.")
            expected = child_end + 1
        if children and expected != end + 1:
            raise ValueError(f"L{expected}~L{end} inside L{start}~L{end} is not covered by any node.")
        if len(children) == 1:
            raise ValueError(f"L{start}~L{end} duplicates N{children[0][0]}. A parent needs at least 2 children.")

        self._validate_limits(content, start, end, is_leaf)

        # 3. 노드 생성과 자식 연결은 함께 성공해야 한다.
        # !!! RETURNING이 없으면 execute_query가 commit()을 호출해 transaction 안에서 오류가 난다.
        with self.db.conn.transaction():
            result = self.db.execute_query("""
                SELECT COALESCE(MAX(TOC_NODEID) + 1, 0)
                FROM toc
                WHERE DOCID = %s;
                """, (docid,)
            )
            toc_nodeid = result[0][0]

            self.db.execute_query("""
                INSERT INTO toc (DOCID, TOC_NODEID, CONTENT, ISLEAF, START_LOC, END_LOC, PARENT_ID)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING TOC_NODEID;
                """, (docid, toc_nodeid, content, is_leaf, start, end, None)
            )

            if children:
                self.db.execute_query("""
                    UPDATE toc
                    SET PARENT_ID = %s
                    WHERE DOCID = %s AND TOC_NODEID = ANY(%s)
                    RETURNING TOC_NODEID;
                    """, (toc_nodeid, docid, [child[0] for child in children]) # psycopg3는 `IN %s`에 tuple 바인딩 불가.
                )
                
        return toc_nodeid # return required.

    def update_node(self, docid: int, toc_nodeid: int, *,
                    content: str | None = None, end: int | None = None) -> dict[int, tuple[int, int]]:
        """Updates content or end of a leaf. If end moves, the next leaf's start follows. Returns {toc_nodeid: (start, end)} of changed nodes."""
        if content is None and end is None:
            raise ValueError(f"No field to update for N{toc_nodeid}.")

        # 1. old record를 받아옴.
        rows = self.db.execute_query("""
            SELECT CONTENT, ISLEAF, START_LOC, END_LOC, PARENT_ID
            FROM toc
            WHERE DOCID = %s AND TOC_NODEID = %s;
            """, (docid, toc_nodeid)
        )
        if not rows:
            raise ValueError(f"Node not found: N{toc_nodeid} in DOCID {docid}.")

        old_content, is_leaf, start, old_end, parent_id = rows[0]
        if not is_leaf:
            raise ValueError(f"N{toc_nodeid} is a parent. Only leaf nodes can be updated.")

        # 2. 전달된 값만 반영한다.
        new_content = old_content if content is None else content
        new_end     = old_end     if end     is None else end

        self._validate_range(start, new_end)
        self._validate_limits(new_content, start, new_end, is_leaf=True)
        changed = {toc_nodeid: (start, new_end)}

        # 3. end를 옮기면 다음 leaf의 start가 따라간다. (node[i].end + 1 == node[i+1].start 유지)
        next_id = None
        if new_end != old_end:
            if parent_id is not None:
                raise ValueError(f"N{toc_nodeid} belongs to N{parent_id}. Its range L{start}~L{old_end} cannot move.")

            rows = self.db.execute_query("""
                SELECT TOC_NODEID, CONTENT, END_LOC, PARENT_ID
                FROM toc
                WHERE DOCID = %s AND ISLEAF AND START_LOC = %s;
                """, (docid, old_end + 1)
            )
            if rows:
                next_id, next_content, next_end, next_parent_id = rows[0]
                if next_parent_id is not None:
                    raise ValueError(f"N{next_id} belongs to N{next_parent_id}. Its start L{old_end + 1} cannot move.")
                if new_end + 1 > next_end:
                    raise ValueError(f"End L{new_end} empties N{next_id} (L{old_end + 1}~L{next_end}).")
                self._validate_limits(next_content, new_end + 1, next_end, is_leaf=True)
                changed[next_id] = (new_end + 1, next_end)
            elif new_end > old_end:
                for other_id, _content, other_start, other_end in self.get_orphans(docid, old_end + 1, new_end):
                    raise ValueError(f"L{start}~L{new_end} overlaps N{other_id} (L{other_start}~L{other_end}).")

        # 4. 두 노드의 수정은 함께 성공해야 한다.
        # !!! RETURNING이 없으면 execute_query가 commit()을 호출해 transaction 안에서 오류가 난다.
        with self.db.conn.transaction():
            self.db.execute_query("""
                UPDATE toc
                SET CONTENT = %s, END_LOC = %s
                WHERE DOCID = %s AND TOC_NODEID = %s
                RETURNING TOC_NODEID;
                """, (new_content, new_end, docid, toc_nodeid)
            )
            if next_id is not None:
                self.db.execute_query("""
                    UPDATE toc
                    SET START_LOC = %s
                    WHERE DOCID = %s AND TOC_NODEID = %s
                    RETURNING TOC_NODEID;
                    """, (new_end + 1, docid, next_id)
                )
        return changed

    # ──────── Sub Methods: validate nodes ────────
    def _validate_range(self, start: int, end: int):
        if not 1 <= start <= end:
            raise ValueError(f"Invalid range: L{start}~L{end}. Must be 1 <= start <= end.")

    def _validate_limits(self, content: str, start: int, end: int, is_leaf: bool):
        kind = "Leaf" if is_leaf else "Parent"
        min_length = self.MIN_LEAF_CONTENT_LENGTH if is_leaf else self.MIN_PARENT_CONTENT_LENGTH
        max_length = self.MAX_LEAF_CONTENT_LENGTH if is_leaf else self.MAX_PARENT_CONTENT_LENGTH
        max_lines  = self.MAX_LEAF_LOC_LENGTH     if is_leaf else self.MAX_PARENT_LOC_LENGTH

        if not min_length <= len(content) <= max_length:
            raise ValueError(f"{kind} content length is {len(content)}. Must be in [{min_length}, {max_length}].")
        if end - start + 1 > max_lines:
            raise ValueError(f"{kind} L{start}~L{end} spans {end - start + 1} lines. Max is {max_lines}.")

    # TODO : chunking agent의 실수를 대비헤 불연속 탐지/수정 기능도 제공해야 할지도.


    def clear_toc(self):
        self.db.execute_query("DELETE FROM toc;")
        self.db.execute_query("ALTER SEQUENCE toc_toc_nodeid_seq RESTART WITH 0;")
        print("TOC table cleared and TOC_NODEID sequence reset.")



class AnnotationTable(BaseTable):
    """Annotation table stores annotations generated by agents for leaf nodes."""
    name = "annotation"

    @property
    def ddl(self) -> str:
        return f"""
            CREATE TABLE annotation (
                DOCID       INT NOT NULL,
                TOC_NODEID  INT NOT NULL,
                ANNOTID     INT NOT NULL,
                ANNOTATION  TEXT NOT NULL,

                PRIMARY KEY (DOCID, TOC_NODEID, ANNOTID),

                FOREIGN KEY (DOCID, TOC_NODEID) REFERENCES toc(DOCID, TOC_NODEID) ON DELETE CASCADE
            );"""

    def insert_annotation(self, docid: int, toc_nodeid: int, annotation: str):
        # 해당 DOCID와 TOC_NODEID의 다음 ANNOTID를 계산
        result = self.db.execute_query("""
            SELECT COALESCE(MAX(ANNOTID) + 1, 0)
            FROM annotation
            WHERE DOCID = %s AND TOC_NODEID = %s;
            """, (docid, toc_nodeid)
        )
        annotid = result[0][0]

        self.db.execute_query(
            "INSERT INTO annotation (DOCID, TOC_NODEID, ANNOTID, ANNOTATION) VALUES (%s, %s, %s, %s);",
            (docid, toc_nodeid, annotid, annotation)
        )

# ──────────────── 2. Progress Tables ────────────────

class TaskTable(BaseTable):
    """Task is a unit of research project. One Task can have multiple Goals."""
    name = "task"
    enums = {"task_status": ("PENDING", "RUNNING", 
                             "DONE", "FAILED", "TIMEOUT", 
                             "DISCARDED")}

    @property
    def ddl(self) -> str:
        return f"""
            CREATE TABLE task (
                TID             SERIAL PRIMARY KEY,
                PRIMARY_GOAL    TEXT NOT NULL,
                STATUS          task_status NOT NULL DEFAULT 'PENDING'
            );"""

    def insert_task(self, primary_goal: str) -> int:
        result = self.db.execute_query(f"""
            INSERT INTO task(PRIMARY_GOAL)
            VALUES (%s)
            RETURNING TID;
        """, (primary_goal,))  

        return result[0][0] # return new task's ID (TID)

    def delete_task(self, tid: int):
        self.db.execute_query(
            "DELETE FROM task WHERE TID = %s;",
            (tid,)
        )
        print("Task deleted from database: " + str(tid))

    # ── research level ──

    def set_task_status(self, tid: int, status: str):
        if status not in self.enums["task_status"]:
            raise ValueError(f"Invalid status: {status}. Must be one of {self.enums['task_status']}.")
        self.db.execute_query(
            "UPDATE task SET STATUS = %s WHERE TID = %s;",
            (status, tid)
        )
    def get_task_status(self, tid: int) -> str:
        result = self.db.execute_query(
            "SELECT STATUS FROM task WHERE TID = %s;",
            (tid,)
        )
        if not result:
            raise ValueError(f"No task found with TID: {tid}")
        return result[0][0]
    def get_task_report(self, tid: int) -> str:
        # TODO: 지금은 primary goal만 반환. goal/intent/finding 요약 추가.
        result = self.db.execute_query(
            "SELECT PRIMARY_GOAL FROM task WHERE TID = %s;",
            (tid,)
        )
        if not result:
            raise ValueError(f"No task found with TID: {tid}")
        return result[0][0]

    # ── main-agent level ──

    def extend_task(self, tid:int, new_primary_goal: str):
        self.db.execute_query(
            "UPDATE task SET PRIMARY_GOAL = %s WHERE TID = %s;",
            (new_primary_goal, tid)
        )


class GoalTable(BaseTable):
    """Goal is a specific objective to be achieved within a Task."""
    """Goal은 Intent를 만들기 위한 과정에 불과함. 모든 Intent가 완료되면 goal은 자동으로 완료됨. 검증은 primary goal과 한 번에 비교."""
    name = "goal"
    enums = {"goal_status": ("OPEN", "MET", "ABANDONED")}

    @property
    def ddl(self) -> str:
        return f"""
            CREATE TABLE goal (
                TID             INT REFERENCES task(TID) ON DELETE CASCADE,
                GID             INT NOT NULL,
                GOAL            TEXT NOT NULL,
                STATUS          goal_status  NOT NULL DEFAULT 'OPEN',

                PRIMARY KEY (TID, GID)
            );"""

    # TODO : tid를 시스템이 넣을 순 없나?
    def insert_goal(self, tid: int, goal: str):
        # 해당 TID의 다음 GID를 계산
        result = self.db.execute_query("""
            SELECT COALESCE(MAX(GID) + 1, 0)
            FROM goal
            WHERE TID = %s;
            """, (tid,)
        )
        gid = result[0][0]

        self.db.execute_query(
            "INSERT INTO goal (TID, GID, GOAL) VALUES (%s, %s, %s);",
            (tid, gid, goal)
        )

    def get_goals(self, tid: int, gids: list[int] | None = None) -> list[tuple[int, str, str]]:
        if gids is None: # get all goals for the task.
            result = self.db.execute_query(
                "SELECT GID, GOAL, STATUS FROM goal WHERE TID = %s;",
                (tid,)
            )
        else:
            result = self.db.execute_query(
                "SELECT GID, GOAL, STATUS FROM goal WHERE TID = %s AND GID = ANY(%s);",
                (tid, list(gids)) # psycopg3는 `IN %s`에 tuple 바인딩 불가.
            )
        return result


class IntentTable(BaseTable):
    """Intent is an explicit and specific unit of work to achieve a Goal."""
    # TODO: 실행 후 삭제하게 하려면 IID로 지우고, 작업 record를 만들고 싶으면 enum으로 상태 관리하면 될 듯.
    name = "intent"
    enums = {"intent_status": ("OPEN", "EXECUTING", "DONE", "FAILED")}

    @property
    def ddl(self) -> str:
        # GID는 Null일 수 있다. 이는 특수 Intent로, 자동으로 worker에 할당하지 않는다. 
        #   예를들어 supervise Intent는 primary goal이 달성되었는지 검증하며 try_report() 호출 시에만 특수 worker에 할당한다.
        # IID는 SERIAL(task 전체에서 같은 Intent가 중복되지 않게 하자는 취지로 Task별로 생성.)
        return f"""
            CREATE TABLE intent (
                TID             INT REFERENCES task(TID) ON DELETE CASCADE,
                GID             INT,
                IID             SERIAL PRIMARY KEY,
                INTENT          TEXT NOT NULL,
                STATUS          intent_status  NOT NULL DEFAULT 'OPEN',

                FOREIGN KEY (TID, GID) REFERENCES goal(TID, GID) ON DELETE CASCADE
            );"""

    def insert_intent(self, tid: int, gid: int|None, intent: str):
        self.db.execute_query(
            "INSERT INTO intent (TID, GID, INTENT) VALUES (%s, %s, %s);",
            (tid, gid, intent)
        )

    def get_open_intents(self, tid: int) -> list[tuple[int, int, str]]:
        """먼저 등록한 Intent를 먼저 수행하도록 IID 오름차순 정렬 후 반환."""
        result = self.db.execute_query(
            """
            SELECT GID, IID, INTENT
            FROM intent
            WHERE TID = %s AND STATUS = 'OPEN'
            ORDER BY IID ASC;
            """,
            (tid,)
        )
        return result

# ──────────────── 3. Research Tables ────────────────

class FindingTable(BaseTable):
    """Finding is a piece of information or insight discovered during the research process supporting a Goal."""
    name = "finding"
    enums = {"finding_status": ("OPEN", "CONFIRMED", "DISMISSED")}

    @property
    def ddl(self) -> str:
        # DOUBLE_CHECK_SOURCE=True면 OPEN으로 두고 supervise를 받아야 하고, =False면 자동으로 CONFIRMED로 설정.
        default_status = r'OPEN' if self.db.options.get("CHECK_SOURCE_DOUBLE", False) else r'CONFIRMED'
        return f"""
            CREATE TABLE finding (
                TID             INT REFERENCES task(TID) ON DELETE CASCADE,
                GID             INT,
                FINDINGID       INT NOT NULL,
                FINDING         TEXT NOT NULL,
                ISDIRECT        BOOLEAN NOT NULL,
                STATUS          finding_status  NOT NULL DEFAULT '{default_status}',

                PRIMARY KEY (TID, GID, FINDINGID),

                FOREIGN KEY (TID, GID) REFERENCES goal(TID, GID) ON DELETE CASCADE
            );"""
    
    def insert_finding(self, tid: int, gid: int, finding: str, is_direct: bool):
        # 해당 TID만 이용해 다음 FINDINGID를 계산 (Task별 Finding은 독립적이므로 GID는 고려하지 않음)
        result = self.db.execute_query("""
            SELECT COALESCE(MAX(FINDINGID) + 1, 0)
            FROM finding
            WHERE TID = %s;
            """, (tid,)
        )
        findingid = result[0][0]

        self.db.execute_query(
            "INSERT INTO finding (TID, GID, FINDINGID, FINDING, ISDIRECT) VALUES (%s, %s, %s, %s, %s);",
            (tid, gid, findingid, finding, is_direct)
        )

    def get_findings(self, tid: int, gid: int | None = None) -> list[tuple[int, str, bool, str]]:
        if gid is None:
            result = self.db.execute_query(
                "SELECT FINDINGID, FINDING, ISDIRECT, STATUS FROM finding WHERE TID = %s;",
                (tid,)
            )
        else:
            result = self.db.execute_query(
                "SELECT FINDINGID, FINDING, ISDIRECT, STATUS FROM finding WHERE TID = %s AND GID = %s;",
                (tid, gid)
            )
        return result
    # TODO: 나중에 위 함수랑 합치던가.
    def get_open_findings(self, tid: int) -> list[tuple[int, str, bool]]:
        result = self.db.execute_query(
            "SELECT FINDINGID, FINDING, ISDIRECT FROM finding WHERE TID = %s AND STATUS = 'OPEN';",
            (tid,)
        )

        return result

class EvidenceTable(BaseTable):
    """Evidence is a piece of information or data that connects findings and leaf node of ToC."""
    name = "evidence"

    @property
    def ddl(self) -> str:
        return f"""
            CREATE TABLE evidence (
                TID             INT REFERENCES task(TID) ON DELETE CASCADE,
                GID             INT,
                EVIDENCEID      INT NOT NULL,
                FINDINGID       INT,
                DOCID           INT,
                TOC_NODEID      INT,
                LOCATION        TEXT NOT NULL,

                PRIMARY KEY (TID, GID, EVIDENCEID, FINDINGID),

                FOREIGN KEY (TID, GID, FINDINGID)  REFERENCES finding(TID, GID, FINDINGID) ON DELETE CASCADE,
                FOREIGN KEY (DOCID, TOC_NODEID)    REFERENCES toc(DOCID, TOC_NODEID)       ON DELETE CASCADE
            );"""

    def insert_evidence(self, tid: int, gid: int, findingid: int, docid: int, toc_nodeid: int, location: str):
        # 해당 TID만 이용해 다음 EVIDENCEID를 계산 (Task별 Evidence는 독립적이므로 GID와 FINDINGID는 고려하지 않음)
        result = self.db.execute_query("""
            SELECT COALESCE(MAX(EVIDENCEID) + 1, 0)
            FROM evidence
            WHERE TID = %s;
            """, (tid,)
        )
        evidenceid = result[0][0]

        self.db.execute_query(
            "INSERT INTO evidence (TID, GID, EVIDENCEID, FINDINGID, DOCID, TOC_NODEID, LOCATION) VALUES (%s, %s, %s, %s, %s, %s, %s);",
            (tid, gid, evidenceid, findingid, docid, toc_nodeid, location)
        )

    def get_evidences(self, tid: int, findingid: int) -> list[tuple[int, int, int, int, int, str]]:
        result = self.db.execute_query(
            "SELECT GID, EVIDENCEID, DOCID, TOC_NODEID, LOCATION FROM evidence WHERE TID = %s AND FINDINGID = %s;",
            (tid, findingid)
        )
        return result
