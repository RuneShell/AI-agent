// serialize.js — client.js의 browser.tabs.executeScript({ file })로 주입되는 content script.
// 마지막 표현식이 Promise이므로 executeScript는 resolve된 값을 반환한다.
//
// 확장 지점 (기능 추가 시 아래 배열에 함수만 추가하면 된다)
//   EXTRACTORS      : html에서 제거하고 css/script 필드로 옮길 노드 규칙
//   ANNOTATORS      : 요소에 속성을 덧붙이는 함수  (el, info, scope) => { attr: value } | null
//   META_PROVIDERS  : meta 필드를 만드는 함수      (cap) => { field: value }
//   VISIBILITY_CHECKS: 가시성 판정 사유 목록

(async () => {

// ━━━━━━━━━━━━━━━━━━━━ CONFIG ━━━━━━━━━━━━━━━━━━━━
const CONFIG = {
  include: { css: false, script: false },   // html 종류일 때 css / script 필드 포함 여부
  selectionMaxLength: 4000,
  keepComments: false,                      // 주석은 노이즈로 보고 기본 제거
  collapseWhitespace: true,                 // white-space: pre 계열이 아닌 곳의 공백 연속을 1칸으로
  lazyImgAttrs: ["data-src", "data-lazy-src", "data-original", "data-lazy", "data-srcset", "data-lazy-srcset"],
};
const REDACTED = "[REDACTED]";

// ━━━━━━━━━━━━━━━━━━━━ UTILS ━━━━━━━━━━━━━━━━━━━━
const safe = (fn, fallback) => { try { return fn(); } catch { return fallback; } };
const viewOf = (el) => el.ownerDocument.defaultView || window;
const openShadow = (el) => el.openOrClosedShadowRoot || el.shadowRoot || null;   // Firefox 전용 API로 closed까지 접근
const toAbs = (raw, base) => safe(() => new URL(raw, base).href, null);
const escText = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const escAttr = (s) => s.replace(/&/g, "&amp;").replace(/"/g, "&quot;");
const VOID_TAGS = new Set(["area", "base", "br", "col", "embed", "frame", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"]);
const PRESERVE_LEADING_NL = new Set(["pre", "textarea", "listing"]);   // 파서가 첫 개행을 버리므로 보정

// ━━━━━━━━━━━━━━━━━━━━ SENSITIVE MASKING ━━━━━━━━━━━━━━━━━━━━
function isSensitive(el) { // password 정보인가? (password, cc-*, one-time-code)
  const tag = el.localName;
  if (tag !== "input" && tag !== "textarea" && tag !== "select") return false;
  if (el.type === "password") return true;
  const tokens = (el.getAttribute("autocomplete") || "").toLowerCase().split(/\s+/);
  return tokens.some((t) => t.startsWith("cc-") || t === "one-time-code");
}

function redactAttrs(el, attrs) {
  if (!isSensitive(el)) return;
  for (const a of attrs) if ((a[0] === "value" || a[0] === "data-live-value") && a[1]) a[1] = REDACTED;
}

// ━━━━━━━━━━━━━━━━━━━━ VISIBILITY ━━━━━━━━━━━━━━━━━━━━
// 렌더되지 않는 것이 기본인 태그는 판정 제외 (head 전체가 hidden 처리되는 것을 방지)
const NON_RENDERED_TAGS = new Set(["head", "title", "meta", "link", "base", "style", "script", "noscript", "template", "area", "param", "track", "datalist"]);

function isContentSkipped(el, { style, parentStyle }) {
  const cv = parentStyle && parentStyle.contentVisibility;
  if (cv === "hidden") return true;
  return cv === "auto" && style.display !== "contents" && el.checkVisibility?.({ contentVisibilityAuto: true }) === false;
}

function isInClosedDetails(el) {
  const p = el.parentElement;
  if (!p || p.localName !== "details" || p.open) return false;
  return el !== Array.from(p.children).find((c) => c.localName === "summary");
}

// 문서 좌표 기준으로 음수 영역(스크롤로도 도달 불가)에 있는 경우. fixed 요소는 스크롤 보정 없음
function isOffscreen(el, { style, view }) {
  const r = el.getBoundingClientRect();
  if (!r.width && !r.height) return false;
  const sx = style.position === "fixed" ? 0 : view.scrollX;
  const sy = style.position === "fixed" ? 0 : view.scrollY;
  return r.right + sx <= 0 || r.bottom + sy <= 0;
}

function isSrOnly(el, { style: s }) {
  if (s.position !== "absolute" && s.position !== "fixed") return false;
  if (!(parseFloat(s.width) <= 1 && parseFloat(s.height) <= 1)) return false;
  return /^(hidden|clip)$/.test(s.overflowX) || s.clip !== "auto" || s.clipPath !== "none";
}

// [사유, 판정함수] — 순서대로 검사하며 display-none이면 나머지는 의미 없으므로 중단
const VISIBILITY_CHECKS = [
  ["display-none", (el, { style }) => style.display === "none"],
  ["opacity-0", (el, { style }) => parseFloat(style.opacity) === 0],
  ["content-visibility", isContentSkipped],
  ["closed-details", isInClosedDetails],
  ["offscreen", isOffscreen],
  ["sr-only", isSrOnly],
];

// 숨김이 "시작되는" 요소에만 표시한다. 하위 요소는 scope(프로토타입 체인)로 상속되어 중복 표시를 피함.
function annotateVisibility(el, info, scope) {
  if (scope.hiddenBlocked || NON_RENDERED_TAGS.has(el.localName)) return null;

  const vHidden = info.style.visibility === "hidden" || info.style.visibility === "collapse";
  const inheritedVHidden = scope.visibilityHidden;
  scope.visibilityHidden = vHidden;   // visibility는 상속되지만 자식이 visible로 되돌릴 수 있음

  const own = [];
  for (const [name, test] of VISIBILITY_CHECKS) {
    if (test(el, info)) {
      own.push(name);
      if (name === "display-none") break;
    }
  }
  if (own.length) scope.hiddenBlocked = true;

  const reasons = vHidden && !inheritedVHidden ? ["visibility-hidden", ...own] : own;
  if (!reasons.length) return null;
  return { "data-hidden": reasons.join(" ") };   // 원본 hidden 속성이 있으면 그대로 유지됨
}

// ━━━━━━━━━━━━━━━━━━━━ LIVE STATE ━━━━━━━━━━━━━━━━━━━━
// 원본 value/checked/selected 속성은 건드리지 않고 data-live-* 로 현재 상태를 덧붙인다.
const NO_VALUE_INPUTS = new Set(["checkbox", "radio", "hidden", "button", "submit", "reset", "image", "file"]);
const liveValue = (el) => (el.value === "" && el.defaultValue === "" ? null : { "data-live-value": el.value });

function annotateLiveState(el) {
  switch (el.localName) {
    case "input":
      if (el.type === "checkbox" || el.type === "radio") return { "data-live-checked": String(el.checked) };
      return NO_VALUE_INPUTS.has(el.type) ? null : liveValue(el);
    case "textarea":
      return liveValue(el);
    case "option": {
      const select = el.closest("select");
      return select && isSensitive(select) ? null : { "data-live-selected": String(el.selected) };
    }
    default:
      return null;
  }
}

// ━━━━━━━━━━━━━━━━━━━━ URL NORMALIZATION ━━━━━━━━━━━━━━━━━━━━
const URL_ATTRS = ["href", "src", "action", "poster", "formaction", "cite"];

// srcset/lazy 가 반영된 실제 로드 URL
function effectiveImgUrl(img) {
  const cur = img.currentSrc;
  if (cur && !cur.startsWith("data:")) return cur;
  for (const name of CONFIG.lazyImgAttrs) {
    let v = img.getAttribute(name);
    if (!v) continue;
    if (name.endsWith("srcset")) v = v.split(",")[0].trim().split(/\s+/)[0];
    const abs = toAbs(v, img.baseURI);
    if (abs) return abs;
  }
  return cur || null;
}

function annotateUrls(el) {
  const out = {};
  const names = el.localName === "object" ? [...URL_ATTRS, "data"] : URL_ATTRS;
  for (const name of names) {
    const raw = el.getAttribute(name);
    if (!raw) continue;
    const abs = toAbs(raw, el.baseURI);
    if (abs && abs !== raw){
      // else out[`data-abs-${name}`] = abs;   // 이미 절대 URL이면 추가하지 않음
      out[`${name}`] = abs; // 그냥 절대 경로로 덮어씌움.
    }
  }
  if (el.localName === "img") {
    const eff = effectiveImgUrl(el);
    // if (eff && eff !== el.getAttribute("src")) out["data-abs-src"] = eff;
    // else delete out["data-abs-src"]; // 마찬가지로 절대경로로 덮어씌움.
    if (eff && eff !== el.getAttribute("src")) out["src"] = eff;
    else delete out["src"];
  }
  return out;
}

// ━━━━━━━━━━━━━━━━━━━━ USER CONTEXT ━━━━━━━━━━━━━━━━━━━━
// shadow root / 같은 origin iframe 안쪽까지 내려가 실제 포커스된 요소를 찾는다
function deepActiveElement(doc) {
  let a = doc.activeElement;
  while (a) {
    const sr = openShadow(a);
    if (sr && sr.activeElement) { a = sr.activeElement; continue; }
    if (a.localName === "iframe" && a.contentDocument && a.contentDocument.activeElement) { a = a.contentDocument.activeElement; continue; }
    break;
  }
  return a && a.localName !== "body" && a.localName !== "html" ? a : null;
}

const annotateFocus = (el, { cap }) => (el === cap.focused ? { "data-focused": "true" } : null);

const metaUserContext = () => {
  const sel = String(window.getSelection());
  return {
    selection: sel ? sel.slice(0, CONFIG.selectionMaxLength) : null,
    scroll: { x: window.scrollX, y: window.scrollY },
    viewport: { width: window.innerWidth, height: window.innerHeight },
  };
};

// ━━━━━━━━━━━━━━━━━━━━ FRAMES ━━━━━━━━━━━━━━━━━━━━
// iframe 본문은 <iframe> 바로 뒤 형제 <template data-iframe-document>에 담는다.
// (iframe 내부는 HTML 파서가 raw text로 취급하므로 자식으로 넣으면 일반 파서가 읽지 못함)

// 접근 가능한 문서이고 body에 요소/텍스트가 없으며, 로딩 대기 중인 src도 없으면 빈 프레임
function isEmptyFrame(el, doc) {
  if (!doc) return false;                                   // cross-origin은 내용을 알 수 없으므로 빈 프레임으로 보지 않음
  const src = el.getAttribute("src");
  if (src && src !== "about:blank") return false;           // src가 있는데 about:blank면 아직 로딩 중일 수 있음
  const body = doc.body;
  return !body || (body.children.length === 0 && !body.textContent.trim());
}

function annotateFrame(el, { cap }) {
  if (el.localName !== "iframe") return null;
  const doc = el.contentDocument;   // cross-origin / sandbox / 미로딩이면 null
  if (isEmptyFrame(el, doc)) return null;   // index 부여, meta.frames 등록, template 생성 모두 건너뜀
  const index = cap.frames.length;
  cap.frames.push({ src: el.src, access: doc ? "same-origin" : "cross-origin" });
  cap.frameDocs.set(el, { index, doc });
  return { "data-frame-index": String(index) };
}

const metaFrames = (cap) => ({ frames: cap.frames });

// ━━━━━━━━━━━━━━━━━━━━ CSS / SCRIPT EXTRACTION ━━━━━━━━━━━━━━━━━━━━
const sheetRules = (sheet) => safe(() => Array.from(sheet.cssRules, (r) => r.cssText).join("\n"), null);

function cssOfElement(el) {
  const isLink = el.localName === "link";
  const rules = el.sheet ? sheetRules(el.sheet) : null;   // CSS-in-JS(insertRule)는 cssRules에만 존재
  const body = rules ?? (isLink ? "/* unreadable */" : el.textContent);
  return `/* ${isLink ? "link " + el.href : "style"} */\n${body}`;
}

const scriptOfElement = (el) => (el.src ? `/* script src: ${el.src} */` : `/* script inline */\n${el.textContent}`);

function collectAdopted(root, cap, label) {
  if (!CONFIG.include.css) return;
  const sheets = safe(() => Array.from(root.adoptedStyleSheets), []);
  for (const s of sheets) cap.css.push(`/* adopted: ${label} */\n${sheetRules(s) ?? "/* unreadable */"}`);
}

const addCss = (el, cap) => { if (CONFIG.include.css) cap.css.push(cssOfElement(el)); };
const addScript = (el, cap) => { if (CONFIG.include.script) cap.script.push(scriptOfElement(el)); };

// html에서는 항상 제거. 옵션이 켜져 있으면 css/script 필드로 수집
const EXTRACTORS = [
  { match: (el) => el.localName === "noscript" },
  { match: (el) => el.localName === "style", extract: addCss },
  { match: (el) => el.localName === "link" && el.relList && el.relList.contains("stylesheet"), extract: addCss },
  { match: (el) => el.localName === "script", extract: addScript },
];

// ━━━━━━━━━━━━━━━━━━━━ REGISTRIES ━━━━━━━━━━━━━━━━━━━━
const ANNOTATORS = [annotateVisibility, annotateLiveState, annotateUrls, annotateFocus, annotateFrame];

// ━━━━━━━━━━━━━━━━━━━━ META ━━━━━━━━━━━━━━━━━━━━
const metaIdentity = () => ({
  url: location.href,
  canonical: safe(() => document.querySelector('link[rel~="canonical"]').href, "") || null,
  title: document.title,
});
const metaCapture = () => ({ captured_at: new Date().toISOString(), ready_state: document.readyState });

const META_PROVIDERS_BASE = [metaIdentity, metaCapture];
const META_PROVIDERS_HTML = [...META_PROVIDERS_BASE, metaUserContext, metaFrames];
const buildMeta = (providers, cap) => Object.assign({}, ...providers.map((p) => p(cap)));

// ━━━━━━━━━━━━━━━━━━━━ DOM SERIALIZER ━━━━━━━━━━━━━━━━━━━━
function serializeText(node, style) {
  let t = node.data;
  if (CONFIG.collapseWhitespace && !/^(pre|break)/.test(style.whiteSpace)) t = t.replace(/[ \t\n\r\f]+/g, " ");
  return escText(t);
}

function serializeNode(node, cap, scope, style) {
  switch (node.nodeType) {
    case 1: return serializeElement(node, cap, scope, style);
    case 3: return serializeText(node, style);
    case 8: return CONFIG.keepComments ? `<!--${node.data.replace(/--/g, "- -")}-->` : "";
    default: return "";
  }
}

function serializeShadowRoot(root, cap, scope, hostStyle) {
  collectAdopted(root, cap, `shadow of <${root.host.localName}>`);
  let inner = "";
  for (const n of root.childNodes) inner += serializeNode(n, cap, scope, hostStyle);
  return `<template data-shadow-root data-mode="${root.mode}">${inner}</template>`;
}

function serializeElement(el, cap, parentScope, parentStyle) {
  for (const rule of EXTRACTORS) {
    if (rule.match(el)) { if (rule.extract) rule.extract(el, cap); return ""; }
  }

  const tag = el.localName;
  const view = viewOf(el);
  const info = { style: view.getComputedStyle(el), parentStyle, view, cap };
  const scope = Object.create(parentScope);   // 하위 트리로 상속되는 상태 (annotator가 자유롭게 기록)

  // 원본 속성 + annotator 속성 (이름이 겹치면 원본 우선)
  const attrs = Array.from(el.attributes, (a) => [a.name, a.value]);
  const seen = new Set(attrs.map((a) => a[0]));
  for (const annotate of ANNOTATORS) {
    const extra = annotate(el, info, scope);
    if (!extra) continue;
    for (const k in extra){
      const index = attrs.findIndex((a) => a[0] === k);
      if(index >= 0) attrs[index][1] = extra[k]; // 이미 있으면 덮어씀
      else           attrs.push([k, extra[k]]) // 없으면 추가
    }
  }
  redactAttrs(el, attrs);

  const open = `<${tag}${attrs.map(([k, v]) => ` ${k}="${escAttr(v)}"`).join("")}>`;
  if (VOID_TAGS.has(tag)) return open;

  let inner = "";
  const root = openShadow(el);
  if (root) inner += serializeShadowRoot(root, cap, scope, info.style);
  if (tag === "textarea" && isSensitive(el)) inner += el.textContent ? REDACTED : "";
  else if (tag !== "template") {   // 페이지 원본 <template>은 비렌더 노이즈라 내용 생략
    for (const n of el.childNodes) inner += serializeNode(n, cap, scope, info.style);
  }
  if (PRESERVE_LEADING_NL.has(tag) && inner.startsWith("\n")) inner = "\n" + inner;

  let out = `${open}${inner}</${tag}>`;

  const fd = cap.frameDocs.get(el);
  if (fd && fd.doc && fd.doc.documentElement) {
    collectAdopted(fd.doc, cap, `iframe ${el.src}`);
    out += `<template data-iframe-document data-frame-index="${fd.index}">${serializeElement(fd.doc.documentElement, cap, scope, null)}</template>`;
  }
  return out;
}

// ━━━━━━━━━━━━━━━━━━━━ HTML DOCUMENT ━━━━━━━━━━━━━━━━━━━━
function captureHtml() {
  const cap = { css: [], script: [], frames: [], frameDocs: new Map(), focused: deepActiveElement(document) };
  collectAdopted(document, cap, "document");

  const rootScope = { hiddenBlocked: false, visibilityHidden: false };
  const html = "<!DOCTYPE html>\n" + serializeElement(document.documentElement, cap, rootScope, null);

  const result = { kind: "html", contentType: "text/html", url: location.href, html };
  if (CONFIG.include.css) result.css = cap.css.join("\n\n");
  if (CONFIG.include.script) result.script = cap.script.join("\n\n");
  result.meta = buildMeta(META_PROVIDERS_HTML, cap);
  return result;
}

// ━━━━━━━━━━━━━━━━━━━━ IMAGE DOCUMENT ━━━━━━━━━━━━━━━━━━━━
function filenameOf(url, contentType) {
  const u = new URL(url);
  const last = u.protocol === "data:" || u.protocol === "blob:" ? "" : u.pathname.split("/").pop();
  const name = safe(() => decodeURIComponent(last), last);
  if (name) return name;
  const sub = contentType.split("/")[1].split("+")[0];
  return `image.${sub === "jpeg" ? "jpg" : sub}`;
}

async function captureImage() {
  const res = await fetch(location.href, { cache: "force-cache" });
  if (!res.ok) throw new Error(`image fetch failed: ${res.status}`);
  const bytes = await res.arrayBuffer();
  const contentType = document.contentType;
  return {
    kind: "image",
    contentType,
    url: location.href,
    filename: filenameOf(location.href, contentType),
    bytes,
    meta: buildMeta(META_PROVIDERS_BASE, {}),
  };
}

// ━━━━━━━━━━━━━━━━━━━━ ENTRY ━━━━━━━━━━━━━━━━━━━━
return document.contentType.startsWith("image/") ? captureImage() : captureHtml();

})();
