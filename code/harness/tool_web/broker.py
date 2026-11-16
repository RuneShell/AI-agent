# 1. built-in
import json
import queue
import threading
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

# 3. custom (Worker는 harness 쪽에서 만들어 주입)

TOKEN = "dev-token"  # client.js의 TOKEN과 동일해야 함
FAIL = "Failed to fetch the URL. "


@dataclass
class Job:
    url: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    done: threading.Event = field(default_factory=threading.Event)
    result: str = ""


class Broker:
    """harness 프로세스 안에서 도는 중계 서버. fetch()가 job을 등록하고 확장이 결과를 올릴 때까지 블록한다."""

    def __init__(self, worker, host="127.0.0.1", port=11101, on_human=None):
        self.worker = worker
        self.queue = queue.Queue()
        self.jobs = {}                       # id -> Job (대기 중인 것만)
        self.lock = threading.Lock()         # worker 호출 직렬화 (병렬 확장 시 안전장치)
        self.ready = threading.Event()       # 확장이 처음 접속하면 set
        self.on_human = on_human or (lambda job: print(f"[browser] 사람 개입 필요: {job.url}"))
        self.server = ThreadingHTTPServer((host, port), self._make_handler())

    # ━━━━━━━━━━━━━━━━━━━━ PUBLIC API ━━━━━━━━━━━━━━━━━━━━
    def start(self):
        # Open server in background thread.
        print("Server UP...")
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        print("Server DOWN.")

    def wait_ready(self, timeout=30):
        return self.ready.wait(timeout)

    def fetch(self, url: str, timeout: float = 60) -> str:
        job = Job(url)
        self.jobs[job.id] = job
        self.queue.put(job)
        if not job.done.wait(timeout):
            job.result = FAIL + "Timeout"
        self.jobs.pop(job.id, None)
        return job.result

    # ━━━━━━━━━━━━━━━━━━━━ HTTP HANDLER ━━━━━━━━━━━━━━━━━━━━
    def _make_handler(self):
        broker = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _cors(self):
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers",
                                 "Content-Type, X-Kind, X-Source-Url, X-Filename, X-Token, X-Job-Id, X-Http-Status")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

            def _reply(self, code, body=b""):
                self.send_response(code)
                self._cors()
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _authed(self):
                if self.headers.get("X-Token") == TOKEN:
                    return True
                self._reply(401)
                return False

            def do_OPTIONS(self):
                self._reply(204)

            # 확장이 job을 받아가는 long-poll
            def do_GET(self):
                if not self._authed():
                    return
                broker.ready.set()
                try:
                    while True:
                        print("job 받아가기 시도..")
                        job = broker.queue.get(timeout=25)
                        if job.id in broker.jobs:       # 이미 timeout된 job은 건너뜀
                            break
                except queue.Empty:
                    return self._reply(204)

                payload = json.dumps({"id": job.id, "url": job.url}).encode()
                try:
                    self._reply(200, payload)
                except OSError:   # ConnectionAbortedError, BrokenPipeError 등을 포함
                    print(f"전달 실패, job 재등록: {job.url}")
                    broker.queue.put(job)
                    return
                print(f"job 받아감: {job.url}")
            def do_POST(self):
                print(f"POST {self.path} from {self.client_address}`")
                if not self._authed():
                    return
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                print(f"POST {self.path} ({len(body)} bytes)")

                # 진행 상태 / 실패 보고
                if self.path == "/job-event":
                    ev = json.loads(body)
                    job = broker.jobs.get(ev["id"])
                    if job and ev["state"] == "needs_human":
                        broker.on_human(job)
                    elif job and ev["state"] == "failed":
                        job.result = FAIL + ev.get("detail", "")
                        job.done.set()
                    return self._reply(200, b"ok")

                # 캡처 결과 (job 없으면 수동 캡처 → 저장만)
                print(f"headers: {self.headers}")
                job = broker.jobs.get(self.headers.get("X-Job-Id"))
                try:
                    result = broker._process(self.headers, body, has_job=job is not None)
                except Exception as e:
                    if job:
                        job.result = FAIL + str(e)
                        job.done.set()
                    raise
                if job:
                    job.result = result
                    job.done.set()
                self._reply(200, b"ok")

        return Handler

    # ━━━━━━━━━━━━━━━━━━━━ RESULT PROCESSING (기존 server.py 로직) ━━━━━━━━━━━━━━━━━━━━
    def _process(self, headers, body, has_job):
        kind = headers.get("X-Kind")
        status = int(headers.get("X-Http-Status", 200))

        with self.lock:
            # 1. image의 경우 - 바로 저장
            if kind == "image":
                meta = {
                    "content_type": headers.get("Content-Type"),
                    "url": unquote(headers.get("X-Source-Url", "")),
                    "filename": unquote(headers.get("X-Filename", "image")),
                }
                self.worker.file_manager.save_img(body, meta)
                return f"Image saved: {meta['filename']}"

            # 2. html의 경우 - 따로 처리 후 저장
            if kind == "html":
                if has_job and status >= 400:
                    return FAIL + f"Status code: {status}"
                data = json.loads(body)          # {kind, url, html, css?, script?, meta}
                cleaned, links = self.worker.clean(data['html'])

                self.worker.file_manager.save_html(cleaned, "cleaned.html")
                return cleaned
        raise TypeError(f"Unknown kind: {kind}")
