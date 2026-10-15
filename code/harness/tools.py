# built-in
from datetime import datetime
import subprocess
import re

# 3rd-party
from strands import tool
import httpx
from bs4 import BeautifulSoup

# custom
from harness.engine import Engine
from configs import MAX_TOOL_OUTPUT_LENGTH

from myLogger import Logger

logger = Logger(log_dir="./logs", runner_name="tool-usage", console=False, file=True, discord=False)



# -------------------------------------------------
# Tools
# -------------------------------------------------



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



@tool(name="command_executor", description=f"Execute a shell command and return the output. Allowed commands: {{cat, cd, date, find, grep, head, ls, pwd, stat, tail, whoami, uptime}} (max output length: {MAX_TOOL_OUTPUT_LENGTH} characters)")
def command_executor(command: str) -> str:
    """Executes a shell command and returns the output. Only allows a predefined set of commands."""
    MAX_OUTPUT_LENGTH = MAX_TOOL_OUTPUT_LENGTH
    allowed_commands = ["cat", "cd", "date", "find", "grep", "head", "ls", "pwd", "stat", "tail", "whoami", "uptime"]
    logger.debug(f"command_executor called with command=`{command}`.")

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
    


# @tool(name="web_search", description="")
# def web_search(query: str) -> list[dict]:
#     return _web_search(query)
    
@tool(name="web_fetch", description="""Fetch a web page and save its content.
The fetched document preserves text, headings, lists, and tables.
Returns a document identifier.

If web_find and web_read do not provide enough information to answer the question,
inspect the href links found in the web_read output and use web_fetch on relevant
href URLs to fetch additional pages. This allows you to follow links from the
current page and gather more detailed or related information.""")
def web_fetch(url: str) -> str: # web search의 결과를 연결시키는 입력이 낫지 않나?
    return _web_fetch(url)

@tool(name="web_find", description="""
Search for an exact text substring in a previously fetched web page.
Returns matching line numbers and surrounding context.
This tool does not understand meaning or semantic relationships.
After finding a heading, title, table cell, or keyword, inspect the
surrounding lines to obtain related information.
""")
def web_find(filename: str, selector: str) -> dict:
    return _web_find(filename, selector)

@tool(name="web_read", description="""
Read a specific section of a fetched document.
Use this after web_find to inspect surrounding content,
especially when the answer depends on relationships between
multiple lines or rows of a table.""")
def web_read(filename: str, line_start: int, line_count: int) -> str:
    return _web_read(filename, line_start, line_count)

# ------------------------------------------------
# Research
# ------------------------------------------------

# Tool : Research
TOOLS_FOR_RESEARCH_LEADER = [
    clock,
]

TOOLS_FOR_RESEARCH_SUPERVISOR = [
    clock,
    command_executor,
    web_fetch,
    web_find,
    web_read,
]

TOOLS_FOR_RESEARCH_SUBAGENT = [
    clock,
    command_executor,
    web_fetch,
    web_find,
    web_read,
]

# research tool
from harness.tool_research import Research


def create_research_tool(model):

    @tool(name="research", description="""
    Order agent leader to research a topic and returns a summary of the findings.
    Only thing you need to do is to offer a concrete, detailed and clear research query... and just wait for the result.
    """)
    def research(query: str) -> str:
        logger.debug(f"research tool called with query=`{query}`.")
        research_instance = Research(query=query, model=model)
        research_instance.Run()
        report = research_instance.research_state.get_report(save_log=True)
        return report

    return research
    

# ------------------------------------------------
# Tool List
# ------------------------------------------------

BASE_TOOLS = [
    clock,
    command_executor,
    web_fetch,
    web_find,
    web_read,
]


def get_tools(role: str, model = None):
    match role:

        # Main agent
        case "main_agent":
            if model is None:
                raise ValueError("Main agent requires a model.")
            return BASE_TOOLS + [ create_research_tool(model) ]

        # Research agents
        case "research_planner":
            return []
        case "research_worker":
            return []

        case _:
            raise ValueError(f"Unknown role: {role}")

# -------------------------------------------------
# Tool Implementations
# -------------------------------------------------

def _web_fetch(url: str) -> str:
    logger.debug(f"web_fetch called with url={url}")
    response = httpx.get(url, follow_redirects=True, timeout=10.0, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"})

    if response.status_code != 200:
        logger.debug(f"web_fetch failed with status_code={response.status_code}, content_length={len(response.text)}")
        return f"Failed to fetch the URL. Status code: {response.status_code}"

    response.raise_for_status()  # Raise an exception for HTTP errors

    soup = BeautifulSoup(response.text, "html.parser")

    # Remove script and style elements
    for element in soup(["script", "style", "noscript", "header", "footer"]):
        element.decompose()

    # Parse images and replace <img> with a placeholder
    for img in soup.find_all("img"):
        parsed_image = _web_fetch_parse_image(img)
        img.replace_with(parsed_image)
    # Parse anchors and replace <a> with text and href
    for a in soup.find_all("a"):
        parsed_anchor = _web_fetch_parse_anchor(a)
        a.replace_with(parsed_anchor)
    # Parse tables and replace <table> with parsed string
    for table in soup.find_all("table"):
        parsed_table = _web_fetch_parse_table(table)
        table.replace_with(parsed_table)



    # block element에만 줄바꿈 추가
    for element in soup.find_all(["p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "pre"]):
        element.append("\n")
    for element in soup.find_all(["strong"]):
        element.append(" ")

    content = soup.get_text(separator="", strip=False) # HTML tag를 \n로 바꿈
    content = "\n".join(
        line.strip()
        for line in content.splitlines()
    )

    content = re.sub(r"\n{3,}", "\n\n", content).strip() # 여러 \n을 2개로 줄임

    # save content to a file
    result = {
        "url": url,
        "content" : content,
    }

    filename = f"web_fetch_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)

    logger.debug(f"content length={len(content)}, saved to {filename}")

    return f"fetched content saved to '{filename}'."

def _web_fetch_parse_image(img) -> str:
    alt = img.get("alt", "")
    if alt == "":
        return ""
    else:
        return f" <img alt={alt}> "

def _web_fetch_parse_anchor(a) -> str:
    href = a.get("href", "")
    text = a.get_text(strip=True)
    if href == "":
        return text
    else:
        return f"{text}(href={href})"

def _web_fetch_parse_table(table) -> str:
    """Convert an HTML table to a Markdown table."""
    headers = [th.get_text(strip=True) for th in table.find_all("th")]
    rows = []
    for tr in table.find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if cells:
            rows.append(cells)

    # Create Markdown table
    markdown_table = "| " + " | ".join(headers) + " |\n"
    markdown_table += "| " + " | ".join(["---"] * len(headers)) + " |\n"
    for row in rows:
        markdown_table += "| " + " | ".join(row) + " |\n"

    return '\n[table]\n' + markdown_table + '\n'
# further table code
# def _web_fetch_parse_table(table):
#     rows = []

#     for tr in table.find_all("tr"):
#         cells = tr.find_all(["th", "td"])

#         if not cells:
#             continue

#         row = [
#             cell.get_text(" ", strip=True)
#             for cell in cells
#         ]

#         rows.append(row)

#     return {
#         "type": "table",
#         "rows": rows
#     }


def _web_find(filename: str, selector: str, context_lines: int = 3) -> dict:
    with open(filename, "r", encoding="utf-8") as f:
        lines = f.readlines()

    results = []

    for i, line in enumerate(lines):
        if selector in line:
            start = max(0, i - context_lines)
            end = min(len(lines), i + context_lines + 1)

            results.append({
                "line": i + 1,
                "context": "".join(lines[start:end])
            })

    logger.debug(f"web_find called with filename={filename}, selector={selector}, Found {len(results)} results., results={results}")
    return {"result_count": len(results), "results": results}

def _web_read(filename: str, line_start: int, line_count: int) -> str:
    logger.debug(f"web_read called with filename={filename}, line_start={line_start}, line_count={line_count}")
    with open(filename, "r", encoding="utf-8") as f:
        lines = f.readlines()

    start = max(0, line_start - 1)  # Convert to 0-based index
    end = start + line_count

    result = "".join(f"{i}: {line}" for i, line in enumerate(lines[start:end], start=line_start)) # 
    logger.debug(f"result: {result}")
    return result




