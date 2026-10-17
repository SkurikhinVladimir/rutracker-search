# rutracker-simple

Поиск раздач на RuTracker и скачивание `.torrent` из Python.

RuTracker закрыт Cloudflare, и обычные HTTP-клиенты получают 403. Поэтому код
управляет настоящим Chrome через `undetected-chromedriver`.

## Установка

Нужны Python 3.13+, [uv](https://docs.astral.sh/uv/) и Chrome.

```bash
uv sync
```

## Использование

```python
from rutracker_simple import RuTracker

with RuTracker() as rt:
    results = rt.search("python", max_pages=2)
    for r in results[:5]:
        print(r["topic_id"], r["title"], r["seeds"])

    rt.download(results[0]["topic_id"], "book.torrent")
```

`search` возвращает список словарей: `topic_id`, `title`, `category`, `author`,
`size_bytes`, `seeds`, `leeches`, `added` (unix time), `url`. Одна страница
выдачи — 50 раздач, больше — через `max_pages`.

`download` сохраняет файл по указанному пути (по умолчанию `<topic_id>.torrent`
в текущей папке) и возвращает его содержимое.

Chrome запускается в `RuTracker()` и закрывается при выходе из `with`.
Запросы внутри одного блока идут в одном окне, поэтому для серии запросов
создавайте клиент один раз.

Запускать нужно из папки проекта: `uv run python my_script.py`.

Из командной строки:

```bash
uv run python rutracker_simple.py search "python"
uv run python rutracker_simple.py download 6921674 book.torrent
```

## Вход и Cloudflare

Скачивать и искать можно только с аккаунтом. Войдите вручную в открывшемся
окне Chrome или задайте логин и пароль в `.env` (шаблон — `.env.example`):
при отсутствии сессии клиент заполнит форму сам. Сессия хранится в
`.chrome-profile/`, поэтому вход нужен только при первом запуске.

Если Cloudflare покажет проверку, пройдите её в том же окне. Клиент ждёт
до 5 минут (параметр `timeout`).

Проверка привязана к IP: окно Chrome и вы должны выходить в сеть одинаково.
Если драйвер не подходит к версии Chrome, передайте её главный номер:
`RuTracker(chrome_version=140)`.
