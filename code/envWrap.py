import re
import os


# Read a md file, remove comments, and return the content as a string.
def read_md(filename: str) -> str:
    if not filename.endswith(".md"):
        raise ValueError("File must be a markdown file with .md extension.")
    basedir = os.path.dirname(os.path.abspath(__file__))
    filepath = os.path.join(basedir, filename)

    with open(filepath, "r") as f:
        content = f.read()

    # Remove comments from the markdown content
    content = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL) # DOTALL means NOT '\n'. which helps to match across multiple lines.

    return content

