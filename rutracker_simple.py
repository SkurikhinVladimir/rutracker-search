"""Клиент RuTracker поверх undetected-chromedriver."""

import base64
import sys
import time
from pathlib import Path
from urllib.parse import quote_plus

import undetected_chromedriver as uc
from bs4 import BeautifulSoup
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

FORUM = "https://rutracker.org/forum"
BASE_DIR = Path(__file__).parent
PROFILE = BASE_DIR / ".chrome-profile"
PAGE_SIZE = 50

FETCH_TORRENT_JS = """
const done = arguments[arguments.length - 1];
fetch(arguments[0], {credentials: 'include'})
  .then(r => r.arrayBuffer())
  .then(buf => {
    const bytes = new Uint8Array(buf);
    let s = '';
    for (let i = 0; i < bytes.length; i += 8192)
      s += String.fromCharCode(...bytes.subarray(i, i + 8192));
    done(btoa(s));
  })
  .catch(e => done('ERR:' + e));
"""


def load_env(path: Path = BASE_DIR / ".env") -> dict[str, str]:
    if not path.exists():
        return {}
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


class RuTracker:
    def __init__(self, timeout: int = 300, chrome_version: int | None = None):
        self.timeout = timeout
        self.env = load_env()
        self._login_tried = False
        options = uc.ChromeOptions()
        options.add_argument(f"--user-data-dir={PROFILE}")
        self.driver = uc.Chrome(options=options, version_main=chrome_version)

    def close(self) -> None:
        self.driver.quit()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _open(self, url: str, marker: str) -> str:
        """Открывает страницу и ждёт, пока в её HTML появится marker.

        Пока marker нет, ждёт ручного прохождения Cloudflare или входа в окне.
        """
        self.driver.get(url)
        deadline = time.time() + self.timeout
        warned = False
        while time.time() < deadline:
            html = self.driver.page_source
            if marker in html:
                return html
            if self._login(html):
                self.driver.get(url)
                continue
            if not warned:
                print("Пройдите проверку или войдите в окне Chrome", file=sys.stderr)
                warned = True
            time.sleep(1.5)
        raise TimeoutError(f"Страница {url} не открылась за {self.timeout} с")

    def _login(self, html: str) -> bool:
        """Заполняет форму входа данными из .env. Пробует один раз за сессию."""
        if self._login_tried or "login_username" not in html:
            return False
        if not {"RUTRACKER_LOGIN", "RUTRACKER_PASSWORD"} <= self.env.keys():
            return False
        self._login_tried = True
        # на обычных страницах форма скрыта, поэтому входим через login.php
        self.driver.get(f"{FORUM}/login.php")
        try:
            wait = WebDriverWait(self.driver, 20)
            username = wait.until(
                EC.visibility_of_element_located((By.NAME, "login_username"))
            )
            username.send_keys(self.env["RUTRACKER_LOGIN"])
            self.driver.find_element(By.NAME, "login_password").send_keys(
                self.env["RUTRACKER_PASSWORD"]
            )
            self.driver.find_element(By.NAME, "login").click()
        except WebDriverException as e:
            print(
                f"Автовход не удался ({type(e).__name__}), войдите вручную в окне",
                file=sys.stderr,
            )
            return False
        time.sleep(3)
        return True

    def search(self, query: str, max_pages: int = 1) -> list[dict]:
        results = []
        for page in range(max_pages):
            url = f"{FORUM}/tracker.php?nm={quote_plus(query)}&start={page * PAGE_SIZE}"
            rows = self._parse_results(self._open(url, 'id="tor-tbl"'))
            results += rows
            if len(rows) < PAGE_SIZE:
                break
        return results

    @staticmethod
    def _parse_results(html: str) -> list[dict]:
        table = BeautifulSoup(html, "lxml").find("table", id="tor-tbl")
        if table is None:
            return []
        results = []
        for row in table.find("tbody").find_all("tr"):
            cells = row.find_all("td")[1:]
            if not cells:
                break
            link = cells[2].find("a")
            topic_id = int(link["data-topic_id"])
            results.append(
                {
                    "topic_id": topic_id,
                    "title": link.text,
                    "category": cells[1].find("a").text,
                    "author": cells[3].find("a").text,
                    "size_bytes": int(cells[4]["data-ts_text"]),
                    "seeds": cells[5].text.strip(),
                    "leeches": cells[6].text.strip(),
                    "added": int(cells[8]["data-ts_text"]),
                    "url": f"{FORUM}/viewtopic.php?t={topic_id}",
                }
            )
        return results

    def download(self, topic_id: int | str, path: str | Path | None = None) -> bytes:
        """Скачивает .torrent через fetch со страницы раздачи и сохраняет в path."""
        self._open(f"{FORUM}/viewtopic.php?t={topic_id}", "dl.php")
        result = self.driver.execute_async_script(
            FETCH_TORRENT_JS, f"{FORUM}/dl.php?t={topic_id}"
        )
        if result.startswith("ERR:"):
            raise RuntimeError(result)
        data = base64.b64decode(result)
        if b"announce" not in data[:300]:
            raise RuntimeError("Ответ не похож на .torrent, возможно нет авторизации")
        Path(path or f"{topic_id}.torrent").write_bytes(data)
        return data


def main() -> None:
    usage = 'usage: rutracker_simple.py search "запрос" | download TOPIC_ID [файл]'
    if len(sys.argv) < 3 or sys.argv[1] not in ("search", "download"):
        sys.exit(usage)
    command, arg = sys.argv[1:3]
    with RuTracker() as rt:
        if command == "search":
            for r in rt.search(arg):
                print(
                    f"{r['topic_id']}\t{r['size_bytes'] / 1e9:.2f} GB\t"
                    f"S:{r['seeds']} L:{r['leeches']}\t{r['title']}"
                )
        else:
            path = sys.argv[3] if len(sys.argv) > 3 else f"{arg}.torrent"
            size = len(rt.download(arg, path))
            print(f"{path}: {size} байт")


if __name__ == "__main__":
    main()
