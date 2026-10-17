"""Клиент RuTracker поверх undetected-chromedriver."""

import argparse
import base64
import random
import sys
import time
from pathlib import Path
from urllib.parse import quote_plus

import undetected_chromedriver as uc
from bs4 import BeautifulSoup
from selenium.common.exceptions import TimeoutException, WebDriverException
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
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip("\"'")
    return env


def to_int(text: str) -> int:
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else 0


def link_text(cell) -> str:
    link = cell.find("a")
    return link.text.strip() if link else ""


class RuTracker:
    def __init__(
        self,
        timeout: int = 300,
        chrome_version: int | None = None,
        delay: tuple[float, float] = (4.0, 10.0),
    ):
        self.timeout = timeout
        self.delay = delay
        self.env = load_env()
        self._login_tried = False
        self._last_request = 0.0
        options = uc.ChromeOptions()
        options.add_argument(f"--user-data-dir={PROFILE}")
        self.driver = uc.Chrome(options=options, version_main=chrome_version)

    def close(self) -> None:
        try:
            self.driver.quit()
        except WebDriverException:
            pass  # окно уже закрыто вручную

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _pause(self) -> None:
        """Выдерживает случайную паузу между загрузками страниц."""
        wait = random.uniform(*self.delay) - (time.time() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.time()

    def _open(self, url: str, marker: str) -> str:
        """Открывает страницу и ждёт, пока в её HTML появится marker.

        Пока marker нет, ждёт ручного прохождения Cloudflare или входа в окне.
        """
        self._pause()
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
        """Входит по данным из .env, один раз за сессию.

        Возвращает True, если попытка была (удачная или нет): страницу нужно
        открыть заново, потому что драйвер остался на login.php.
        """
        if self._login_tried or "login_username" not in html:
            return False
        if not {"RUTRACKER_LOGIN", "RUTRACKER_PASSWORD"} <= self.env.keys():
            return False
        self._login_tried = True
        # на обычных страницах форма скрыта, поэтому входим через login.php
        self.driver.get(f"{FORUM}/login.php")
        wait = WebDriverWait(self.driver, 20)
        try:
            username = wait.until(
                EC.visibility_of_element_located((By.NAME, "login_username"))
            )
            username.send_keys(self.env["RUTRACKER_LOGIN"])
            self.driver.find_element(By.NAME, "login_password").send_keys(
                self.env["RUTRACKER_PASSWORD"]
            )
            self.driver.find_element(By.NAME, "login").click()
            wait.until(lambda d: "login_username" not in d.page_source)
        except (TimeoutException, WebDriverException) as e:
            print(
                f"Автовход не удался ({type(e).__name__}), войдите вручную в окне",
                file=sys.stderr,
            )
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
        results = []
        for row in table.find("tbody").find_all("tr"):
            cells = row.find_all("td")[1:]
            if len(cells) < 9:  # строка «Не найдено» или служебная
                continue
            link = cells[2].find("a")
            topic_id = int(link["data-topic_id"])
            results.append(
                {
                    "topic_id": topic_id,
                    "title": link.text.strip(),
                    "category": link_text(cells[1]),
                    "author": link_text(cells[3]),
                    "size_bytes": int(cells[4]["data-ts_text"]),
                    "seeds": to_int(cells[5].text),
                    "leeches": to_int(cells[6].text),
                    "added": int(cells[8]["data-ts_text"]),
                    "url": f"{FORUM}/viewtopic.php?t={topic_id}",
                }
            )
        return results

    def download(self, topic_id: int | str, path: str | Path | None = None) -> bytes:
        """Скачивает .torrent через fetch со страницы раздачи и сохраняет в path."""
        topic_id = int(topic_id)
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
    parser = argparse.ArgumentParser(description="Поиск и скачивание с RuTracker")
    commands = parser.add_subparsers(dest="command", required=True)

    search = commands.add_parser("search", help="искать раздачи")
    search.add_argument("query")
    search.add_argument("--pages", type=int, default=1, help="страниц по 50 раздач")

    download = commands.add_parser("download", help="скачать .torrent")
    download.add_argument("topic_id", type=int)
    download.add_argument("path", nargs="?", help="по умолчанию <topic_id>.torrent")

    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    with RuTracker() as rt:
        if args.command == "search":
            for r in rt.search(args.query, max_pages=args.pages):
                print(
                    f"{r['topic_id']}\t{r['size_bytes'] / 1e9:.2f} GB\t"
                    f"S:{r['seeds']} L:{r['leeches']}\t{r['title']}"
                )
        else:
            path = args.path or f"{args.topic_id}.torrent"
            size = len(rt.download(args.topic_id, path))
            print(f"{path}: {size} байт")


if __name__ == "__main__":
    main()
