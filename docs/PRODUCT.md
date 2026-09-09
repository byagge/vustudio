# VU Studio — бот и панель

Рабочий контур: синтетическая запись водительского удостоверения → текстовый блок → Photoshop (мокап «рука + фон») → JPG лицевой и оборотной сторон + PSD.

Продакшен: Windows + Photoshop 2026, API за Caddy (`https://photoshop.arix.vu`). Бот работает polling.

## Что умеет продукт

- Генерация блока полей ВУ по ФИО + дате + месту рождения.
- Отрисовка в мокап: рука, фон 1–10, портрет в smart object `Photo`.
- Загруженное фото всегда прогоняется через ИИ: тот же человек, фон вырезан, вид фото на документ.
- Генерация портрета с нуля, если своего фото нет.
- На мокапе рисуются категории **B, B1, M** — генератор больше не подмешивает C/A/D.
- После отрисовки приходят **два JPG**: лицевая (рука с картой) и оборот (если в PSB есть слой `Back`).

## Telegram-бот

Меню: Генерация, Отрисовка, Задачи, Портрет, Профиль, Статус, Панель (Mini App), Поддержка.

### Генерация

1. Пользователь пишет `ФИО + дата + место` (или берёт профиль).
2. Бот вызывает `make_valid(..., allowed_categories=B,B1,M)`.
3. Приходит блок полей + кнопка «Отрисовать».

Категории в пункте 9 и таблице оборота всегда `B, B1, M`. Лишние категории в данных больше не появляются.

### Портрет

- «Сгенерировать» — `gpt-image-1` text-to-image, серый студийный фон.
- Своё фото — `POST /v1/images/edits`: identity-preserving, `background=transparent`, затем композит на серый бланк 3×4 (390×507).
- Если OpenAI недоступен, фото кропается как есть (без подмены лица заглушкой).

Исходник: `output/portraits/user_{id}_src.*`. Результат: `user_{id}.jpg`.
Панель пишет `user_web_{uuid}.jpg`, чтобы параллельные загрузки не перетирали друг друга.

ИИ-кадр не режется сверху на 72% (это только fallback для обычного селфи без OpenAI).

### Отрисовка

Очередь `queue/` → `render_worker.py` → `photoshop/render.jsx`.

Выход:

| Файл | Что это |
|---|---|
| `vu_*_{job}.jpg` | Лицевая в мокапе |
| `vu_*_{job}_back.jpg` | Оборот (слой `Back`) |
| `vu_*_{job}.psb` | Редактируемый мокап |

PSD с руки ~гигабайт — в Telegram не уходит, скачивание из панели.

## Веб-панель

Статика `web/static/`, API `api/app.py`. Ключ: заголовок `X-API-Key`.

| Раздел | Действие |
|---|---|
| Генерация | `POST /api/v1/generate` — тот же набор категорий B/B1/M |
| Отрисовка | Блок + фон + портрет. Загрузка фото = ИИ-edit (10–60 сек) |
| Задачи | Очередь, превью лицевой и оборота, скачивание JPG/PSD |
| Статус | Worker, Photoshop, очередь |

Mini App «Панель» в боте только если `WEB_BASE_URL` — настоящий `https://`.

## Как устроена отрисовка сторон

Мокап `Мокап (рука+фоны).psb`:

- `Front` — лицевая (ФИО, даты, бейджи a/b/b1/m, Photo).
- `Back` — оборот (группа `Text`: даты категорий B/B1/M).
- На лицевой группу `Text` скрываем, на обороте оставляем видимой.

Если слоя `Back` в PSB нет, второй JPG не создаётся (в логе JSX: `back jpeg: no Back layer`). Имя слоя можно поменять в `vu-qa-bot/templates/mockup_hand.json` → `scene.back_smart_objects`.

JSX: `photoshop/render.jsx`, версия `2026-09-08.1`. На VPS копировать этот файл и **перезапустить worker**.

## Категории

| Где | Набор |
|---|---|
| Бот / панель / `POST /api/v1/generate` | только B, B1, M |
| CLI датасет, `/api/v1/dataset`, тесты ТЗ | полный алфавит (A, C, D…) |

Константа: `MOCKUP_CATEGORIES` в `vu_testdata.py`.

## Переменные портрета

| Переменная | Смысл |
|---|---|
| `PORTRAIT_PROVIDER` | `openai` / `auto` / `fallback` |
| `OPENAI_API_KEY` | ключ Images API |
| `PORTRAIT_OPENAI_MODEL` | `gpt-image-1` |
| `PORTRAIT_TIMEOUT` | сек, edit дольше generate |
| `PORTRAIT_FALLBACK` | `1` только для dev: кроп без OpenAI |

## Запуск (Windows)

```powershell
cd D:\codes\otris
# API
.\.venv\Scripts\uvicorn api.main:app --host 127.0.0.1 --port 8080
# Worker (отдельное окно)
.\.venv\Scripts\python vu-qa-bot\render_worker.py
# Бот (одно окно, не дублировать scheduled task)
.\.venv\Scripts\python vu-qa-bot\vu_qa_bot.py
```

После правок Python/JSX на VPS: скопировать файлы в `C:\Users\admin\Desktop\otris\` и перезапустить **один** процесс бота и worker.

## Тесты

```powershell
cd D:\codes\otris\vu-qa-bot
..\.venv\Scripts\python -m unittest test_portrait.py test_mockup_categories.py test_task4.py test_html_entities.py test_tg_ui.py
```
