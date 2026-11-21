
class BrokerClient {
    constructor(tabManager){
        this.tabManager = tabManager;
    }

    async getNextJob() {                      // job | null
        const response = await fetch(`${BROKER_ADDRESS}/${GET_ENDPOINT_PATH}`, 
                                    { headers: { "X-Auth-Token": AUTH_TOKEN } });
        return response.status === 200 ? response.json() : null;
    }
    reportJob(jobId, payload) {               // payload: { status: "ok"|"failed", ... }
        return fetch(`${BROKER_ADDRESS}/${POST_ENDPOINT_PATH}`, {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-Auth-Token": AUTH_TOKEN },
            body: JSON.stringify({ id: jobId, ...payload }),
        });
    }

    // ──────────────── JOB RUNNER ────────────────
    async runJob(job) {
        let tab;
        try{
            tab = await this.tabManager.open(job.url);
            await tab.waitLoaded();

            if (await tab.hasChallenge()){ // captcha 등의 challenge가 있는 경우
                await this.reportJob(job.id, { status: "needs_human" });
                // tab을 focus. // [disabled] window는 focus하지 않음
                await browser.tabs.update(tab.id, { active: true });
                // const t = await browser.tabs.get(tabId);
                // await browser.windows.update(t.windowId, { drawAttention: true });

                if (await this.waitHuman(tab, job)){ // human이 challenge를 해결한 경우
                    await tab.waitLoaded(); // page load 대기
                } else{
                    throw new Error("human timeout");
                }
            }
            
            if (WAKE_LAZY_CONTENT) await tab.wakeLazyContent();

            await this.reportJob(job.id, { status: "ok", result: await tab.captureDOM() });
        } catch (error) {
            await this.reportJob(job.id, { status: "failed", error: String(error) });
        } finally {
            await this.tabManager.close(tab.id);
        }
    }

    async waitHuman(tab, job){
        const start = Date.now();
        while(Date.now() - start < WAIT_MS.HUMAN_TIMEOUT && (await tab.hasChallenge())){

            await sleep(WAIT_MS.CHECK_CAPTCHA);
        } 

        // timeout
        if (await tab.hasChallenge()) return false;
        return true;
    }
}
