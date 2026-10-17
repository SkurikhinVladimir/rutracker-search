# rutracker-simple

Поиск раздач на RuTracker и скачивание `.torrent` из Python.

RuTracker закрыт Cloudflare, поэтому запросы идут не напрямую, а через настоящий
Chrome (`undetected-chromedriver`). Окно открывается само, сессия хранится
в `.chrome-profile/`.

## Установка

Нужны Python 3.13+, [uv](https://docs.astral.sh/uv/) и установленный Chrome.

```bash
uv sync
```

Логин и пароль (необязательно) кладутся в `.env`, шаблон — `.env.example`.
Если сессия в профиле истекла, клиент сам заполнит форму входа.

## Использование из кода

```python
from rutracker_simple import RuTracker

with RuTracker() as rt:
    results = rt.search("python", max_pages=2)
    for r in results[:5]:
        print(r["topic_id"], r["title"], r["seeds"])

    rt.download(results[0]["topic_id"], "book.torrent")
```

`search` возвращает список словарей с полями `topic_id`, `title`, `category`,
`author`, `size_bytes`, `seeds`, `leeches`, `added` (unix time), `url`.
`download` сохраняет файл и возвращает его байты.

Chrome запускается при создании `RuTracker()` и закрывается при выходе из
`with`. Все запросы внутри одного блока идут в одном окне, поэтому для серии
запросов создавайте клиент один раз:

```python
with RuTracker() as rt:
    for title in titles:
        rt.search(title)
```

Скрипт нужно запускать из папки проекта через `uv run`, чтобы подхватились
зависимости: `uv run python my_script.py`.

## Командная строка

```bash
uv run python rutracker_simple.py search "python"
uv run python rutracker_simple.py download 6921674 book.torrent
```

Каждая команда запускает Chrome заново.

## Cloudflare и вход

- Если Cloudflare покажет проверку, пройдите её в открывшемся окне Chrome.
  Скрипт подождёт (по умолчанию до 5 минут, параметр `timeout`).
- После первого прохождения проверка обычно не повторяется, пока жив профиль.
- Если драйвер ругается на версию Chrome, передайте её главный номер:
  `RuTracker(chrome_version=140)`.
- Окно браузера должно выходить в сеть с того же IP, с которого вы проходите
  проверку. Через VPN это тоже работает, если окно открыто через него.

## Файлы

| Файл | Назначение |
| --- | --- |
| `rutracker_simple.py` | клиент и CLI |
| `.env` | логин и пароль, не коммитить |
| `.chrome-profile/` | профиль Chrome с сессией, не коммитить |
