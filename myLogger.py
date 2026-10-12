import logging
import os
import time

# -------------------------------------------------
# Discord Webhook Handler
# -------------------------------------------------
class DiscordWebhookHandler(logging.Handler):
    def __init__(self, webhook_url):
        super().__init__()

        import requests
        self.requests = requests

        self.webhook_url = webhook_url

    def emit(self, record):
        message = self.format(record)
        payload = {"content": message}

        try:
            self.requests.post(self.webhook_url, json=payload)
        except Exception as e:
            print(f"Failed to send message to Discord: {e}")


# -------------------------------------------------
# Custom Logger
# -------------------------------------------------
class Logger:
    def __init__(self, log_dir="./logs", runner_name="record", 
                 console=True, file=False, discord=False, *, 
                 setLevel=logging.DEBUG, format="",
                 
                 WEBHOOK_URL=""):
        self._logger = logging.getLogger(runner_name)

        self._logger.setLevel(setLevel)
        formatter   = logging.Formatter(format or "[%(levelname)s] %(asctime)s \n%(message)s", datefmt="%Y-%m-%d %H:%M:%S")

        if console:
            console = logging.StreamHandler()
            self._logger.addHandler(console)
            console.setFormatter(formatter)

        if file:
            if not os.path.exists(log_dir):
                os.makedirs(log_dir)

            file = logging.FileHandler(f"{os.path.join(log_dir, runner_name)}.log")
            self._logger.addHandler(file)
            file.setFormatter(formatter)

        if discord:
            discord = DiscordWebhookHandler(WEBHOOK_URL)
            self._logger.addHandler(discord)
            discord.setFormatter(formatter)

        # self.info("logger started.")

    #== logging built-in methods ==
    def debug(self, message):
        self._logger.debug(message)

    def info(self, message):
        self._logger.info(message)

    def warning(self, message):
        self._logger.warning(message)

    def error(self, message):
        self._logger.error(message)

    def critical(self, message):
        self._logger.critical(message)

    #== custom log methods ==
    def timer_start(self):
        self.start_time = time.time()
    def timer_end(self, message=""):
        elapsed_time = time.time() - self.start_time
        self.debug(f"{message} \n Elapsed time: {elapsed_time:.2f} seconds")