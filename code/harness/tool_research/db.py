import psycopg

# SQL 문법에 format string 쓰면 SQL Injection 공격에 취약하므로, 항상 파라미터 바인딩(%s) 을 사용해야 합니다.

class ResearchDB:
    def __init__(self):
        DB_CONFIG = {
            "host": "localhost",
            "port": 5432, # Docker container port
            "dbname": "research",
            "user": "app",
            "password": "1234"
        }

        # Connect to PostgreSQL DB.
        try:
            self.conn = psycopg.connect(**DB_CONFIG)
        except psycopg.OperationalError:
            raise ConnectionError(f"port {DB_CONFIG['port']} is closed. Docker container may be down.")

        self.tables = self.get_table_names() # restore prev session tables
        print(self.tables) # TODO : logger

    def execute_query(self, query: str, params: tuple = None, num_result: int = -1): # TODO : 이거 아래에 많이 적용
        with self.conn.cursor() as cur:
            cur.execute(query, params)

            if cur.description:  # SELECT 쿼리인 경우
                if num_result > 0:
                    return cur.fetchmany(num_result)
                else:
                    return cur.fetchall() # 모든 결과
            else:  # INSERT, UPDATE, DELETE 쿼리인 경우
                self.conn.commit()
                return None



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
            cur.execute(f"SELECT COUNT(*) FROM {table_name}")
            total_count = cur.fetchone()[0]

            cur.execute(f"SELECT * FROM {table_name} LIMIT %s", (count,))
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
            self.conn.commit()


    def close_connection(self, ):
        if self.conn:
            self.conn.close()



    #==== Additional methods for research-specific operations ====

    ##== 1. Tasks ==

    def init_table_tasks(self):
        if 'tasks' in self.tables:
            return
        self.tables.append('tasks')

        # create ENUM : task_status
        self.execute_query("""
            CREATE TYPE task_status AS ENUM(
                'IDLE',
                'RUNNING',
                'PAUSED',
                'DONE'
            );""")

        # create table : tasks
        self.execute_query("""
            CREATE TABLE tasks (
                TID SERIAL PRIMARY KEY,
                primary_goal TEXT NOT NULL,
                status task_status NOT NULL DEFAULT 'IDLE'
            );""")

    def insert_task(self, primary_goal: str) -> int | None:
        if 'tasks' not in self.tables:
            return None 
        
        records = self.execute_query(f"""
            INSERT INTO tasks (primary_goal)
            VALUES (%s)
            RETURNING TID;
        """, (primary_goal,))  

        return records[0] # return new task's ID (TID)



    ##== 2. Goals ==

    def init_table_goals(self):
        if 'goals' in self.tables:
            return
        self.tables.append('goals')

        # create ENUM : goal_status
        self.execute_query("""
            CREATE TYPE goal_status AS ENUM(
                'OPEN',
                'MET',
                'ABANDONED'
            );""")

        # create table : goals
        self.execute_query("""
                CREATE TABLE goals (
                GID SERIAL PRIMARY KEY,
                TID INT REFERENCES tasks(TID) ON DELETE CASCADE,
                goal TEXT NOT NULL,
                status goal_status NOT NULL DEFAULT 'OPEN'
            );""")

    def insert_goal(self, TID: int, goal: str) -> int | None:
        if 'goals' not in self.tables:
            return None

        records = self.execute_query("""
            INSERT INTO goals (TID, goal)
            VALUES (%s, %s)
            RETURNING GID;
        """, (TID, goal))

        return records[0] # return new goal's ID (GID)


    def get_task_report(self, TID: int) -> str:
        if 'goals' not in self.tables:
            return ""

        return "" # TODO : ...



    ##== 3. Intents ==

    def init_table_intents(self):
        if 'intents' in self.tables:
            return
        self.tables.append('intents')

        # create ENUM : intent_status
        self.execute_query("""
            CREATE TYPE intent_status AS ENUM(
                'PENDING',
                'WORKING',
                'FAILED',
                'TIMEOUT',
                'DONE',
                'APPROVED',
                'DISCARDED'
            );""")

        # create table : intents
        self.execute_query("""
            CREATE TABLE intents (
                IID SERIAL PRIMARY KEY,
                TID INT REFERENCES tasks(TID) ON DELETE CASCADE,
                GID INT REFERENCES goals(GID) ON DELETE CASCADE,
                intent TEXT NOT NULL,
                status intent_status NOT NULL DEFAULT 'PENDING'
            );""")

    def get_intents(self, TID: int, GID: int, num_result: int = 4) -> list[str]:
        if 'intents' not in self.tables:
            return []

        # FAILED나 TIMEOUT은 검수 후에 다시 PENDING으로 되돌려짐.
        records = self.execute_query("""
            SELECT intent
            FROM intents
            WHERE TID = %s AND GID = %s AND status = 'PENDING';
        """, (TID, GID), num_result) 

        return [row[0] for row in records]