# built-in
from datetime import datetime
import subprocess

# 3rd-party
from strands import tool

# custom
from ..configs import MAX_TOOL_OUTPUT_LENGTH
from ..myLogger import Logger
logger = Logger(log_dir="./logs", runner_name="tool-usage", console=False, file=True, discord=False)



# ──────────────── 1. Common Tools ────────────────   


@tool(name="clock", description="What datetime is it now?")
def clock() -> str:
    """Retrieves datetime in the format: weekday YYYY-MM-DD HH:MM:SS"""
    now = datetime.now()
    current_time = now.strftime("%A %Y-%m-%d %H:%M:%S")

    logger.debug(f"clock called, returning current time: {current_time}")
    return current_time


# @tool(name="file_reader", description="Read the content of a file with offset and length. (max length: 8192 characters)")
# def file_reader(file_path: str, offset: int = 0, length: int = 100) -> str:
#     MAX_READ_LENGTH = 8192
#     import os
#     if not os.path.isfile(file_path):
#         logger.debug(f"file_reader called with file_path={file_path}, but file does not exist.")
#         return f"File '{file_path}' does not exist."

#     with open(file_path, "r") as f:
#         f.seek(offset)
#         content = f.read(min(length, MAX_READ_LENGTH))

#     logger.debug(f"file_reader called with file_path={file_path}, offset={offset}, length={length}, returning content of length {len(content)}")
#     return content



@tool(name="shell", description=f"Execute a shell command and return the output. Allowed commands: {{cat, cd, date, find, grep, head, ls, pwd, stat, tail, whoami, uptime}} (max output length: {MAX_TOOL_OUTPUT_LENGTH} characters)")
def shell(command: str) -> str:
    """Executes a shell command and returns the output. Only allows a predefined set of commands."""
    MAX_OUTPUT_LENGTH = MAX_TOOL_OUTPUT_LENGTH
    allowed_commands = ["cat", "cd", "date", "find", "grep", "head", "ls", "pwd", "stat", "tail", "whoami", "uptime"]
    logger.debug(f"shell called with command=`{command}`.")

    try:
        command_name = command.split()[0]
        if command_name in allowed_commands:
            result = subprocess.run(command, shell=True, capture_output=True, text=True)
            output = result.stdout + result.stderr
            return output[:MAX_OUTPUT_LENGTH]
        else:
            return f"Command '{command_name}' is not allowed."
        
    except Exception as e:
        logger.debug(f"Error executing command : {e}")
        return f"Error executing command : {str(e)}"







# ──────────────── 2. Research Tools ────────────────}

