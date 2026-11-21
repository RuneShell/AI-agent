
class Tab{
    inflight = new Set();
    lastActivity = Date.now();
    httpStatus = null;


    constructor(id){
        this.id = id;
    }
    onRequestStart(requestId){ this.inflight.add(requestId);    this.lastActivity = Date.now(); }
    onRequestEnd(requestId){   this.inflight.delete(requestId); this.lastActivity = Date.now(); }

    async _runScript(code){
        // 이 파일(background 코드)과 tab은 서로 다른 JS 환경에서 동작한다. 
        // 따라서 tab의 `document`, `window`에 접근하기 위해 코드를 문자열로 삽입해서 실행한다.
        const [result] = (await browser.tabs.executeScript(this.id, {code}))
        return result;
    }

    // ────────────────  DOM CAPTURE ────────────────
    async captureDOM(){
        const [result] = await browser.tabs.executeScript(this.id, {file: "serialize.js"});
        return { httpStatus: this.httpStatus, ...result};
    }

    // ──────────────── WAIT & LAZY LOAD ────────────────
    async waitLoaded(){
        const start = Date.now();

        // condition 1: network 요청이 잠잠해졌는가? (HTML/CSS/JS 리소스 로드 완료 && 이동 전 빈 페이지의 complete제외 && JS의 fetch/XHR 요청 없음 && 추가적인 요청 없이 500ms 유지)
        const isNetworkSettled = async () => {
            const tab = await browser.tabs.get(this.id);
            return tab.status === "complete"
                && tab.url !== "about:blank"
                && this.inflight.size === 0
                && Date.now() - this.lastActivity >= WAIT_MS.NETWORK_QUIET;
        };
        
        while (!(await isNetworkSettled())){
            // timeout 초과 시 강제 반환
            if (Date.now() - start >= WAIT_MS.NETWORK_TIMEOUT) break;
            await sleep(WAIT_MS.CHECK_TAB_LOAD); // 200ms마다 체크
        }

        // condition 2: 요청이 잠잠해졌다면, 링크가 정상(http:// 또는 https://)인가?
        const tabAfterLoad = await browser.tabs.get(this.id);
        if (!/^https?:/.test(tabAfterLoad.url)) throw new Error(`load failed: ${tabAfterLoad.url}`);   // about:neterror 등

        // condition 3: DOM 변경이 더 이상 없는가?
        await this._runScript(`new Promise((resolve) => {
            let timeout;
            const done = () => { mutationObserver.disconnect(); resolve(true); };

            const mutationObserver = new MutationObserver(() => { clearTimeout(timeout); timeout = setTimeout(done, ${WAIT_MS.DOM_QUIET}); });  // DOM 변화가 감지될 때마다 timeout을 초기화
            mutationObserver.observe(document, { subtree: true, childList: true, characterData: true, attributes: false });  // attributes(class, style 등) 변화는 무시. DOM 구조/텍스트 변화만 감지

            timeout = setTimeout(done, ${WAIT_MS.DOM_QUIET}); // DOM 변화가 없으면(mutationObserver 미호출 시) 500ms 후에 종료
            setTimeout(done, ${WAIT_MS.DOM_TIMEOUT}); // DOM 변화가 계속되더라도 10초 후에는 종료
        })`);
    }

    async wakeLazyContent(){
        /* scroll page from start to end to trigger lazy loading */
        await this._runScript(`(async () => {
            const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
            const end = Math.min(document.documentElement.scrollHeight, innerHeight * 20);
            for (let y = 0; y < end; y += innerHeight) { scrollTo(0, y); await sleep(150); }
            scrollTo(0, 0);
        })()`);
        await this.waitLoaded(); // wait again.
    }

    // ──────────────── CONDITIONAL HELPERS ────────────────
    // 정확한 감지는 불가능 — 제목/마커 요소 기반 휴리스틱. 실행 실패(페이지 이동 중 등)는 "아직 챌린지"로 간주
    async hasChallenge(){
        try {
            return await this._runScript(tabId, `(() => {
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


}




class TabManager{

    // webRequest filter (특정 type의 content만 추적; type=null이면 모든 것이 target인데, `websocket`을 추적하면 연결이 계속되서, 페이지 로드 완료를 탐지할 수 없음.)
    static NET_FILTER = { urls: ["<all_urls>"],
        types: ["main_frame", "sub_frame", "script", "stylesheet", "image", "imageset", "xmlhttprequest", "font", "media", "object", "other"]};
    
    #tabs = new Map();

    constructor(){
        // webRequest Listener 등록
        const on = (event, handler) => event.addListener((d) => {
            const tab = this.#tabs.get(d.tabId);   // tabId -1(탭 밖 요청)이나 추적 안 하는 탭은 여기서 걸러짐
            if (tab)    handler(tab, d);
        }, TabManager.NET_FILTER);

        on(browser.webRequest.onBeforeRequest, (tab, d) => tab.onRequestStart(d.requestId));
        on(browser.webRequest.onCompleted, (tab, d) => {
            tab.onRequestEnd(d.requestId);
            if (d.type === "main_frame") tab.httpStatus = d.statusCode;
        });
        on(browser.webRequest.onErrorOccurred, (tab, d) => tab.onRequestEnd(d.requestId));
    }
        
    // ──────────────── TAB MANAGEMENT ────────────────
    async open(url){
        // about:blank로 미리 탭을 열어둠으로써, main_frame을 놓치지 않는다.
        const { id } = await browser.tabs.create({url: "about:blank", active: true});

        const tab = new Tab(id);
        this.#tabs.set(id, tab);
        // 실제 url로 이동
        await browser.tabs.update(id, {url});
        return tab;
    }
    async close(tabId){
        this.#tabs.delete(tabId);
        await browser.tabs.remove(tabId);
    }

    get(tabId){
        return this.#tabs.get(tabId);
    }
}
