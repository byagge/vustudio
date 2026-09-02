# VU QA Platform

Платформа для **генерации синтетических записей ВУ**, валидации правил R01–R11, Telegram-бота и веб-панели.

> Каждая запись помечена `synthetic: true` и предназначена для QA/тестирования валидатора, а не как документ.

## Что входит

| Компонент | Описание |
|---|---|
| `vu-qa-bot/` | Генератор, валидатор, Telegram-бот |
| `api/` | REST API (FastAPI) + OpenAPI `/docs` |
| `web/static/` | Веб-панель генерации и валидации |
| `docker-compose.yml` | API + бот в контейнерах |

## Быстрый старт (Windows)

```powershell
cd D:\codes\otris
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
# заполните BOT_TOKEN и ALLOWED_USERS в .env
```

### Telegram-бот

```powershell
cd vu-qa-bot
..\.venv\Scripts\python vu_qa_bot.py
```

Команды: `/me`, `/generate`, `/json`, `/regions`, `/clear`

### API + веб-панель

```powershell
cd D:\codes\otris
.\.venv\Scripts\uvicorn api.main:app --reload --port 8080
```

Откройте http://localhost:8080 — веб-панель.  
Документация API: http://localhost:8080/docs

### Docker

```powershell
copy .env.example .env
docker compose up -d --build
```

## API

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/health` | Статус |
| GET | `/api/v1/regions` | Справочник регионов |
| POST | `/api/v1/generate` | Генерация одной записи |
| POST | `/api/v1/validate` | Проверка JSON по R01–R11 |
| POST | `/api/v1/evaluate` | Метрики precision/recall |
| POST | `/api/v1/dataset` | Пакет valid + mutated |

Если задан `API_KEY` в `.env`, передавайте заголовок `X-API-Key`.

Пример:

```bash
curl -X POST http://localhost:8080/api/v1/generate \
  -H "Content-Type: application/json" \
  -d '{"me":"АБСАЛЯМОВ ВЛАДИСЛАВ НАИЛЕВИЧ 08.09.1983 Г. ХАБАРОВСК","valid_now":true}'
```

## CLI (датасеты и CI)

```powershell
cd vu-qa-bot
..\.venv\Scripts\python vu_testdata.py --valid 500 --mutated 1100 -o dataset.jsonl
..\.venv\Scripts\python eval_rules.py --valid 500 --mutated 1100
..\.venv\Scripts\python test_vu.py
```

## Переменные окружения

См. `.env.example`.

## Соответствие ТЗ v2.3

| Пункт ТЗ | Реализация |
|---|---|
| §7.2 `/me` + `/start`/`/help`/`/forget` | `vu_qa_bot.py` |
| §7.3 профиль с `region`, `birth_place` | `profiles.py` |
| §7.4 формат вывода с QA-блоком | `formatter.py` → `format_debug_block` |
| §2.2 клавиатура места рождения | инлайн-кнопки при `/me` без места |
| §4.6 сохранение подразделения в профиле | `save_region()` |
| §7.5 `.jsonl` `dataset_{ok}_{bad}.jsonl` | API `/api/v1/dataset/download`, CLI `-o` |
| §8 CLI | `vu_testdata.py` |
| §9 тесты 1–5, 7 | `test_vu.py`, `test_profiles.py` |
| §10 CI | `.github/workflows/ci.yml` |

## Отрисовка (task1.md, task4.md)

```
Telegram-бот → парсер → JSON → очередь → render-worker → Photoshop → JPG + PSD
```

**Запуск worker (Windows + Photoshop):**
```powershell
cd D:\codes\otris\vu-qa-bot
..\.venv\Scripts\python render_worker.py
```

**Бот + API** кладут задачи в `queue/pending/`. Worker забирает и отдаёт файлы в `output/`.  
Photoshop **не запускается** в боте/API (`RENDER_MODE=server` по умолчанию).

### Серверная обработка (Windows VPS)

```
Linux/Docker: bot + API          Windows VPS: render_worker + Photoshop
       │                                    │
       └── shared queue/ + output/ ─────────┘
              (NFS / SMB / git-sync)
```

**Windows worker:**
```powershell
.\scripts\start_render_worker.ps1
# или
cd D:\codes\otris\vu-qa-bot
..\.venv\Scripts\python render_worker.py
```

**Проверка:**
```powershell
.\scripts\check_render_server.ps1
curl http://localhost:8080/api/v1/render/server -H "X-API-Key: YOUR_KEY"
```

Один инстанс Photoshop, file-lock `.photoshop.lock`, heartbeat `.worker_heartbeat.json`,  
автовосстановление зависших задач из `processing/` (`RENDER_STALE_JOB_SEC`).

| Мокап | Файл | Кнопка |
|---|---|---|
| Бланк | `Прямоугольник 2 копия.psb` | 📄 Бланк |
| Рука+фон | `Мокап (рука+фоны).psb` | 🤚 Рука+фон |
| Оригинал | тот же, без руки | 🖼 Оригинал |

Фоны 1–10 — слои `Вариант N` внутри smart object «Меняющийся фон (Ред)`.

**API:**
- `GET /api/v1/mockups` — список мокапов и фонов
- `GET /api/v1/render/server` — статус worker + очередь
- `GET /api/v1/render/server/status` — alias
- `GET /api/v1/render/queue` — статистика очереди
- `GET /api/v1/render/scene/verify` — проверка PSB vs templates
- `POST /api/v1/render` — `{text_block, mockup, background, wait}`
- `GET /api/v1/render/{job_id}` — статус
- `GET /api/v1/render/download/{jpg|psd|psb}?path=...` — скачать из `output/`

**Портрет (task3):** `/portrait`, кнопка «🧑 Портрет (ИИ)», smart object `Photo`.  
Mock API: `uvicorn portrait_api.app:app --port 8090` или `docker compose up portrait-api`.  
`PORTRAIT_API_URL=http://127.0.0.1:8090/generate`

## Структура vu-qa-bot

| Файл | Назначение |
|---|---|
| `vu_testdata.py` | Генератор и справочники |
| `eval_rules.py` | Валидатор R01–R11 |
| `formatter.py` | Клиентский текстовый блок |
| `vu_qa_bot.py` | Telegram-бот |
| `profiles.py` | Хранилище профилей |
| `photoshop_text.py` | **Подстановка текста** — единый API (task1/task2) |
| `photoshop_server.py` | **task4** — очередь, heartbeat, `RENDER_MODE=server` |
| `render_worker.py` | Windows worker → Photoshop (COM/JSX) |
| `mockup_scene.py` | **task4** — фон 1–10, hand/original, verify scene |
| `render_cli.py` | CLI: `--text`, `--dry-run`, `--queue` |
| `psb_utils.py` | Инспекция PSB, verify шаблонов |
| `template_cache.py` | Кэш открытого шаблона в Photoshop |
| `font_registry.py` | Шрифты Z_NOMER / Z_NOMER0 → worker + JSX |

**Шрифты:** `assets/fonts/` (`Z_NOMER.TTF`, `Z_NOMER0.TTF`). Worker загружает их перед Photoshop; JSX применяет PostScript-имена к слоям серии/номера. `python scripts/verify_fonts.py`

## Админ-панель и управление

Управление доступно **двумя способами** (как в ТЗ: бот или веб):

| Способ | Как открыть | Что можно |
|---|---|---|
| **Веб-панель** | http://localhost:8080 → вкладка «Админ» | Статус worker, очередь, scene verify, recover stale |
| **Telegram** | `/status` — всем; `/admin` — только `ADMIN_USERS` | Тот же статус + кнопка «Восстановить зависшие» |

**Где найти API:**
- Swagger UI: **http://localhost:8080/docs** — интерактивная документация, все эндпоинты
- OpenAPI JSON: http://localhost:8080/openapi.json
- Если в `.env` задан `API_KEY` — заголовок `X-API-Key: ваш_ключ` на всех `/api/v1/*`

**Админ API:**
- `GET /api/v1/admin/dashboard` — worker, очередь, проверка мокапов
- `POST /api/v1/admin/recover-stale` — вернуть зависшие задачи из `processing/` в `pending/`

**Портрет API** (отдельный сервис): http://localhost:8090/docs  
- `POST /generate` — генерация JPEG по полям ВУ  
- В `.env`: `OPENAI_API_KEY` для DALL·E, или `PORTRAIT_FALLBACK=1` для офлайн-заглушки

## Полный запуск (Windows)

```powershell
cd D:\codes\otris
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
# Заполните минимум:
#   BOT_TOKEN=...           — от @BotFather
#   ALLOWED_USERS=681094413 — ваш Telegram user_id
#   ADMIN_USERS=681094413   — кто может /admin (по умолчанию = ALLOWED_USERS)
#   PHOTOSHOP_EXE=C:\Program Files\Adobe\...\Photoshop.exe
#   OPENAI_API_KEY=sk-...   — или PORTRAIT_FALLBACK=1
```

**Терминал 1 — API + веб-админка:**
```powershell
.\.venv\Scripts\uvicorn api.main:app --port 8080
# → http://localhost:8080
# → http://localhost:8080/docs
```

**Терминал 2 — Portrait API:**
```powershell
.\.venv\Scripts\uvicorn portrait_api.app:app --port 8090
```

**Терминал 3 — Telegram-бот:**
```powershell
cd vu-qa-bot
..\.venv\Scripts\python vu_qa_bot.py
```

**Терминал 4 — Render worker (Windows + Photoshop):**
```powershell
.\scripts\start_render_worker.ps1
# или: cd vu-qa-bot; ..\.venv\Scripts\python render_worker.py
```

**Docker (API + бот + portrait, без Photoshop):**
```powershell
docker compose up -d --build
# Worker Photoshop — только на Windows-хосте вне Docker
```

## Что нужно для production

| Компонент | Где | Обязательно |
|---|---|---|
| `.env` | корень `otris/` | `BOT_TOKEN`, `ALLOWED_USERS` |
| Photoshop + worker | Windows VPS | `PHOTOSHOP_EXE`, PSB-файлы мокапов |
| Общая папка `queue/` + `output/` | NFS/SMB между API и worker | для server mode |
| ИИ-портрет | `OPENAI_API_KEY` или fallback | для `/portrait` и smart object Photo |
| API key | `API_KEY` в `.env` | защита REST в production |

**Команды бота:** `/me` · `/render` · `/portrait` · `/status` · `/admin` · `/forget`
