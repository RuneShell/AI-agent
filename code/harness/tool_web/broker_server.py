# 1. built-in
import json
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote


# 2. third-party

# 3. custom
from worker import Worker
worker = Worker() # temp. TODO: 이름을 바꿀 것.


def log(*args):
    # 파이프/IDE에서 실행하면 stdout이 버퍼링되어 로그가 안 보일 수 있으므로 즉시 flush
    print(*args, flush=True)



"""
dashboard에 보낼 목록

reply,
options, post, log-수집된 목록
broker queue, running job 목록.

"""



class HTTPHandler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*") # 모든 출처 허용 # TODO : 제한.
        # custom headers: X-Kind, X-Source-Url, X-Filename
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Kind, X-Source-Url, X-Filename")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")

    def _reply(self, status, text):
        body = text.encode("utf-8")
        # == expected Responses ==
        # 200 OK
        # 400 Bad Request : Invalid file type
        # 403 Forbidden : Invalid source URL
        # 500 Internal Server Error
        self.send_response(status)
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body) # send response to client

    def do_OPTIONS(self): # preflight request
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        print(f"\n[POSTED]")

        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            kind = self.headers.get("X-Kind")
            log(f"[recieved] kind={kind} bytes={length}")

            # ===========================

            # 1. image의 경우 - 바로 저장
            if kind == "image":
                self.handle_image(body)

            # 2. html의 경우 - 따로 처리 후 저장
            elif kind == "html":
                self.handle_html(body)

            else:
                #self._reply(400, f"unknown kind: {kind}")
                return

            # ===========================

            self._reply(200, "ok")

        except Exception:
            traceback.print_exc()
            sys.stderr.flush()
            # try:
            #     self._reply(500, "server error (see server console)")
            # except Exception:
            #     pass
            print("POST failed")

    def handle_image(self, body: bytes):
        meta = {
            "content_type": self.headers.get("Content-Type"),
            "url": unquote(self.headers.get("X-Source-Url", "")),
            "filename": unquote(self.headers.get("X-Filename", "image")),
        }
        log("[image]", meta["content_type"], meta["filename"], meta["url"], f"{len(body)} bytes")
        # TODO: 저장

    def handle_html(self, body: bytes):
        payload = json.loads(body)

        html = payload.get('html', '')
        css  = payload.get("css", [])
        js   = payload.get("js", [])
        meta = payload.get("meta", {}) # ['url', 'canonical', 'title', 'captured_at', 'ready_state', 'selection', 'scroll', 'viewport': {'width', 'height'}, 'frames']

        ready_state = meta["ready_state"]
        selection = meta["selection"]

        # 전체를 print하면 수 MB가 쏟아지므로 요약만 출력
        log(f"[html] {payload.get("url")} (ready={ready_state})")
        log(f"\thtml={len(html)}, css={len(css)}, js={len(js)} chars.")
        log(f"\tselection={selection if selection else "None"}, {meta["frames"]}")


        # 일단 원본 백업
        worker.file_manager.save_html(html, "raw.html")

        # agent가 읽기 좋도록 clean
        cleaned, links = worker.clean(html)
        worker.file_manager.save_html(cleaned, "clean.html")






import queue
from dataclasses import dataclass, field
import uuid  # job에 unique id를 부여하기 위해


class BrokerServer:

    @dataclass
    class Job:
        url:    str
        id:     str = field(default_factory=lambda: str(uuid.uuid4())) # 자동으로 unique id 부여
        status: str = "pending"  # pending, running, done


    def __init__(self, host_ip: str, host_port: int):
        self.server = ThreadingHTTPServer((host_ip, host_port), HTTPHandler) # 1 request 1 thread
        self.isServerUP = False

        self.job_ready = queue.Queue()  # job이 들어오면 put, worker가 가져가면 get
        self.job_running = dict()

        


    def start(self):
        print(f"Server UP at {self.server.server_address}")
        self.server.serve_forever()
        self.isServerUP = True
    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.isServerUP = False
        print("Server DOWN.")

    def fetch(self, url: str):
        if not self.isServerUP:
            raise RuntimeError("HTTP server is down.")

        job = self.Job(url)
        self.job_ready.put(job)
        
