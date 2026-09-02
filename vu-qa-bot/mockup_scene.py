#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Смена фона и варианта мокапа (рука+фоны) — task1 § «Фон/мокап».

Мокап «Мокап (рука+фоны).psb»:
  - фон: слои «Вариант 1» … «Вариант 10» внутри SO «Меняющийся фон (Ред)»
  - композиция: «Рука+док» (hand) vs «Оригинал» (original)

Маленький blank — без scene (supports_background=False).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mockup_registry import MOCKUPS, MockupSpec, get_mockup
from render_models import MockupKind, RenderOptions
from template_loader import load_template

DEFAULT_BG_COUNT = 10


def _psd_tools_available() -> bool:
    try:
        import psd_tools  # noqa: F401

        return True
    except ImportError:
        return False


@dataclass(frozen=True)
class BackgroundOption:
    id: int
    layer_name: str


@dataclass(frozen=True)
class MockupInfo:
    kind: str
    title: str
    supports_background: bool
    supports_portrait: bool
    mockup_variant: str | None
    backgrounds: tuple[BackgroundOption, ...]


def scene_from_template(template: dict) -> dict[str, Any]:
    return dict(template.get("scene") or {})


def background_count(scene: dict[str, Any]) -> int:
    return int(scene.get("background_count") or DEFAULT_BG_COUNT)


def background_layer_name(scene: dict[str, Any], bg_id: int) -> str:
    prefix = scene.get("background_prefix") or "Вариант "
    return f"{prefix}{bg_id}"


def list_backgrounds(template_name: str = "mockup_hand") -> list[BackgroundOption]:
    scene = scene_from_template(load_template(template_name))
    count = background_count(scene)
    return [BackgroundOption(i, background_layer_name(scene, i)) for i in range(1, count + 1)]


def list_mockups_info() -> list[MockupInfo]:
    out: list[MockupInfo] = []
    for kind, spec in MOCKUPS.items():
        bgs: tuple[BackgroundOption, ...] = ()
        if spec.supports_background:
            bgs = tuple(list_backgrounds(spec.template))
        out.append(
            MockupInfo(
                kind=kind,
                title=spec.title,
                supports_background=spec.supports_background,
                supports_portrait=spec.supports_portrait,
                mockup_variant=spec.mockup_variant,
                backgrounds=bgs,
            )
        )
    return out


def validate_scene_options(opts: RenderOptions) -> list[str]:
    """Проверка mockup + background перед постановкой в очередь."""
    errors: list[str] = []
    spec = get_mockup(opts.mockup)
    if opts.mockup not in MOCKUPS:
        errors.append(f"Неизвестный мокап: {opts.mockup}")
        return errors

    tpl = load_template(spec.template)
    scene = scene_from_template(tpl)
    count = background_count(scene)

    if not spec.supports_background:
        return errors

    if opts.background < 1 or opts.background > count:
        errors.append(f"Фон должен быть от 1 до {count}, получено {opts.background}")

    if spec.mockup_variant not in (None, "hand", "original"):
        errors.append(f"Некорректный вариант мокапа: {spec.mockup_variant}")

    required = []
    if spec.supports_background:
        required.append(("background_smart_object", "SO фона"))
    if spec.mockup_variant:
        if spec.mockup_variant == "hand":
            required.extend([("hand_group", "группа руки"), ("original_layer", "слой оригинала")])
        else:
            required.extend([("hand_group", "группа руки"), ("original_layer", "слой оригинала")])

    for key, label in required:
        if key in scene and not scene[key]:
            errors.append(f"scene.{key} ({label}) не задан в шаблоне")

    return errors


def build_scene_job_fields(opts: RenderOptions, template: dict | None = None) -> dict[str, Any]:
    """
    Поля job JSON для JSX: background, mockup_variant, scene.
    """
    spec = get_mockup(opts.mockup)
    tpl = template or load_template(spec.template)
    scene = scene_from_template(tpl)

    if not spec.supports_background:
        return {
            "mockup_variant": None,
            "background": None,
            "scene": {},
        }

    bg = max(1, min(background_count(scene), int(opts.background or 1)))
    return {
        "mockup_variant": spec.mockup_variant,
        "background": bg,
        "scene": scene,
    }


def scene_summary(opts: RenderOptions) -> str:
    spec = get_mockup(opts.mockup)
    if not spec.supports_background:
        return f"{spec.title} (без фона/руки)"
    variant = "рука+док" if spec.mockup_variant == "hand" else "оригинал"
    scene = scene_from_template(load_template(spec.template))
    layer = background_layer_name(scene, opts.background)
    return f"{spec.title}, {variant}, фон #{opts.background} ({layer})"


def normalize_options_for_mockup(opts: RenderOptions) -> RenderOptions:
    """При смене мокапа — сброс неподдерживаемых опций."""
    normalized = opts.normalized()
    spec = get_mockup(normalized.mockup)
    portrait_path = normalized.portrait_path
    generate_portrait = normalized.generate_portrait
    if not spec.supports_portrait:
        portrait_path = None
        generate_portrait = False
    bg = normalized.background
    if not spec.supports_background:
        bg = 1
    return RenderOptions(
        mockup=normalized.mockup,
        background=bg,
        portrait_path=portrait_path,
        generate_portrait=generate_portrait,
    )


def discover_background_layers(psb_path) -> list[str]:
    """Найти слои «Вариант N» в PSB (для verify_scene)."""
    from pathlib import Path

    if not _psd_tools_available():
        return []
    from psb_utils import iter_nested_psbs

    path = Path(psb_path)
    if not path.is_file():
        return []
    names: set[str] = set()
    for _p, psd in iter_nested_psbs(path):
        for layer in psd.descendants():
            n = layer.name
            if n.startswith("Вариант ") or n.startswith("Variant "):
                names.add(n)
    return sorted(names, key=lambda s: int(s.split()[-1]) if s.split()[-1].isdigit() else 0)


def discover_layer_names(psb_path) -> set[str]:
    """Все имена слоёв во вложенных PSB (для verify scene keys)."""
    from pathlib import Path

    if not _psd_tools_available():
        return set()
    from psb_utils import iter_nested_psbs

    path = Path(psb_path)
    if not path.is_file():
        return set()
    names: set[str] = set()
    for _p, psd in iter_nested_psbs(path):
        for layer in psd.descendants():
            names.add(layer.name)
    return names


def verify_scene_template(template_name: str = "mockup_hand") -> dict[str, Any]:
    spec = next((s for s in MOCKUPS.values() if s.template == template_name), get_mockup("hand"))
    tpl = load_template(template_name)
    scene = scene_from_template(tpl)
    psb = spec.resolve_path()
    found = discover_background_layers(psb) if psb.is_file() else []
    expected = [background_layer_name(scene, i) for i in range(1, background_count(scene) + 1)]
    missing_bg = [n for n in expected if n not in found]

    layer_names = discover_layer_names(psb) if psb.is_file() else set()
    scene_keys = (
        ("background_smart_object", "SO фона"),
        ("hand_group", "группа руки"),
        ("original_layer", "слой оригинала"),
        ("photo_smart_object", "SO портрета"),
    )
    missing_layers: list[str] = []
    for key, _label in scene_keys:
        name = scene.get(key)
        if name and layer_names and name not in layer_names:
            missing_layers.append(name)

    psb_exists = psb.is_file()
    can_scan = psb_exists and _psd_tools_available()
    ok = psb_exists and can_scan and not missing_bg and not missing_layers
    if psb_exists and not _psd_tools_available():
        ok = False
    return {
        "template": template_name,
        "mockup": spec.kind,
        "psb": str(psb),
        "psb_exists": psb_exists,
        "psd_tools": _psd_tools_available(),
        "expected_backgrounds": expected,
        "found_backgrounds": found,
        "missing_backgrounds": missing_bg,
        "missing_layers": missing_layers,
        "hand_group": scene.get("hand_group"),
        "original_layer": scene.get("original_layer"),
        "background_so": scene.get("background_smart_object"),
        "photo_so": scene.get("photo_smart_object"),
        "layer_count": len(layer_names),
        "ok": ok,
    }


def verify_all_scenes() -> dict[str, Any]:
    """Проверка scene для hand/original (task4 §12)."""
    reports = {name: verify_scene_template(name) for name in ("mockup_hand",)}
    return {
        "ok": all(r["ok"] for r in reports.values()),
        "templates": reports,
    }
