// serialize.js — broker_client.js의 browser.tabs.executeScript({ file })로 주입되는 content script.
// 마지막 표현식이 Promise이므로 executeScript는 resolve된 값을 반환한다.

/* 작업 메모
 * 확장 지점 (기능 추가 시 아래 배열에 함수만 추가하면 된다)
 *   EXTRACTORS         : html에서 제거하고 css/script 필드로 옮길 노드 규칙
 *   ANNOTATORS         : 요소에 속성을 덧붙이는 함수  (el, info, scope) => { attr: value } | null
 *   META_PROVIDERS_*   : meta 필드를 만드는 함수      (cap) => { field: value }
 *   VISIBILITY_CHECKS  : 가시성 판정 사유 목록
 *
 * 반환 format (외부 경계: broker_client.js 가 이 값을 그대로 broker 로 보낸다)
 *   html  : { kind: "html",  contentType, url, html, [css], [script], meta }
 *   image : { kind: "image", contentType, url, filename, bytes_b64, meta }
 *
 * 선언 순서가 실행 순서를 강제한다(const 화살표 함수는 TDZ). => 레지스트리는 항목 함수 뒤에 두고, 구역 라벨로 보완
 */

(async () => {

// ======================== Constants ========================
const CONFIG = {
    include:            { css: false, script: false },  // html 종류일 때 css / script 필드 포함 여부
    selectionMaxLength: 4000,
    keepComments:       false,                          // 주석은 노이즈로 보고 기본 제거
    collapseWhitespace: true,                           // white-space: pre 계열이 아닌 곳의 공백 연속을 1칸으로
    lazyImgAttrs:       ["data-src", "data-lazy-src", "data-original", "data-lazy", "data-srcset", "data-lazy-srcset"],
};
const REDACTED = "[REDACTED]";

const NodeType = {
    ELEMENT: 1,
    TEXT:    3,
    COMMENT: 8
};  // Node.* 상수 대신 리터럴 집합으로 고정

const VOID_TAGS            = new Set(["area", "base", "br", "col", "embed", "frame", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"]);
const PRESERVE_LEADING_NL  = new Set(["pre", "textarea", "listing"]);   // 파서가 첫 개행을 버리므로 보정
const NON_RENDERED_TAGS    = new Set(["head", "title", "meta", "link", "base", "style", "script", "noscript", "template", "area", "param", "track", "datalist"]);  // head 전체가 hidden 처리되는 것을 방지
const NO_VALUE_INPUTS      = new Set(["checkbox", "radio", "hidden", "button", "submit", "reset", "image", "file"]);
const URL_ATTRS            = ["href", "src", "action", "poster", "formaction", "cite"];
const SR_ONLY_MAX_SIZE_PX  = 1;



// ======================== Module API ========================
// 선언 순서 제약으로 파일 맨 아래(ENTRY)에서 호출한다. 읽는 순서: Entry -> Html Document / Image Document -> 나머지



// ──────────────── Common Helpers ────────────────
const runSafely       = (fn, fallback) => { try { return fn(); } catch { return fallback; } };
const getView         = (el) => el.ownerDocument.defaultView || window;
const getShadowRoot   = (el) => el.openOrClosedShadowRoot || el.shadowRoot || null;    // Firefox 전용 API로 closed까지 접근
const toAbsoluteUrl   = (raw, base) => runSafely(() => new URL(raw, base).href, null);
const escapeText      = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const escapeAttr      = (s) => s.replace(/&/g, "&amp;").replace(/"/g, "&quot;");



// ──────────────── Sensitive Masking ────────────────
function isSensitive(el){ // password 정보인가? (password, cc-*, one-time-code)
    const tag = el.localName;
    if (tag !== "input" && tag !== "textarea" && tag !== "select") return false;
    if (el.type === "password") return true;
    const tokens = (el.getAttribute("autocomplete") || "").toLowerCase().split(/\s+/);
    return tokens.some((t) => t.startsWith("cc-") || t === "one-time-code");
}

function redactAttrs(el, attrs){
    if (!isSensitive(el)) return;
    for(const a of attrs){
        if ((a[0] === "value" || a[0] === "data-live-value") && a[1]) a[1] = REDACTED;
    }
}



// ──────────────── Visibility ────────────────
function isContentSkipped(el, { style, parentStyle }){
    const cv = parentStyle && parentStyle.contentVisibility;
    if (cv === "hidden") return true;
    return cv === "auto" && style.display !== "contents" && el.checkVisibility?.({ contentVisibilityAuto: true }) === false;
}

function isInClosedDetails(el){
    const p = el.parentElement;
    if (!p || p.localName !== "details" || p.open) return false;
    return el !== Array.from(p.children).find((c) => c.localName === "summary");
}

// 문서 좌표 기준으로 음수 영역(스크롤로도 도달 불가)에 있는 경우. fixed 요소는 스크롤 보정 없음
function isOffscreen(el, { style, view }){
    const r = el.getBoundingClientRect();
    if (!r.width && !r.height) return false;
    const sx = style.position === "fixed" ? 0 : view.scrollX;
    const sy = style.position === "fixed" ? 0 : view.scrollY;
    return r.right + sx <= 0 || r.bottom + sy <= 0;
}

function isSrOnly(el, { style: s }){
    if (s.position !== "absolute" && s.position !== "fixed") return false;
    if (!(parseFloat(s.width) <= SR_ONLY_MAX_SIZE_PX && parseFloat(s.height) <= SR_ONLY_MAX_SIZE_PX)) return false;
    return /^(hidden|clip)$/.test(s.overflowX) || s.clip !== "auto" || s.clipPath !== "none";
}

// [사유, 판정함수] — 순서대로 검사하며 display-none이면 나머지는 의미 없으므로 중단
const VISIBILITY_CHECKS = [
    ["display-none",       (el, { style }) => style.display === "none"],
    ["opacity-0",          (el, { style }) => parseFloat(style.opacity) === 0],
    ["content-visibility", isContentSkipped],
    ["closed-details",     isInClosedDetails],
    ["offscreen",          isOffscreen],
    ["sr-only",            isSrOnly],
];

// 숨김이 "시작되는" 요소에만 표시한다. 하위 요소는 scope(프로토타입 체인)로 상속되어 중복 표시를 피함.
function annotateVisibility(el, info, scope){
    if (scope.hiddenBlocked || NON_RENDERED_TAGS.has(el.localName)) return null;

    const isVHidden        = info.style.visibility === "hidden" || info.style.visibility === "collapse";
    const wasInheritedVHidden = scope.visibilityHidden;
    scope.visibilityHidden = isVHidden;     // visibility는 상속되지만 자식이 visible로 되돌릴 수 있음

    const own = [];
    for(const [name, test] of VISIBILITY_CHECKS){
        if (test(el, info)){
            own.push(name);
            if (name === "display-none") break;
        }
    }
    if (own.length) scope.hiddenBlocked = true;

    const reasons = isVHidden && !wasInheritedVHidden ? ["visibility-hidden", ...own] : own;
    if (!reasons.length) return null;
    return { "data-hidden": reasons.join(" ") };    // 원본 hidden 속성이 있으면 그대로 유지됨
}



// ──────────────── Live State ────────────────
// 원본 value/checked/selected 속성은 건드리지 않고 data-live-* 로 현재 상태를 덧붙인다.
const getLiveValue = (el) => (el.value === "" && el.defaultValue === "" ? null : { "data-live-value": el.value });

function annotateLiveState(el){
    switch(el.localName){

        case "input":
            if (el.type === "checkbox" || el.type === "radio") return { "data-live-checked": String(el.checked) };
            return NO_VALUE_INPUTS.has(el.type) ? null : getLiveValue(el);

        case "textarea":
            return getLiveValue(el);

        case "option": {
            const select = el.closest("select");
            return select && isSensitive(select) ? null : { "data-live-selected": String(el.selected) };
        }

        default:
            return null;    // E-04: 해당 없는 태그는 정상 경로이므로 실패가 아니라 null
    }
}



// ──────────────── URL Normalization ────────────────
// srcset/lazy 가 반영된 실제 로드 URL
function getEffectiveImgUrl(img){
    const cur = img.currentSrc;
    if (cur && !cur.startsWith("data:")) return cur;
    for(const name of CONFIG.lazyImgAttrs){
        let v = img.getAttribute(name);
        if (!v) continue;
        if (name.endsWith("srcset")) v = v.split(",")[0].trim().split(/\s+/)[0];
        const abs = toAbsoluteUrl(v, img.baseURI);
        if (abs) return abs;
    }
    return cur || null;
}

function annotateUrls(el){
    const out   = {};
    const names = el.localName === "object" ? [...URL_ATTRS, "data"] : URL_ATTRS;
    for(const name of names){
        const raw = el.getAttribute(name);
        if (!raw) continue;
        const abs = toAbsoluteUrl(raw, el.baseURI);
        if (abs && abs !== raw){
            // out[`data-abs-${name}`] = abs;   // 별도 속성으로 덧붙이던 방식 (deprecated: 원본 속성을 절대 경로로 덮어씀)
            out[name] = abs;
        }
    }
    if (el.localName === "img"){
        const eff = getEffectiveImgUrl(el);
        // if (eff && eff !== el.getAttribute("src")) out["data-abs-src"] = eff;
        // else delete out["data-abs-src"];     // 마찬가지로 절대경로로 덮어씀
        if (eff && eff !== el.getAttribute("src")) out["src"] = eff;
        else                                       delete out["src"];   // 위 루프에서 이미 넣은 값도 지움: 실제 로드 URL이 원본 src와 같다는 뜻
    }
    return out;
}



// ──────────────── User Context ────────────────
// shadow root / 같은 origin iframe 안쪽까지 내려가 실제 포커스된 요소를 찾는다
function getDeepActiveElement(doc){
    let a = doc.activeElement;
    while(a){
        const sr = getShadowRoot(a);
        if (sr && sr.activeElement){ a = sr.activeElement; continue; }
        if (a.localName === "iframe" && a.contentDocument && a.contentDocument.activeElement){ a = a.contentDocument.activeElement; continue; }
        break;
    }
    return a && a.localName !== "body" && a.localName !== "html" ? a : null;
}

const annotateFocus = (el, { cap }) => (el === cap.focused ? { "data-focused": "true" } : null);

const buildMetaUserContext = () => {
    const sel = String(window.getSelection());
    return {
        selection: sel ? sel.slice(0, CONFIG.selectionMaxLength) : null,
        scroll:    { x: window.scrollX, y: window.scrollY },
        viewport:  { width: window.innerWidth, height: window.innerHeight },
    };
};



// ──────────────── Frames ────────────────
// iframe 본문은 <iframe> 바로 뒤 형제 <template data-iframe-document>에 담는다.
// (iframe 내부는 HTML 파서가 raw text로 취급하므로 자식으로 넣으면 일반 파서가 읽지 못함)

// 접근 가능한 문서이고 body에 요소/텍스트가 없으며, 로딩 대기 중인 src도 없으면 빈 프레임
function isEmptyFrame(el, doc){
    if (!doc) return false;                             // cross-origin은 내용을 알 수 없으므로 빈 프레임으로 보지 않음
    const src = el.getAttribute("src");
    if (src && src !== "about:blank") return false;     // src가 있는데 about:blank면 아직 로딩 중일 수 있음
    const body = doc.body;
    return !body || (body.children.length === 0 && !body.textContent.trim());
}

function annotateFrame(el, { cap }){
    if (el.localName !== "iframe") return null;
    const doc = el.contentDocument;                     // cross-origin / sandbox / 미로딩이면 null
    if (isEmptyFrame(el, doc)) return null;             // index 부여, meta.frames 등록, template 생성 모두 건너뜀
    const index = cap.frames.length;
    cap.frames.push({ src: el.src, access: doc ? "same-origin" : "cross-origin" });
    cap.frameDocs.set(el, { index, doc });
    return { "data-frame-index": String(index) };
}

const buildMetaFrames = (cap) => ({ frames: cap.frames });



// ──────────────── CSS / Script Extraction ────────────────
const getSheetRules = (sheet) => runSafely(() => Array.from(sheet.cssRules, (r) => r.cssText).join("\n"), null);

function getCssOfElement(el){
    const isLink = el.localName === "link";
    const rules  = el.sheet ? getSheetRules(el.sheet) : null;   // CSS-in-JS(insertRule)는 cssRules에만 존재
    const body   = rules ?? (isLink ? "/* unreadable */" : el.textContent);
    return `/* ${isLink ? "link " + el.href : "style"} */\n${body}`;
}

const getScriptOfElement = (el) => (el.src ? `/* script src: ${el.src} */` : `/* script inline */\n${el.textContent}`);

function collectAdopted(root, cap, label){
    if (!CONFIG.include.css) return;
    const sheets = runSafely(() => Array.from(root.adoptedStyleSheets), []);
    for(const s of sheets) cap.css.push(`/* adopted: ${label} */\n${getSheetRules(s) ?? "/* unreadable */"}`);
}

const addCss    = (el, cap) => { if (CONFIG.include.css)    cap.css.push(getCssOfElement(el)); };
const addScript = (el, cap) => { if (CONFIG.include.script) cap.script.push(getScriptOfElement(el)); };

// html에서는 항상 제거. 옵션이 켜져 있으면 css/script 필드로 수집
const EXTRACTORS = [
    { match: (el) => el.localName === "noscript" },
    { match: (el) => el.localName === "style",  extract: addCss },
    { match: (el) => el.localName === "link" && el.relList && el.relList.contains("stylesheet"), extract: addCss },
    { match: (el) => el.localName === "script", extract: addScript },
];



// ──────────────── Registries ────────────────
// 위 구역의 함수들을 모아 조립한다. 순서가 곧 속성 덮어쓰기 순서
const ANNOTATORS = [annotateVisibility, annotateLiveState, annotateUrls, annotateFocus, annotateFrame];



// ──────────────── Meta ────────────────
const buildMetaIdentity = () => ({
    canonical: runSafely(() => document.querySelector('link[rel~="canonical"]').href, "") || null,
    title:     document.title  });
const buildMetaCapture = () => ({ 
    captured_at: new Date().toISOString(), 
    ready_state: document.readyState  });

const META_PROVIDERS_BASE = [buildMetaIdentity, buildMetaCapture];
const META_PROVIDERS_HTML = [...META_PROVIDERS_BASE, buildMetaUserContext, buildMetaFrames];
const buildMeta           = (providers, cap) => Object.assign({}, ...providers.map((p) => p(cap)));



// ──────────────── DOM Serializer ────────────────
function serializeText(node, style){
    let t = node.data;
    if (CONFIG.collapseWhitespace && !/^(pre|break)/.test(style.whiteSpace)) t = t.replace(/[ \t\n\r\f]+/g, " ");
    return escapeText(t);
}

function serializeNode(node, cap, scope, style){
    switch(node.nodeType){
        case NodeType.ELEMENT: return serializeElement(node, cap, scope, style);
        case NodeType.TEXT:    return serializeText(node, style);
        case NodeType.COMMENT: return CONFIG.keepComments ? `<!--${node.data.replace(/--/g, "- -")}-->` : "";
        default:               return "";   // CDATA, processing instruction 등은 html 직렬화 대상이 아님
    }
}

function serializeShadowRoot(root, cap, scope, hostStyle){
    collectAdopted(root, cap, `shadow of <${root.host.localName}>`);
    let inner = "";
    for(const n of root.childNodes) inner += serializeNode(n, cap, scope, hostStyle);
    return `<template data-shadow-root data-mode="${root.mode}">${inner}</template>`;
}

function serializeElement(el, cap, parentScope, parentStyle){
    // 1. 제거 대상 (옵션이 켜져 있으면 css/script 필드로 수집)
    for(const rule of EXTRACTORS){
        if (rule.match(el)){
            if (rule.extract) rule.extract(el, cap);
            return "";
        }
    }

    const tag   = el.localName;
    const view  = getView(el);
    const info  = { style: view.getComputedStyle(el), parentStyle, view, cap };
    const scope = Object.create(parentScope);   // 하위 트리로 상속되는 상태 (annotator가 자유롭게 기록)

    // 2. 원본 속성 + annotator 속성 (이름이 겹치면 annotator 값이 덮어씀)
    const attrs = Array.from(el.attributes, (a) => [a.name, a.value]);
    for(const annotate of ANNOTATORS){
        const extra = annotate(el, info, scope);
        if (!extra) continue;
        for(const k in extra){
            const index = attrs.findIndex((a) => a[0] === k);
            if (index >= 0) attrs[index][1] = extra[k];     // 이미 있으면 덮어씀
            else            attrs.push([k, extra[k]]);      // 없으면 추가
        }
    }
    redactAttrs(el, attrs);

    const open = `<${tag}${attrs.map(([k, v]) => ` ${k}="${escapeAttr(v)}"`).join("")}>`;
    if (VOID_TAGS.has(tag)) return open;

    // 3. 자식 직렬화
    let inner = "";
    const root = getShadowRoot(el);
    if (root) inner += serializeShadowRoot(root, cap, scope, info.style);
    if (tag === "textarea" && isSensitive(el)){
        inner += el.textContent ? REDACTED : "";
    }
    else if (tag !== "template"){   // 페이지 원본 <template>은 비렌더 노이즈라 내용 생략
        for(const n of el.childNodes) inner += serializeNode(n, cap, scope, info.style);
    }
    if (PRESERVE_LEADING_NL.has(tag) && inner.startsWith("\n")) inner = "\n" + inner;

    let out = `${open}${inner}</${tag}>`;

    // 4. iframe 본문은 바로 뒤 형제 template 으로 붙임
    const frameDoc = cap.frameDocs.get(el);
    if (frameDoc && frameDoc.doc && frameDoc.doc.documentElement){
        collectAdopted(frameDoc.doc, cap, `iframe ${el.src}`);
        out += `<template data-iframe-document data-frame-index="${frameDoc.index}">${serializeElement(frameDoc.doc.documentElement, cap, scope, null)}</template>`;
    }
    return out;
}



// ======================== Html Document ========================
function captureHtml(){
    const cap = { css: [], script: [], frames: [], frameDocs: new Map(), focused: getDeepActiveElement(document) };
    collectAdopted(document, cap, "document");

    const rootScope = { hiddenBlocked: false, visibilityHidden: false };
    const html      = "<!DOCTYPE html>\n" + serializeElement(document.documentElement, cap, rootScope, null);

    const result = { kind: "html", contentType: "text/html", url: location.href, html };
    if (CONFIG.include.css)    result.css    = cap.css.join("\n\n");
    if (CONFIG.include.script) result.script = cap.script.join("\n\n");
    result.meta = buildMeta(META_PROVIDERS_HTML, cap);
    return result;
}



// ======================== Image Document ========================
function getFilename(url, contentType){
    const u    = new URL(url);
    const last = u.protocol === "data:" || u.protocol === "blob:" ? "" : u.pathname.split("/").pop();
    const name = runSafely(() => decodeURIComponent(last), last);
    if (name) return name;
    const sub = contentType.split("/")[1].split("+")[0];
    return `image.${sub === "jpeg" ? "jpg" : sub}`;
}

const blobToBase64 = (blob) => new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload  = () => resolve(r.result.slice(r.result.indexOf(",") + 1));   // "data:...;base64," 접두어 제거
    r.onerror = () => reject(r.error);
    r.readAsDataURL(blob);
});

async function captureImage(){
    const res = await fetch(location.href, { cache: "force-cache" });
    if (!res.ok) throw new Error(`image fetch failed: ${res.status}`);     // E-02: 잘못된 값(status)을 메시지에 포함
    const contentType = document.contentType;
    return {
        kind:        "image",
        contentType,
        url:         location.href,
        filename:    getFilename(location.href, contentType),
        bytes_b64:   await blobToBase64(await res.blob()),   // bytes → bytes_b64
        meta:        buildMeta(META_PROVIDERS_BASE, {}),
    };
}



// ======================== Entry ========================
// 마지막 표현식이 Promise여야 executeScript가 resolve된 값을 반환한다.
return document.contentType.startsWith("image/") ? captureImage() : captureHtml();

})();
