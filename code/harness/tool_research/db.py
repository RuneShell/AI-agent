# 1. built-in
import os
from abc import ABC, abstractmethod # Abstract Base Class


# 3. third-party
import psycopg



# TODO: print, raise Error 모두 logger로 묶기


class ResearchDB:
    """연결·쿼리 실행·테이블 목록만 책임진다."""
    def __init__(self, config: dict, options: dict = {}):
        self.options = options
        """options = {
            "CHECK_SOURCE_DOUBLE": False        # if True, supervisor agent DOUBLE CHECKS the `finding` table with `evidence` table and related documents.
        }
        """

        try:
            self.conn = psycopg.connect(**config)
        except psycopg.OperationalError:
            raise ConnectionError(f"port {config['port']} is closed. Docker container may be down.")
        self.tables: set[str] = set()
        self.refresh_tables()

    def execute_query(self, query, params=None, num_result: int = -1):
        with self.conn.cursor() as cur:
            cur.execute(query, params)
            if cur.description:
                return cur.fetchmany(num_result) if num_result > 0 else cur.fetchall()
            self.conn.commit()
            return None

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
    enums: dict[str, tuple[str, ...]] = {} # {"task_status": ("IDLE", ...)}

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

        self.db.execute_query(
            "INSERT INTO document (DIR, NAME) VALUES (%s, %s);",
            (dir, name)
        )

    def delete_document(self, name: str):
        self.db.execute_query(
            "DELETE FROM document WHERE NAME = %s;",
            (name,)
        )
        print("Document deleted from database: " + name)


class TreeOfContentTable(BaseTable):
    """`TOC(Tree of Content)` stores the hierarchical structure of a document, allowing for efficient retrieval and management of its sections and subsections."""
    name = "toc"

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

    # TODO: docid를 시스템이 넣을 순 없나?
    def insert_leaf(self, docid: int, content: str, start: int, end: int):
        # TODO: 문서 안에 자체 목차가 있을 때에는?
        MIN_CONTENT_LENGTH = 100
        MAX_CONTENT_LENGTH = 500
        MAX_LOC_LENGTH = 5000 # TODO : 확인 필요

        if len(content) < MIN_CONTENT_LENGTH or len(content) > MAX_CONTENT_LENGTH:
            raise ValueError("Content length is out of bounds")
        if end - start > MAX_LOC_LENGTH:
            raise ValueError("Location length is out of bounds")

        # 해당 DOCID의 다음 TOC_NODEID를 계산
        result = self.db.execute_query("""
            SELECT COALESCE(MAX(TOC_NODEID) + 1, 0)
            FROM toc
            WHERE DOCID = %s;
            """, (docid,)
        )
        toc_nodeid = result[0][0]

        self.db.execute_query(
            "INSERT INTO toc (DOCID, TOC_NODEID, CONTENT, ISLEAF, START_LOC, END_LOC, PARENT_ID) VALUES (%s, %s, %s, %s, %s, %s, %s);",
            (docid, toc_nodeid, content, True, start, end, None)
        )

    def merge_leaves(self, docid: int, content: str, start: int, end: int):
        MIN_CONTENT_LENGTH = 50
        MAX_CONTENT_LENGTH = 200
        MAX_LOC_LENGTH = 100000 # TODO : 확인 필요

        if len(content) < MIN_CONTENT_LENGTH or len(content) > MAX_CONTENT_LENGTH:
            raise ValueError("Content length is out of bounds")
        if end - start > MAX_LOC_LENGTH:
            raise ValueError("Location length is out of bounds")


        # 부모가 없는 leaf 중 해당 범위에 속하는 후보 조회
        candidates = self.db.execute_query("""
            SELECT TOC_NODEID, START_LOC, END_LOC
            FROM toc
            WHERE DOCID = %s
                AND PARENT_ID IS NULL
                AND START_LOC >= %s
                AND END_LOC <= %s
            ORDER BY START_LOC ASC;
            """, (docid, start, end)
        )
        if not candidates:
            raise ValueError("No leaf candidates found")

        # 범위의 시작과 끝이 정확히 일치하는지 검증
        if candidates[0][1] != start:
            raise ValueError("No leaf starts at the specified start location")
        elif candidates[-1][2] != end:
            raise ValueError("No leaf ends at the specified end location")
        # 후보들이 서로 연속적으로 연결되는지 검증
        for i in range(len(candidates) - 1):
            if candidates[i][2] != candidates[i + 1][1]:
                raise ValueError("Leaf locations are not contiguous")

        # 해당 DOCID의 다음 TOC_NODEID를 계산
        result = self.db.execute_query("""
            SELECT COALESCE(MAX(TOC_NODEID) + 1, 0)
            FROM toc
            WHERE DOCID = %s;
            """, (docid,)
        )
        toc_nodeid = result[0][0]

        # 부모 생성
        self.db.execute_query("""
            INSERT INTO toc (DOCID, TOC_NODEID, CONTENT, ISLEAF, START_LOC, END_LOC, PARENT_ID) VALUES (%s, %s, %s, %s, %s, %s, %s);
            """, (docid, toc_nodeid, content, False, start, end, None)
        )

        # 생성된 부모 ID를 후보 leaf들의 PARENT_ID를 업데이트
        self.db.execute_query("""
            UPDATE toc
            SET PARENT_ID = %s
            WHERE DOCID = %s AND TOC_NODEID IN (%s);
            """, (toc_nodeid, docid, tuple(row[0] for row in candidates))
        )

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
                DOCID       INT NOT NULL REFERENCES document(DOCID) ON DELETE CASCADE,
                TOC_NODEID  INT NOT NULL REFERENCES toc(TOC_NODEID) ON DELETE CASCADE,
                ANNOTID     INT NOT NULL,
                ANNOTATION  TEXT NOT NULL,

                PRIMARY KEY (DOCID, TOC_NODEID, ANNOTID)
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
    enums = {"task_status": ("IDLE", "RUNNING", "PAUSED", "DONE")}

    @property
    def ddl(self) -> str:
        return f"""
            CREATE TABLE task (
                TID             SERIAL PRIMARY KEY,
                PRIMARY_GOAL    TEXT NOT NULL,
                STATUS          task_status NOT NULL DEFAULT 'IDLE'
            );"""

    def insert_task(self, primary_goal: str) -> int | None:
        records = self.db.execute_query(f"""
            INSERT INTO task(PRIMARY_GOAL)
            VALUES (%s)
            RETURNING TID;
        """, (primary_goal,))  

        return records[0][0] # return new task's ID (TID)

    def delete_task(self, tid: int):
        self.db.execute_query(
            "DELETE FROM task WHERE TID = %s;",
            (tid,)
        )
        print("Task deleted from database: " + str(tid))


class GoalTable(BaseTable):
    """Goal is a specific objective to be achieved within a Task."""
    name = "goal"
    enums = {"goal_status": ("OPEN", "MET", "ABANDONED")}

    @property
    def ddl(self) -> str:
        return f"""
            CREATE TABLE goal (
                TID             INT REFERENCES task(TID) ON DELETE CASCADE,
                GID             INT NOT NULL,
                GOAL            TEXT NOT NULL,
                STATUS          goal_status  NOT NULL DEFAULT 'OPEN'
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

class IntentTable(BaseTable):
    """Intent is an explicit and specific unit of work to achieve a Goal."""
    # TODO: 실행 후 삭제하게 하려면 IID로 지우고, 작업 record를 만들고 싶으면 enum으로 상태 관리하면 될 듯.
    name = "intent"

    @property
    def ddl(self) -> str:
        return f"""
            CREATE TABLE intent (
                TID             INT REFERENCES task(TID) ON DELETE CASCADE,
                GID             INT REFERENCES goal(GID) ON DELETE CASCADE,
                IID             SERIAL PRIMARY KEY,
                INTENT          TEXT NOT NULL,
            );"""

    def insert_intent(self, tid: int, gid: int, intent: str):
        self.db.execute_query( # TODO: 아직 IID는 serial.?
            "INSERT INTO intent (TID, GID, INTENT) VALUES (%s, %s, %s);",
            (tid, gid, intent)
        )

# ──────────────── 3. Research Tables ────────────────

class FindingTable(BaseTable):
    """Finding is a piece of information or insight discovered during the research process supporting a Goal."""
    name = "finding"
    enums = {"finding_status": {"OPEN", "CONFIRMED", "DISMISSED"}}

    @property
    def ddl(self) -> str:
        # DOUBLE_CHECK_SOURCE=True면 OPEN으로 두고 supervise를 받아야 하고, =False면 자동으로 CONFIRMED로 설정.
        default_status = r'OPEN' if self.db.options.get("CHECK_SOURCE_DOUBLE", False) else r'CONFIRMED'
        return f"""
            CREATE TABLE finding (
                TID             INT REFERENCES task(TID) ON DELETE CASCADE,
                GID             INT REFERENCES goal(GID) ON DELETE CASCADE,
                FINDINGID       INT NOT NULL,
                FINDING         TEXT NOT NULL,
                STATUS          finding_status  NOT NULL DEFAULT {default_status},

                PRIMARY KEY (TID, GID, FINDINGID)
            );"""
    
    def insert_finding(self, tid: int, gid: int, finding: str):
        # 해당 TID만 이용해 다음 FINDINGID를 계산 (Task별 Finding은 독립적이므로 GID는 고려하지 않음)
        result = self.db.execute_query("""
            SELECT COALESCE(MAX(FINDINGID) + 1, 0)
            FROM finding
            WHERE TID = %s;
            """, (tid,)
        )
        findingid = result[0][0]

        self.db.execute_query(
            "INSERT INTO finding (TID, GID, FINDINGID, FINDING) VALUES (%s, %s, %s, %s);",
            (tid, gid, findingid, finding)
        )

class EvidenceTable(BaseTable):
    """Evidence is a piece of information or data that connects findings and leaf node of ToC."""
    name = "evidence"

    @property
    def ddl(self) -> str:
        return f"""
            CREATE TABLE evidence (
                TID             INT REFERENCES task(TID) ON DELETE CASCADE,
                GID             INT REFERENCES goal(GID) ON DELETE CASCADE,
                EVIDENCEID      INT NOT NULL,
                FINDINGID       INT REFERENCES finding(FINDINGID) ON DELETE CASCADE,
                DOCID           INT REFERENCES document(DOCID) ON DELETE CASCADE,
                TOC_NODEID      INT REFERENCES toc(TOC_NODEID) ON DELETE CASCADE,
                LOCATION        TEXT NOT NULL,

                PRIMARY KEY (TID, GID, EVIDENCEID, FINDINGID)
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

