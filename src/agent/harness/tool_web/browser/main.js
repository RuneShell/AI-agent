const brokerClient = new BrokerClient();
let activeJobCount = 0;

const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

(async function pollLoop() {
    for(;;){
        if (activeJobCount >= MAX_CONCURRENT_JOBS){ await sleep(LOAD.WAIT_ACTIVE_JOB); continue; }
        const job = await brokerClient.getNextJob().catch(() => undefined);
        if (job === undefined) { await sleep(LOAD.BORKER_NOT_REACHABLE); continue; } // broker not reachable
        else if (job === null) { await sleep(LOAD.POLL_INTERVAL); continue; }
        activeJobCount++;
        runningJob(job).finally(() => { activeJobCount--; });
    }
})();
