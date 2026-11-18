import json
import subprocess
import zipfile
from pathlib import Path
import psutil


# 격리 프로필용 설정: 확장 자동 활성화 + 첫 실행/텔레메트리 팝업 제거



class BrowserSession:
    """engine 시작 시 격리 프로필의 Firefox를 띄우고, 종료 시 닫는다. 프로필은 유지(쿠키/캡챠 통과 기록 보존)."""

    EXT_ID = "dom-sender@local"  # manifest.json의 gecko id와 동일
    EXT_FILES = ["manifest.json", "client.js", "serialize.js"]

    FIREFOX_PROFILE_PREFS = {
        "xpinstall.signatures.required": False,   # 서명 안 된 extension 설치 허용 # Developer Edition / Nightly / ESR 에서만 유효
        "extensions.autoDisableScopes": 0,
        "extensions.enabledScopes": 15,

        "browser.shell.checkDefaultBrowser": False, # 기본 브라우저로 설정 안 해요
        "browser.tabs.warnOnClose": False, # 여러 탭 한 번에 닫을 때 경고 안 해요
        "browser.aboutwelcome.enabled": False, # 첫 실행 시 환영 화면 안 띄워요

        "datareporting.policy.dataSubmissionEnabled": False, # 잡다한 안내 안 띄워요
        "toolkit.telemetry.reportingpolicy.firstRun": False,
    }

    def __init__(self, firefox_path: str, profile_dir: str, ext_dir: str):
        self.firefox = firefox_path
        self.profile = Path(profile_dir).resolve()
        self.ext_dir = Path(ext_dir).resolve()
        self.process = None
        # self.isExtensionLoaded = "on" if time.time() - getattr(server, "last_poll", 0) < 10 else "off"

    def start(self):
        self.profile.mkdir(parents=True, exist_ok=True)

        # install custom extension
        self._install_extension(self.EXT_ID, self.EXT_FILES) 

        # set firefox preferences
        lines = [f'user_pref("{k}", {json.dumps(v)});' for k, v in self.FIREFOX_PROFILE_PREFS.items()]   # bool→true/false, int→숫자
        (self.profile / "user.js").write_text("\n".join(lines), encoding="utf-8")

        # 시작 창 하나는 계속 남겨 두어, job 창이 모두 닫혀도 브라우저가 종료되지 않게 한다
        self.process = subprocess.Popen([self.firefox, "-profile", str(self.profile), "-no-remote", "about:blank"])
        import time; time.sleep(2)  # 브라우저가 완전히 뜰 때까지 잠시 대기
        print("pid:", self.process.pid, "poll:", self.process.poll())


    def stop(self):
        if not self.process:
            return
        self.process.terminate()
        try:
            self.process.wait(10)
        except subprocess.TimeoutExpired:
            self.process.kill()
        self.process = None

    def _install_extension(self, ext_id, ext_files):
        ext_path = self.profile / "extensions"
        ext_path.mkdir(exist_ok=True)

        try:
            with zipfile.ZipFile(ext_path / f"{ext_id}.xpi", "w", zipfile.ZIP_DEFLATED) as z:   # 매번 덮어써서 코드 변경 반영
                for name in ext_files:
                    z.write(self.ext_dir / name, name)

        except OSError as e:
            print(f"Browser is already open: {e}")


    def is_browser_alive(self):
        key = str(self.profile).lower()
        for p in psutil.process_iter(["name", "cmdline"]):
            if p.info["name"] and "firefox" in p.info["name"].lower():
                if any(key in (a or "").lower() for a in (p.info["cmdline"] or [])):
                    return True
        return False
