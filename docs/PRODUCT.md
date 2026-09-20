# VU Studio — бот и панель

Рабочий контур: синтетическая запись водительского удостоверения → текстовый блок → Photoshop (мокап «рука + фон») → JPG лицевой и оборотной сторон + PSD.

Продакшен: Windows + Photoshop 2026, API за Caddy (`https://photoshop.arix.vu`). Бот работает polling.

## Что умеет продукт

- Генерация блока полей ВУ по ФИО + дате + месту рождения.
- Отрисовка в мокап: рука, фон 1–10, портрет в smart object `Photo`.
- Загруженное селфи прогоняется через OpenRouter (NB 2 Lite): тот же человек, серый фон, вид фото на документ.
- Генерация портрета с нуля по промпту/возрасту **не используется**.
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

- Нужно **селфи**: бот/панель принимают фото → OpenRouter (`google/gemini-3.1-flash-lite-image`, NB 2 Lite) делает портрет 4:3 на сером фоне (лицо как на исходнике).
- Fallback edit: OpenAI `images/edits`, если OpenRouter недоступен.
- Генерация «с нуля» по году/описанию отключена.
- Если ИИ недоступен, фото кропается как есть (без подмены лица заглушкой).

Исходник: `output/portraits/user_{id}_src.*`. Результат: `user_{id}.jpg`.
Панель пишет `user_web_{uuid}.jpg`, чтобы параллельные загрузки не перетирали друг друга.

ИИ-кадр не режется сверху на 72% (это только fallback для обычного селфи без ИИ).

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
- `Back` — оборот (группа `Text`: в графах 10/11 даты открытия и окончания для открытых категорий, обычно B, B1, M).
- На лицевой группу `Text` скрываем, на обороте оставляем видимой.

Оборот ищется как слой `Back` и как группа `Text` внутри карточки / wrapper SO. Имя слоя можно поменять в `vu-qa-bot/templates/mockup_hand.json` → `scene.back_smart_objects`.

JSX: `photoshop/render.jsx`, версия `2026-09-16.1`. На VPS копировать этот файл и **перезапустить worker**. Оборот: даты 10/11 только Python на JPG (`back_jpg_dates.py`), без сценового оверлея и без замазывания бланка. Фон: пресеты 1–10 или свой (`custom_background_path`). Портрет в Photo — cover без полей.

## Категории

| Где | Набор |
|---|---|
| Бот / панель / `POST /api/v1/generate` | только B, B1, M |
| CLI датасет, `/api/v1/dataset`, тесты ТЗ | полный алфавит (A, C, D…) |

Константа: `MOCKUP_CATEGORIES` в `vu_testdata.py`.

## Переменные портрета

| Переменная | Смысл |
|---|---|
| `PORTRAIT_PROVIDER` | `auto` / `openrouter` / `openai` / `fallback` |
| `OPENROUTER_API_KEY` | ключ OpenRouter Images API (селфи → портрет) |
| `PORTRAIT_OPENROUTER_MODEL` | `google/gemini-3.1-flash-lite-image` |
| `OPENAI_API_KEY` | опциональный fallback edit |
| `PORTRAIT_OPENAI_MODEL` | `gpt-image-1` |
| `PORTRAIT_TIMEOUT` | сек, edit обычно 30–120 |
| `PORTRAIT_FALLBACK` | `1` только для dev: кроп без ИИ |

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

Для портрета на проде обязателен `OPENROUTER_API_KEY` в `.env` (модель NB 2 Lite). Без ключа edit уйдёт в OpenAI fallback, если задан `OPENAI_API_KEY`.

## Тесты

```powershell
cd D:\codes\otris\vu-qa-bot
..\.venv\Scripts\python -m unittest test_portrait.py test_mockup_categories.py test_task4.py test_html_entities.py test_tg_ui.py
```
