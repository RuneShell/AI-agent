


# Tools

MAX_TOOL_OUTPUT_LENGTH = 4096  # Maximum length of the output from any tool

### TOOL_RESEARCH : ToC Segmentaation
DOCUMENT_EXTENSIONS = [".html", ".txt", ".md"]  # Supported document extensions for chunking # pdf/docs requires wrapper.
CHUNK_MAX_BYTES = 16000 # UTF-8 bytes # 16k model context MAY greater than this.
REPORT_MAX_BYTES = 3000 # UTF-8 bytes. ToC records in toc_document report # TODO: tune with real documents


### TOOL_WEB : Broker
BROKER_HTTP_SERVER_URL = ("127.0.0.1", 11101) # (ip, port)

# Storage
# TODO: 일단보류 


# Logs

### Dashboard: Log Poller
LOG_DASHBOARD_URL = "http://127.0.0.1:10000/report"
LOG_POLLING_INTERVAL = 2 # seconds