# 1. built-in
import os
import pathlib
from datetime import datetime
# import mimetypes # type 추정용

# 2. third-party
from bs4 import BeautifulSoup
from crawlee.crawlers import PydanticAiCleanHtmlDistiller



class FileManager:
    def __init__(self, path):
        # set path
        self.path = pathlib.Path(path)
        self.path.mkdir(exist_ok=True)
        print(f"[FileManager] path: {self.path.resolve()}")


    def save_html(self, data, filename=".html") -> str:
        filepath = os.path.join(self.path, f"{str(datetime.now().strftime('%H%M%S'))}{filename}")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(data)

        print(f"[saved] {filepath} ({len(data)} chars)")
        return filepath

    def read_html(self, filename):
        with open(f"{self.path}/{filename}", "r", encoding="utf-8") as f:
            content = f.read()

            print(f"[read] {filename} ({len(content)} chars)")
            return content


    def save_img(self, img: bytes, meta: dict, filename: str) -> str:

        # [disabled] inferring file extension. - not needed.
        # def __mime_to_extension(content_type: str) -> str:
        #     # "image/jpeg; charset=..." 같은 부가 정보 제거
        #     mime = (content_type or "").split(";")[0].strip().lower()
        #     if mime in self.EXT_MAP:
        #         return self.EXT_MAP[mime]
        #     ext = mimetypes.guess_extension(mime)
        #     return ext.lstrip(".") if ext else "bin"

        # if filename == "":
        #     filename = datetime.now().strftime("%H%M%S")
        # ext = __mime_to_extension(meta["content_type"])
        
        filepath = os.path.join(self.path, f"{str(datetime.now().strftime('%H%M%S'))}{filename}")
        with open(filepath, "wb") as f:
            f.write(img)

        print(f'[saved] {filepath} from {meta["url"]}')
        return filepath




class Worker:
    def __init__(self, results_dir="./tool_web_results"):
        self.file_manager = FileManager(results_dir)


    def clean(self, html: str):
        before_clean_len = len(html)

        # 1. <template>은 distill 대상이므로, <div>로 변환하여 사라지지 않도록. 
        def unwrap_templates(html: str) -> str:
            soup = BeautifulSoup(html, "html.parser")
            # <template> → <div>
            for t in soup.find_all("template"):
                if t.has_attr("data-shadow-root") or t.has_attr("data-iframe-document"):
                    t.name = "div"                       # 속성(data-mode 등)은 그대로 유지
            # <iframe>
            for tag in soup.select("div[data-iframe-document] head"):
                tag.decompose()                          # iframe 문서의 head는 노이즈
            for tag in soup.select("div[data-iframe-document] html, div[data-iframe-document] body"):
                tag.unwrap()                             # 중첩된 html/body 래퍼 제거
            return str(soup)
        unwrapped = unwrap_templates(html) 
        cleaned: str = PydanticAiCleanHtmlDistiller(pretty=True).distill(unwrapped)


        # 2. 내부에 유의미한 데이터가 없는 'hidden-data' element 제거
        def remove_hidden_data(html: str) -> str:
            hidden = "data-hidden"

            soup = BeautifulSoup(html, "html.parser")
            for element in soup.select(f'[{hidden}]'):
                has_content = element.get_text(strip=True) or element.find()

                if not has_content:
                    element.decompose()  # remove the element entirely
            return str(soup)
        cleaned = remove_hidden_data(cleaned)


        # TODO: 무의미한 nested div를 compact할 것인가?
        # def compact_nested_div(html: str) -> str:
        #     soup = BeautifulSoup(html, "html.parser")

        #     while True:
        #         elements = soup.select("div")
        #         targets = [element for element in elements if len(element.contents) == 1 and element.div]
        #         if not targets:
        #             break

        #         for element in targets:
        #             element.unwrap()
        #     return str(soup)

        # cleaned = compact_nested_div(cleaned)


        # 3. 링크가 전체 html의 5~15%를 차지하므로, href나 src 링크는 별도 dict에 저장하고, 숫자로 대체
        def compress_html_links(html: str) -> tuple[str, dict[str, str]]:
            soup = BeautifulSoup(html, "html.parser")

            link_dict = {}
            link_index = 0

            for tag in soup.find_all(True):
                for attr in ("href", "src"):
                    url = tag.get(attr)
                    if url is None:
                        continue

                    # 동일한 URL은 동일한 인덱스 재사용
                    if url not in link_dict.values():
                        link_dict[str(link_index)] = url
                        link_index += 1

                    # URL을 숫자 식별자로 대체
                    index = next(key for key, value in link_dict.items() if value == url)
                    tag[attr] = index

            return str(soup), link_dict
        compressed, links = compress_html_links(cleaned)
        print(f"{len(links)} links found.")


        after_clean_len = len(compressed)
        print(f"[cleaned] {before_clean_len} → {after_clean_len} chars")
        return compressed, links



if __name__ == "__main__":
    worker = Worker()

    content = worker.file_manager.read_html("save.html")

    cleaned, links = worker.clean(content)

    worker.file_manager.save_html(cleaned, "cleaned.html")
    print(links)