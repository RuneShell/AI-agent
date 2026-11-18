// 통신 방식을 http -> websocker으로 바꾸기?


// ──────────────── CONFIG ────────────────
const BROKER_ADDRESS = "http://127.0.0.1:11101";
const GET_ENDPOINT_PATH = "jobs/next";
const POST_ENDPOINT_PATH = "jobs/report";
const AUTH_TOKEN = "tool_web";            // broker.py의 TOKEN과 동일해야 함

const MAX_CONCURRENT_JOBS = 1; // job마다 tab이 별도로 열림.
const WAKE_LAZY_CONTENT = true; // page를 끝까지 스크롤해서 lazy-loaded content를 깨운 뒤 capture













// ──────────────── JOB POLLING (long-polling) ────────────────
async function runJob(job){
    let tabId;
    try{
        // open new tab
        const tab = await browser.tabs.create({ url: job.url, active: true });
        tabId = tab.id;

        
    }
}


let activateJobCount = 0;
async function pollLoop() {
    while (true) {
        if (activateJobCount >= MAX_CONCURRENT_JOBS){ await sleep(300); continue; }
        
        try{
            // fetch next job from broker
            const response = await fetch(`${BROKER_ADDRESS}/${GET_ENDPOINT_PATH}`, 
                                        { headers: { "X-Auth-Token": AUTH_TOKEN } });
            if (response.status === 204) { await sleep(500); continue; }  // no job to handle
            if (response.status !== 200) { await sleep(3000); continue; }

            const job = await response.json();
            activateJobCount++;
            

            // run job in background
            try{

            }
        }


        






// ──────────────── helper functions ────────────────
const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));
