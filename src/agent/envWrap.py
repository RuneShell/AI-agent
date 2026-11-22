import re
import os


# Read a md file, remove comments, and return the content as a string.
# def read_md(filename: str) -> str:
#     if not filename.endswith(".md"):
#         raise ValueError("File must be a markdown file with .md extension.")
#     basedir = os.path.dirname(os.path.abspath(__file__))
#     filepath = os.path.join(basedir, filename)

#     with open(filepath, "r", encoding="utf-8") as f: # Windows 기본 인코딩(cp949)으로는 한글 md를 읽지 못함.
#         content = f.read()

#     # Remove comments from the markdown content
#     content = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL) # DOTALL means NOT '\n'. which helps to match across multiple lines.

#     return content


def merge_dicts_by_keys(*dicts, keys: list) -> dict:
    """pick keys from dicts and merge them into a new dict."""
    return { key: d[key]
        for d in dicts
        for key in keys
        if key in d
    }