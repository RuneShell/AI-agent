import random, time
from log_poller import LogPoller


class TemperatureModule:
    def __init__(self, poller):
        self.poller = poller

    def start(self):
        self.poller.register("temperature", self.get_widgets)

    def stop(self):
        self.poller.unregister("temperature")

    def get_widgets(self):
        # poller가 주기마다 호출한다. 현재 값을 위젯(dict)으로 돌려주면 끝.
        return [{"type": "graph", "name": "temperature", "value": round(20 + random.random() * 5, 2)}]


poller = LogPoller("demo", "http://127.0.0.1:10000/report", interval=2)
poller.start()

module = TemperatureModule(poller)
module.start()    # 이 순간부터 대시보드에 올라감


time.sleep(600)


module.stop()     # 이 순간부터 payload에서 빠짐
poller.stop()