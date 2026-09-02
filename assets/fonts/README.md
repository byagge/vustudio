# Шрифты бланка ВУ для Photoshop-render

| Файл | PostScript | Назначение |
|---|---|---|
| `Z_NOMER.TTF` | `znomer` | Полный номер (`04 76 656492`) |
| `Z_NOMER0.TTF` | `z_nomer0` | Серия и номер по частям (`04`, `76`, `656492`) |

Маппинг полей → шрифт: `manifest.json` и `vu-qa-bot/templates/mockup_*.json` → `fonts.layer_fields`.

Worker загружает TTF через `AddFontResourceEx` перед запуском Photoshop.  
JSX после подстановки текста принудительно выставляет PostScript-имя (`render.jsx` → `applyFontRules`).

Проверка: `python scripts/verify_fonts.py`
