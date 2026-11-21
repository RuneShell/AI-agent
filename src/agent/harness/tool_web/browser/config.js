// ──────────────── CONFIG ────────────────
// server connection
const BROKER_ADDRESS = "http://127.0.0.1:11101";
const GET_ENDPOINT_PATH = "jobs/next";
const POST_ENDPOINT_PATH = "jobs/report";
const AUTH_TOKEN = "tool_web";            // broker.py의 TOKEN과 동일해야 함

// job runner
const MAX_CONCURRENT_JOBS = 1; // job마다 tab이 별도로 열림.
const WAKE_LAZY_CONTENT = true; // page를 끝까지 스크롤해서 lazy-loaded content를 깨운 뒤 capture

// detect CAPTCHA heuristically
const CHALLENGE_RE = /just a moment|attention required|verify you are human|are you human|access denied/i;
const CHALLENGE_SELECTOR = 'iframe[src*="challenges.cloudflare.com"], iframe[src*="recaptcha"], iframe[src*="hcaptcha"], #challenge-form, .g-recaptcha, .h-captcha, .cf-turnstile';


const WAIT_MS = {
    // server connection
    POLL_INTERVAL: 1000,
    BROKER_NOT_REACHABLE: 3000,
    ACTIVE_CONCURRENT_JOB: 500,

    // load tab page
    NETWORK_QUIET: 500,
    NETWORK_TIMEOUT: 20000,
    CHECK_TAB_LOAD: 200,
    DOM_QUIET: 500,
    DOM_TIMEOUT: 10000,
    
    // wait human (captcha)
    HUMAN_TIMEOUT: 30 * 60 * 1000,
    CHECK_CAPTCHA: 5000,
}