// ━━━━━━━━━━━━━━━━━━━━ CONFIG ━━━━━━━━━━━━━━━━━━━━
const BROKER = "http://127.0.0.1:11101";
const TOKEN = "dev-token";            // broker.py의 TOKEN과 동일해야 함
const MAX_CONCURRENT = 1;             // 병렬 job 수. job마다 별도 창을 쓰므로 늘려도 구조 변경 없음
const LOAD = { idleMs: 500, domQuietMs: 500, domQuietMaxMs: 5000, timeoutMs: 20000 };
const HUMAN_TIMEOUT_MS = 5 * 60 * 1000;
const WAKE_LAZY = true;               // 캡처 전 한 번 끝까지 스크롤해 lazy 콘텐츠를 깨움
const CHALLENGE_RE = /just a moment|attention required|verify you are human|are you human|access denied/i;
const CHALLENGE_SELECTOR = 'iframe[src*="challenges.cloudflare.com"], iframe[src*="recaptcha"], iframe[src*="hcaptcha"], #challenge-form, .g-recaptcha, .h-captcha, .cf-turnstile';

// ━━━━━━━━━━━━━━━━━━━━ UTILS ━━━━━━━━━━━━━━━━━━━━
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const run = async (tabId, code) => (await browser.tabs.executeScript(tabId, { code }))[0];
const sendEvent = (id, state, detail = "") =>
  fetch(`${BROKER}/job-event`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Token": TOKEN },
    body: JSON.stringify({ id, state, detail })
  }).catch((e) => console.error("event 전송 실패:", e));

// ━━━━━━━━━━━━━━━━━━━━ NETWORK STATE (탭별 진행 중 요청 / 마지막 main_frame 상태코드) ━━━━━━━━━━━━━━━━━━━━
const tabState = new Map();
const state = (tabId) => {
  if (!tabState.has(tabId)) tabState.set(tabId, { inflight: new Set(), lastActivity: Date.now(), status: null });
  return tabState.get(tabId);
};
const NET_FILTER = {
  urls: ["<all_urls>"],
  types: ["main_frame", "sub_frame", "script", "stylesheet", "image", "xmlhttprequest", "font", "media", "object", "other"]
};
const netDone = (d) => {
  if (d.tabId < 0) return;
  const s = state(d.tabId);
  s.inflight.delete(d.requestId);
  s.lastActivity = Date.now();
};
browser.webRequest.onBeforeRequest.addListener((d) => {
  if (d.tabId < 0) return;
  const s = state(d.tabId);
  s.inflight.add(d.requestId);
  s.lastActivity = Date.now();
}, NET_FILTER);
browser.webRequest.onCompleted.addListener((d) => {
  netDone(d);
  if (d.tabId >= 0 && d.type === "main_frame") state(d.tabId).status = d.statusCode;
}, NET_FILTER);
browser.webRequest.onErrorOccurred.addListener(netDone, NET_FILTER);

// ━━━━━━━━━━━━━━━━━━━━ LOAD WAIT ━━━━━━━━━━━━━━━━━━━━
// 신호 3개: tab complete + 진행 중 요청 0 (idleMs 유지) + DOM 변화 없음. 전체 timeout 초과 시 현재 상태로 진행
async function waitLoaded(tabId) {
  const start = Date.now();
  while (Date.now() - start < LOAD.timeoutMs) {
    const tab = await browser.tabs.get(tabId);
    const s = state(tabId);
    if (tab.status === "complete" && tab.url !== "about:blank" && s.inflight.size === 0 && Date.now() - s.lastActivity >= LOAD.idleMs) break;
    await sleep(200);
  }
  const tab = await browser.tabs.get(tabId);
  if (!/^https?:/.test(tab.url)) throw new Error(`load failed: ${tab.url}`);   // about:neterror 등

  await run(tabId, `new Promise((res) => {
    let t; const done = () => { mo.disconnect(); res(true); };
    const mo = new MutationObserver(() => { clearTimeout(t); t = setTimeout(done, ${LOAD.domQuietMs}); });
    mo.observe(document, { subtree: true, childList: true, characterData: true });
    t = setTimeout(done, ${LOAD.domQuietMs});
    setTimeout(done, ${LOAD.domQuietMaxMs});
  })`);
}

async function wakeLazy(tabId) {
  await run(tabId, `(async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const end = Math.min(document.documentElement.scrollHeight, innerHeight * 20);
    for (let y = 0; y < end; y += innerHeight) { scrollTo(0, y); await sleep(150); }
    scrollTo(0, 0);
  })()`);
  await waitLoaded(tabId);
}

// ━━━━━━━━━━━━━━━━━━━━ CHALLENGE (캡챠 등) ━━━━━━━━━━━━━━━━━━━━
// 정확한 감지는 불가능 — 제목/마커 요소 기반 휴리스틱. 실행 실패(페이지 이동 중 등)는 "아직 챌린지"로 간주
async function hasChallenge(tabId) {
  try {
    return await run(tabId, `(() => {
      const title = document.title || "";
      const bodyLen = (document.body?.innerText || "").trim().length;

      // 1) Cloudflare 고유 마커 (정상 페이지에는 거의 없음)
      if (document.querySelector('#challenge-form, #cf-challenge-running, #challenge-running, #cf-please-wait')) return true;

      // 2) 화면에 실제로 보이는 챌린지 iframe/위젯만 인정
      const visible = (el) => {
        const r = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        return r.width > 50 && r.height > 30 && cs.visibility !== 'hidden' && cs.display !== 'none';
      };
      const widgets = document.querySelectorAll(${JSON.stringify(CHALLENGE_SELECTOR)});
      const hasVisibleWidget = [...widgets].some(visible);

      // 3) 제목 매칭은 "본문이 빈약할 때"만 신뢰
      const titleHit = (${CHALLENGE_RE}).test(title);

      if (titleHit && bodyLen < 1500) return true;     // 전형적인 차단/대기 페이지
      if (hasVisibleWidget && bodyLen < 1500) return true;
      return false;
    })()`);
  } catch { return false; }
}

async function waitHuman(tabId, job) {
  const start = Date.now();
  while (!job.force && Date.now() - start < HUMAN_TIMEOUT_MS && (await hasChallenge(tabId))) await sleep(2000);
  if (!job.force && (await hasChallenge(tabId))) throw new Error("human timeout");
}

// ━━━━━━━━━━━━━━━━━━━━ CAPTURE & SEND ━━━━━━━━━━━━━━━━━━━━
async function captureAndSend(tabId, jobId = null) {
  const [r] = await browser.tabs.executeScript(tabId, { file: "serialize.js" });

  const headers = { "X-Token": TOKEN };
  if (jobId) headers["X-Job-Id"] = jobId;
  const status = state(tabId).status;
  if (status) headers["X-Http-Status"] = String(status);

  let init;

  // 1. raw <img>의 경우
  if (r.kind === "image") {
    init = {
      method: "POST",
      headers: {
        ...headers,
        "Content-Type": r.contentType,                 // 예: image/jpeg
        "X-Kind": "image",
        "X-Source-Url": encodeURI(r.url),
        "X-Filename": encodeURIComponent(r.filename)
      },
      body: r.bytes                                    // 원본 바이너리 그대로
    };

  // 2. html의 경우 (css/script는 옵션이 꺼져 있으면 undefined → JSON에서 필드 생략)
  } else {
    const { kind, url, html, css, script, meta } = r;
    init = {
      method: "POST",
      headers: { ...headers, "Content-Type": "application/json", "X-Kind": "html" },
      body: JSON.stringify({ kind, url, html, css, script, meta })
    };
  }

  const res = await fetch(`${BROKER}/`, init);
  console.log("sent:", r.kind, res.status);
}

// ━━━━━━━━━━━━━━━━━━━━ JOB RUNNER ━━━━━━━━━━━━━━━━━━━━
const activeJobs = new Map();   // tabId -> job (툴바 버튼으로 "지금 캡처" 신호를 줄 때 사용)

async function runJob(job) {
  let tabId;
  try {
    const tab = await browser.tabs.create({ url: job.url, active: true });
    tabId = tab.id;
    activeJobs.set(tabId, job);
    state(tabId).lastActivity = Date.now();

    await waitLoaded(tabId);

    if (await hasChallenge(tabId)) {
      await sendEvent(job.id, "needs_human", job.url);
      await browser.tabs.update(tabId, { active: true });
      const t = await browser.tabs.get(tabId);
      await browser.windows.update(t.windowId, { drawAttention: true });
      await waitHuman(tabId, job);
      await waitLoaded(tabId);
    }
    if (WAKE_LAZY) await wakeLazy(tabId);

    await captureAndSend(tabId, job.id);
  } catch (e) {
    console.error("job 실패:", e);
    await sendEvent(job.id, "failed", String(e));
  } finally {
    if (tabId !== undefined) { activeJobs.delete(tabId); tabState.delete(tabId); browser.tabs.remove(tabId).catch(() => {}); }
  }
}

// ━━━━━━━━━━━━━━━━━━━━ JOB POLLING (long-poll) ━━━━━━━━━━━━━━━━━━━━
let active = 0;
async function pollLoop() {
  while (true) {
    if (active >= MAX_CONCURRENT) { await sleep(300); continue; }
    try {
      const res = await fetch(`${BROKER}/next-job`, { headers: { "X-Token": TOKEN } });
      if (res.status === 204) continue;
      if (res.status !== 200) { await sleep(3000); continue; }
      const job = await res.json();
      active++;
      runJob(job).finally(() => active--);
    } catch { await sleep(3000); }   // broker 미접속
  }
}
pollLoop();

// ━━━━━━━━━━━━━━━━━━━━ MANUAL TRIGGER (툴바 버튼) ━━━━━━━━━━━━━━━━━━━━
browser.browserAction.onClicked.addListener(async (tab) => {
  const job = activeJobs.get(tab.id);
  if (job) job.force = true;          // 사람 개입 대기 중이면 "지금 캡처"
  else await captureAndSend(tab.id);  // 일반 수동 캡처 (job 없음 → broker가 파일로 저장만 함)
});
