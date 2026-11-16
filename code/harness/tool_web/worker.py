# 1. built-in
import pathlib
from datetime import datetime
import re
import mimetypes # type 추정용

# 2. third-party
from bs4 import BeautifulSoup
from crawlee.crawlers import PydanticAiCleanHtmlDistiller



class FileManager:
    def __init__(self, path):
        # set path
        self.path = pathlib.Path(path)
        self.path.mkdir(exist_ok=True)
        print(f"[FileManager] path: {self.path.resolve()}")


    def save_html(self, data, filename=""):
        filename = f"{str(datetime.now().strftime("%H%M%S"))}{filename}"

        with open(f"{self.path}/{filename}", "w", encoding="utf-8") as f:
            f.write(data)
        print(f"[saved] {filename} ({len(data)} chars)")

    def read_html(self, filename):
        with open(f"{self.path}/{filename}", "r", encoding="utf-8") as f:
            content = f.read()

            print(f"[read] {filename} ({len(content)} chars)")
            return content


    def save_img(self, img, meta: dict, filename=""):

        def __mime_to_extension(content_type: str) -> str:
            # "image/jpeg; charset=..." 같은 부가 정보 제거
            mime = (content_type or "").split(";")[0].strip().lower()
            if mime in self.EXT_MAP:
                return self.EXT_MAP[mime]
            ext = mimetypes.guess_extension(mime)
            return ext.lstrip(".") if ext else "bin"

        if filename == "":
            filename = datetime.now().strftime("%H%M%S")
        ext = __mime_to_extension(meta["content_type"])
        path = f'{self.path}/{filename}.{ext}'
        with open(path, "wb") as f:
            f.write(img)
        print(f'[saved] {filename}.{ext} from {meta["url"]}')




class Worker:
    def __init__(self):
        self.file_manager = FileManager(".")


    def clean(self, html: str):

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


        # 2. distill
        cleaned: str = PydanticAiCleanHtmlDistiller(pretty=True).distill(unwrapped)


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


        return compressed, links



if __name__ == "__main__":
    worker = Worker()

    content = worker.file_manager.read_html("save.html")

    cleaned, links = worker.clean(content)

    worker.file_manager.save_html(cleaned, "cleaned.html")
    print(links)