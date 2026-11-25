"""[chunker.py: Document Chunker]
Serves a document as line-numbered Chunks for LLM agents. Knows neither LLM nor DB.
"""
# written by Claude Opus 5.5 (high)

# 1. built-in
import hashlib  # 내용이 바뀌면 정규화 파일명도 바뀌어, 기존 ToC의 줄 번호가 깨지지 않도록
import os
from dataclasses import dataclass

# 2. third-party

# 3. custom
from ...configs import DOCUMENT_EXTENSIONS, CHUNK_MAX_BYTES


"""How to assemble classes
chunker = Chunker.from_file(filepath)   # 줄이 망가진 로컬 HTML이면 normalize=True

cursor = 1
while cursor <= chunker.line_count:
    chunk = chunker.take_chunk(cursor)
    ...                                 # chunk.text를 Segmenter에 전달
    cursor = next_start_line            # 마지막 구간은 보류하고 다음 chunk에서 다시 읽는다
"""
# TODO: Things to consider
# normalize된 파일 이름에 추가로 붙는 게 의미가 있나?
# truckation marker bytes가 뭐임. 의미가 있나.


class Chunker:
    """Serves a document as line-numbered Chunks within a byte budget."""
    NORMALIZED_SUFFIX       = ".normalized"
    TRUNCATION_MARKER_BYTES = 64  # 잘린 줄의 표식이 들어갈 자리

    @dataclass
    class Chunk:
        start_line: int   # inclusive, 1-based # TODO: system prompt에도 넣어야 함.
        end_line:   int   # inclusive
        is_last:    bool  # 문서의 마지막 줄까지 포함하는가
        text:       str   # 줄 번호가 붙은 LLM 입력

    def __init__(self, filepath: str, text: str, chunk_max_bytes: int = CHUNK_MAX_BYTES):
        if not text.strip():
            raise ValueError(f"Cannot chunk an empty document: {filepath}")
        if chunk_max_bytes <= self.TRUNCATION_MARKER_BYTES:
            raise ValueError(f"chunk_max_bytes is {chunk_max_bytes}. Must be > {self.TRUNCATION_MARKER_BYTES}.")

        self.filepath = filepath  # normalize=True면 정규화 파일. DB에는 이 경로를 등록한다.
        self.chunk_max_bytes = chunk_max_bytes

        # !!! splitlines()는 \x0b,  등에서도 나뉘어 에디터의 줄 번호와 어긋난다.
        self._lines = text.removesuffix("\n").split("\n")
        self.line_count = len(self._lines)

    @classmethod
    def from_file(cls, filepath: str, normalize: bool = False) -> "Chunker":
        """normalize=True면 지금 정규화를 수행한다. web_fetch 결과는 이미 줄이 나뉘어 있으므로 False."""
        ext = os.path.splitext(filepath)[1].lower()

        with open(filepath, "r", encoding="utf-8") as f:  # 텍스트 모드가 \r\n, \r을 \n으로 통일한다.
            text = f.read()

        if normalize and text.strip():
            filepath, text = cls._normalize_file(filepath, text, ext)
        return cls(filepath, text)


    # ──────── ToC build loop ────────
    def take_chunk(self, start_line: int, *, max_bytes: int | None = None, backward: bool = False) -> "Chunker.Chunk":
        """ Generated a formatted chunk from `start_line`(1-based) to `start_line + chunk_max_bytes`.
            backward=True: get `max_bytes` lines from backward.)
        .text e.g.: L1| <div><p>Run the installer.</p></div>
                    L2| <p>Run it.</p>
                    (omitted)
        """
        if not 1 <= start_line <= self.line_count:
            raise ValueError(f"Invalid start_line: {start_line}. Must be in [1, {self.line_count}].")
        max_bytes = max_bytes or self.chunk_max_bytes

        # gather Chunk lines
        numbered_lines: list[str] = []
        used_bytes = -1  # "\n" in front of the first line MUST be ignored.
        numbers = range(start_line, 0, -1) if backward else range(start_line, self.line_count + 1)
        for number in numbers:
            # [format]: `L12| <div><p>Run the installer.</p></div>`
            numbered_line = f"L{number}| {self._lines[number - 1]}"
            used_bytes += len(numbered_line.encode("utf-8")) + 1  # +1: "\n"
            if used_bytes > max_bytes:
                break
            numbered_lines.append(numbered_line)

        # if Overflow from first line, then truncate
        if not numbered_lines:
            encoded = numbered_line.encode("utf-8")
            shown   = encoded[:max_bytes - self.TRUNCATION_MARKER_BYTES].decode("utf-8", errors="ignore")  # 글자 중간에서 잘린 바이트는 버린다.
            numbered_lines = [f"{shown} [truncated: showing {len(shown.encode('utf-8'))} of {len(encoded)} bytes]"]

        # return Chunk
        if backward:
            numbered_lines.reverse()
            start_line, end_line = start_line - len(numbered_lines) + 1, start_line
        else:
            end_line = start_line + len(numbered_lines) - 1
        return self.Chunk(start_line = start_line,
                          end_line   = end_line,
                          is_last    = end_line == self.line_count,
                          text       = "\n".join(numbered_lines))


    # ──────── Sub Methods ────────
    @classmethod
    def _normalize_file(cls, filepath: str, text: str, ext: str) -> tuple[str, str]:
        """줄을 정리한 결과를 별도 파일에 저장한다. 줄 번호가 가리킬 파일이 필요하고, 원본은 유지해야 한다."""
        root = os.path.splitext(filepath)[0]
        if root.endswith(cls.NORMALIZED_SUFFIX):
            return filepath, text

        if ext == ".html":
            import lxml.html  # worker의 distiller와 같은 방식으로 블록 태그 단위로 줄을 나눈다.
            parser = lxml.html.HTMLParser(encoding="utf-8")  # str 입력은 encoding 선언이 있으면 오류가 난다.
            tree = lxml.html.document_fromstring(text.encode("utf-8"), parser=parser)
            text = lxml.html.tostring(tree, encoding="unicode", pretty_print=True)

        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        normalized_path = f"{root}.{digest}{cls.NORMALIZED_SUFFIX}{ext}"
        with open(normalized_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        return normalized_path, text




if __name__ == "__main__":
    # Run from `src/`: python -m agent.harness.tool_research.chunker <filepath>
    # import sys

    # chunker = Chunker.from_file(sys.argv[1])
    # cursor = 1
    # while cursor <= chunker.line_count:
    #     chunk = chunker.take_chunk(cursor)
    #     print(f"L{chunk.start_line}~L{chunk.end_line} ({len(chunk.text.encode('utf-8'))} bytes)")
    #     cursor = chunk.end_line + 1

    chunker = Chunker.from_file(r"C:\Users\Computer\Documents\GitHub\AI-agent\tool_web_results\164320clean.html")
    print(chunker.take_chunk(1).text)
