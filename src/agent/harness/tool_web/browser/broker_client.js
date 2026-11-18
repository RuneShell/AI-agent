
class BrokerClient {
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
        const tab = await TabManager.open(job.url);
        try{
            await tab.waitLoaded();

            if (await tab.hasChallenge()) await this.waitHuman(tab, job); // TODO: method
            
            if (WAKE_LAZY_CONTENT) await tab.wakeLazyContent();

            await this.reportJob(job.id, { status: "ok", result: await tab.captureDOM() });
        } catch (error) {
            await this.reportJob(job.id, { status: "failed", error: String(error) });
        } finally {
            await TabManager.close(tab.id);
        }
    }
}
