# 1. built-in
import json
import sys
import traceback
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote
import queue
from dataclasses import dataclass, field
import uuid  # job에 unique id를 부여하기 위해



# 2. third-party

# 3. custom
# from worker import Worker
# worker = Worker() # temp. TODO: 이름을 바꿀 것.
from browser import BrowserSession
from log_poller import LogPoller


def log(*args):
    # 파이프/IDE에서 실행하면 stdout이 버퍼링되어 로그가 안 보일 수 있으므로 즉시 flush
    print(*args, flush=True)


# TODO : 전역변수 다 집어넣기
GET_ENDPOINT_PATH = "jobs/next"
POST_ENDPOINT_PATH = "jobs/report"

FIREFOX_PATH = r"C:\Program Files\Firefox Developer Edition\firefox.exe"
PROFILE_DIR = r"C:\Users\Computer\AppData\Roaming\Mozilla\Firefox\Profiles\tool_web"
EXT_DIR = r".\src\agent\harness\tool_web\browser"

"""
dashboard에 보낼 목록

reply,
options, post, log-수집된 목록
broker queue, running job 목록.

"""


"""How to assemble classes
broker = Broker(ip, port)
frontend_server = BrokerHTTPServer(ip, port, broker)
frontend_server.start()

broker.fetch(url)  # blocking until job is done

frontend_server.stop()
"""


"""
Job.result
wait_extension_ready
token
"""



class Broker:

    @dataclass
    class Job:
        url:    str
        id:     str = field(default_factory=lambda: uuid.uuid4().hex) # 자동으로 unique id 부여
        state:  threading.Event = field(default_factory=threading.Event) # 실행 대기 시 wait(), 할당 시 set()
        result: str = ""


    def __init__(self, host_ip: str, host_port: int, poller=None):
        self.server_address = (host_ip, host_port)

        self.job_ready = queue.Queue()  # job이 들어오면 put, worker가 가져가면 get
        self.job_running = dict()
        self._lock = threading.Lock() # job_running에 접근할 때 lock

        # HTTP server
        self.server = BrokerHTTPServer(host_ip, host_port, 
                                       self.take_job, self.report_job) # HTTPHandler에서 job을 다룰 함수를 넘김.
        self.server_thread: threading.Thread = None

        # browser
        self.browser = BrowserSession(FIREFOX_PATH, PROFILE_DIR, EXT_DIR)

        # dashboard
        self.poller = poller
        if self.poller:
            self.poller.register("Broker", self.get_dashboard_broker_widgets)

    def get_dashboard_broker_widgets(self):
        payload = {"type": "group", "name": "Broker", "children": [
            {"type": "lamp", "name": "HTTP Server", "value": "on" if self.server_thread and self.server_thread.is_alive() else "off"},
            {"type": "lamp", "name": "browser", "value": "on" if self.browser.is_browser_alive() else "error"},
            {"type": "lamp", "name": "DOM-sender", "value": "on" if time.time() - getattr(self.server, "last_poll", 0) < 5 else "error"},
            {"type": "group", "name": "job_queue", "children": [
                {"type": "text", "name": f"ready({self.job_ready.qsize()})", 
                 "value": [job.url for job in list(self.job_ready.queue)]},
                {"type": "text", "name": f"running({len(self.job_running)})",
                 "value": [job.url for job in list(self.job_running.values())]}
            ]}
        ]}
        return [payload]


    # ──────── life cycle ────────

    def start(self): # TODO: server랑 brwoser 중 뭐가 먼저지?
        # start server
        if not self.server_thread: # 이미 있다면 넘어감.
            print(f"Server UP at {self.server_address}")
            self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True) # TODO: 여기 daemon?
            self.server_thread.start()

        # start browser
        if not self.browser.process:
            print(f"Browser UP at {self.browser.profile}")
            self.browser.start()
    def stop(self):
        # stop server
        if self.server_thread: # 종료할 서버가 없다면 넘어감.
            self.server.shutdown()
            self.server.server_close()
            self.server_thread.join() # to make self.server_thread.is_alive() = false
            self.server_thread = None
            print("Server DOWN.")

        # stop server
        if self.browser.process:
            self.browser.stop()
            print("Browser DOWN.")

    # ──────── agent tool ────────
    def fetch(self, url: str, timeout: float = 30.0) -> str:
        job = self.Job(url)
        self.job_ready.put(job)

        # timeout 동안 꺼내가기를 기다림.
        if job.state.wait(timeout):
            return job.result
        else: # time out
            timeout = "Failed to fetch the URL: Timeout."
            job.result = timeout
            log(timeout)
            self.job_ready.put(job) # 실패 시 다시 job_ready에 넣음.
            # TODO: 그 이후에는?
            return timeout

    # ──────── client(browser extention)-side ────────
    def take_job(self): 
        if self.job_ready.empty():
            return None

        job = self.job_ready.get()
        with self._lock:
            self.job_running[job.id] = job
        return job
    def report_job(self, job_id: str, result: str):
        with self._lock:
            job = self.job_running.pop(job_id, None)
        if not job:
            log(f"[broker] report_job: job_id={job_id} not found")
            return

        job.result = result
        job.state.set() # job이 끝났으므로 fetch()로 되돌아감.





class BrokerHTTPServer(ThreadingHTTPServer):
    daemon_threads = True  # 서버 종료 시 모든 thread 종료

    def __init__(self, host_ip: str, host_port: int, take_job: callable, report_job: callable):
        self.server_address = (host_ip, host_port)
        super().__init__(self.server_address, HTTPHandler)
        self.last_poll = 0 # 마지막에 extension이 poll한 시각. dashboard에서 표시용.
        
        self.take_job = take_job
        self.report_job = report_job





class HTTPHandler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*") # 모든 출처 허용 # TODO : 제한. token?
        # custom headers: X-Kind, X-Source-Url, X-Filename
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Auth-Token, X-Kind, X-Source-Url, X-Filename")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")

    def _reply(self, status, text):
        # == expected Responses ==
        # 200 OK
        # 400 Bad Request : Invalid file type
        # 403 Forbidden : Invalid source URL
        # 500 Internal Server Error

        # url 전송 시 str / response=401 시 bytes.
        body = text if isinstance(text, bytes) else text.encode("utf-8")
        self.send_response(status)
        self._cors()

        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body) # send response to client

    def _check_auth(self):
        if self.headers.get("X-Token") == "tool_web":
            return True
        self._reply(401, "Unauthorized")
        return False

    def do_OPTIONS(self): # preflight request
        self._reply(204, "")

    def do_GET(self): # extension이 long-polling으로 job을 받아가는 요청.
        self.server.last_poll = time.time()

        # check if authed
        # if not self._check_auth():
        #     return

        # TODO: if self.path != f"/{GET_ENDPOINT_PATH}": return self._reply(404, "Not Found")

        job = self.server.take_job() # broker의 take_job() 호출
        if not job:
            return self._reply(204, "") # no job

        # payload 
        payload = json.dumps({"id": job.id, "url": job.url}).encode()

        # send the job to extension
        try:
            self._reply(200, payload)
        except OSError as e: # ConnectionAbortedError, BrokenPipeError 등을 포함
            print(f"전달 실패, job 재등록: {job.url}")
            return self.server.report_job(job.id, f"failed to deliver: {e}")

        print(f"job 전달됨: {job.url}")

    def do_POST(self):
        print(f"POST {self.path} from {self.client_address}`")
        # check if authed
        # if not self._check_auth():
        #     return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        kind = self.headers.get("X-Kind")
        log(f"[recieved] kind={kind} bytes={length}")

        if self.path == f"/{POST_ENDPOINT_PATH}":
            event = json.loads(body)

            # TODO: 반환된 job을 처리
            print(f"job report: {event}")

            self.server.report_job(event["id"], event.get("result", ""))
            return self._reply(200, "ok")

        # TODO: 헤더 처리.

    #     try:
    #         # ===========================

    #         # 1. image의 경우 - 바로 저장
    #         if kind == "image":
    #             self.handle_image(body)

    #         # 2. html의 경우 - 따로 처리 후 저장
    #         elif kind == "html":
    #             self.handle_html(body)

    #         else:
    #             #self._reply(400, f"unknown kind: {kind}")
    #             return

    #         # ===========================

    #         self._reply(200, "ok")

    #     except Exception:
    #         traceback.print_exc()
    #         sys.stderr.flush()
    #         # try:
    #         #     self._reply(500, "server error (see server console)")
    #         # except Exception:
    #         #     pass
    #         print("POST failed")

    # def handle_image(self, body: bytes):
    #     meta = {
    #         "content_type": self.headers.get("Content-Type"),
    #         "url": unquote(self.headers.get("X-Source-Url", "")),
    #         "filename": unquote(self.headers.get("X-Filename", "image")),
    #     }
    #     log("[image]", meta["content_type"], meta["filename"], meta["url"], f"{len(body)} bytes")
    #     # TODO: 저장

    # def handle_html(self, body: bytes):
    #     payload = json.loads(body)

    #     html = payload.get('html', '')
    #     css  = payload.get("css", [])
    #     js   = payload.get("js", [])
    #     meta = payload.get("meta", {}) # ['url', 'canonical', 'title', 'captured_at', 'ready_state', 'selection', 'scroll', 'viewport': {'width', 'height'}, 'frames']

    #     ready_state = meta["ready_state"]
    #     selection = meta["selection"]

    #     # 전체를 print하면 수 MB가 쏟아지므로 요약만 출력
    #     log(f"[html] {payload.get("url")} (ready={ready_state})")
    #     log(f"\thtml={len(html)}, css={len(css)}, js={len(js)} chars.")
    #     log(f"\tselection={selection if selection else "None"}, {meta["frames"]}")


    #     # 일단 원본 백업
    #     worker.file_manager.save_html(html, "raw.html")

    #     # agent가 읽기 좋도록 clean
    #     cleaned, links = worker.clean(html)
    #     worker.file_manager.save_html(cleaned, "clean.html")





if __name__ == "__main__":
    poller = LogPoller("tool_web", "http://127.0.0.1:10000/report", interval=2)
    poller.start()

    broker = Broker("127.0.0.1", 11101, poller)
    broker.start()

    broker.fetch("https://example.com")

    broker.stop()
    poller.stop()