// ──────────────── CONFIG ────────────────
// server connection
const BROKER_ADDRESS = "http://127.0.0.1:11101";
const GET_ENDPOINT_PATH = "jobs/next";
const POST_ENDPOINT_PATH = "jobs/report";
const AUTH_TOKEN = "tool_web";            // broker.py의 TOKEN과 동일해야 함

// job runner
const MAX_CONCURRENT_JOBS = 1; // job마다 tab이 별도로 열림.
const WAKE_LAZY_CONTENT = true; // page를 끝까지 스크롤해서 lazy-loaded content를 깨운 뒤 capture


const LOAD_MS = {
    // server connection
    POLL_INTERVAL: 500,
    BORKER_NOT_REACHABLE: 3000,
    WAIT_ACTIVE_JOB: 500,

    // load tab page
    WAIT_TAB_TIMEOUT: 20000,
    WAIT_DOM_QUIET: 500,
}