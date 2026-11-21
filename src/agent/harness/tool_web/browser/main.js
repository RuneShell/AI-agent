console.log("client extension loaded.");
const brokerClient = new BrokerClient(new TabManager());
let activeJobCount = 0;

const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

(async function pollLoop() {
    for(;;){
        if (activeJobCount >= MAX_CONCURRENT_JOBS){ await sleep(WAIT_MS.ACTIVE_CONCURRENT_JOB); continue; }
        const job = await brokerClient.getNextJob().catch(() => undefined);
        console.log("[GET] job: ", job);
        if (job === undefined) { await sleep(WAIT_MS.BROKER_NOT_REACHABLE); continue; } // broker not reachable
        else if (job === null) { await sleep(WAIT_MS.POLL_INTERVAL); continue; }
        activeJobCount++;
        brokerClient.runJob(job).finally(() => { activeJobCount--; });
    }
})();
