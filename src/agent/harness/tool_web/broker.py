# 1. built-in
import json
import time
from dataclasses import dataclass, field

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import queue # job queue
import uuid  # job id (unique)
import base64 # decode returned image

# 2. third-party

# 3. custom
from .worker import Worker
from .browser import BrowserSession
from ...log_poller import LogPoller


def log(*args):
    # 파이프/IDE에서 실행하면 stdout이 버퍼링되어 로그가 안 보일 수 있으므로 즉시 flush
    print(*args, flush=True)


# TODO : 전역변수 다 집어넣기
AUTH_TOKEN = "tool_web"
GET_ENDPOINT_PATH = "jobs/next"
POST_ENDPOINT_PATH = "jobs/report"

FIREFOX_PATH = r"C:\Program Files\Firefox Developer Edition\firefox.exe"
# notebook
# PROFILE_DIR = r"C:\Users\Computer\AppData\Roaming\Mozilla\Firefox\Profiles\tool_web"
# EXT_DIR = r".\src\agent\harness\tool_web\browser"
# PC
PROFILE_DIR = r"C:\Users\admin\AppData\Roaming\Mozilla\Firefox\Profiles\tool_web"
EXT_DIR = r".\src\agent\harness\tool_web\browser"



class Broker:

    @dataclass
    class Job:
        url:    str
        id:     str = field(default_factory=lambda: uuid.uuid4().hex) # 자동으로 unique id 부여
        state:  threading.Event = field(default_factory=threading.Event) # 실행 대기 시 wait(), 할당 시 set()
        result: str = ""
        saved_path: str = "" # 저장된 파일 경로. html / image 등


    def __init__(self, host_ip: str, host_port: int, poller=None):
        self.server_address = (host_ip, host_port)

        self.job_ready = queue.Queue()  # job이 들어오면 put, worker가 가져가면 get
        self.job_running = dict()
        self._lock = threading.Lock() # job_running에 접근할 때 lock

        # HTTP server
        self.server = BrokerHTTPServer(host_ip, host_port, 
                                       self._take_job, self._report_job) # HTTPHandler에서 job을 다룰 함수를 넘김.
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

        # stop browser
        if self.browser.process:
            self.browser.stop()
            print("Browser DOWN.")

    # ──────── agent tool ────────
    def fetch(self, url: str, timeout: float = 60.0) -> str:
        job = self.Job(url)
        self.job_ready.put(job)

        # timeout 동안 꺼내가기를 기다림.
        if job.state.wait(timeout): # wait `_report_job()` call.
            if job.saved_path:
                return job.saved_path # TODO 정말 file로 저장하고, 경로만 넘기는게 최적인가?
            # else:
            #     return job.result 
        else: # time out
            timeout = "Failed to fetch the URL: Timeout."
            job.result = timeout
            log(timeout)
            self.job_ready.put(job) # 실패 시 다시 job_ready에 넣음.
            # TODO: 그 이후에는?
            return job.result
        

    # ──────── client(browser extention)-side ────────
    def _take_job(self): 
        if self.job_ready.empty():
            return None

        job = self.job_ready.get()
        with self._lock:
            self.job_running[job.id] = job
        return job 
    def _report_job(self, job_id: str, saved_path: str):
        with self._lock:
            job = self.job_running.pop(job_id, None)
        if not job:
            log(f"[broker] report_job: job_id={job_id} not found")
            return

        job.saved_path = saved_path
        job.state.set() # job이 끝났으므로 fetch()로 되돌아감.





class BrokerHTTPServer(ThreadingHTTPServer):
    daemon_threads = True  # 서버 종료 시 모든 thread 종료

    def __init__(self, host_ip: str, host_port: int, take_job: callable, report_job: callable):
        self.server_address = (host_ip, host_port)
        super().__init__(self.server_address, HTTPHandler)
        self.last_poll = 0 # 마지막에 extension이 poll한 시각. dashboard에서 표시용.

        self.worker = Worker() # 받은 파일을 작업

        self.take_job = take_job
        self.report_job = report_job





class HTTPHandler(BaseHTTPRequestHandler):
    @property
    def worker(self) -> Worker: 
        # `this.server.worker` is not intuitive (server does not have worker), so wrap it.
        return self.server.worker
    
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*") # 모든 출처 허용 # TODO : 제한. token?
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Auth-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST")

    def _reply(self, status, text):
        # == expected Responses ==
        # 200 OK
        # 204 No Content : no job
        # 401 Unauthorized : Invalid X-Auth-Token
        # 404 Not Found : Invalid endpoint

        # url 전송 시 str / response=401 시 bytes.
        body = text if isinstance(text, bytes) else text.encode("utf-8")
        self.send_response(status)
        self._cors()

        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body) # send response to client

    def _check_auth(self):
        if self.headers.get("X-Auth-Token") == AUTH_TOKEN:
            return True
        self._reply(401, "Unauthorized")
        return False

    # ──────────────── client-side (extension) ────────────────
    def do_GET(self): # extension이 long-polling으로 job을 받아가는 요청.
        self.server.last_poll = time.time()
        # check if valid
        if not self._check_auth():
            return
        if self.path != f"/{GET_ENDPOINT_PATH}":
            return self._reply(404, "Invalid endpoint.")

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
        #check if valid
        if not self._check_auth():
            return
        if self.path != f"/{POST_ENDPOINT_PATH}":
            return self._reply(404, "Invalid endpoint.")

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        kind = self.headers.get("X-Kind")
        log(f"POST {self.path} from {self.client_address} kind={kind} bytes={length}")

        if self.path == f"/{POST_ENDPOINT_PATH}":
            event = json.loads(body)

            job_status = event["status"]
            result = event["result"]

            meta = result["meta"]
            url = result['url']

            if job_status == "ok":
                print(f"job {url} completed successfully.")

                # Handling files
                saved_path = ""
                if result["kind"] == "html":
                    cleaned_html, links = self.worker.clean(result["html"])
                    # TODO: save links to DB?
                    saved_path = self.worker.file_manager.save_html(cleaned_html, "clean.html")
                    
                elif result["kind"] == "image":
                    raw = base64.b64decode(result["bytes_b64"])  # bytes_b64 → bytes decoding
                    saved_path = self.worker.file_manager.save_img(raw, meta, filename=result["filename"])
 
                self.server.report_job(event["id"], saved_path)


                
            elif job_status == "failed":
                print(f"job {url} failed: {event.get('result', '')}")
                self.server.report_job(event["id"], f"[failed] {event.get('error', '')}")
                pass
            elif job_status == "needs_human":
                print(f"job {url} needs human intervention.")
                pass
            else:
                print(f"Unknown job status: {job_status}")

            return self._reply(200, "ok")



if __name__ == "__main__":
    poller = LogPoller("tool_web", "http://127.0.0.1:10000/report", interval=2)
    poller.start()

    broker = Broker("127.0.0.1", 11101, poller)
    broker.start()

    broker.fetch(r"https://example.com")

    broker.stop()
    poller.stop()