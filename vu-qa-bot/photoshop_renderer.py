#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Рендер PSD + JPG через Adobe Photoshop (Windows COM / CLI)."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from layer_values import build_photoshop_job
from mockup_registry import get_mockup
from render_models import RenderTask
from renderer_stub import DocumentRenderer, RenderJob, RenderResult
from text_parser import TextParseError, parse_client_block

log = logging.getLogger("photoshop_renderer")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_JSX = ROOT / "photoshop" / "render.jsx"

PHOTOSHOP_CANDIDATES = [
    r"C:\Program Files\Adobe\Adobe Photoshop 2026\Photoshop.exe",
    r"C:\Program Files\Adobe\Adobe Photoshop 2025\Photoshop.exe",
    r"C:\Program Files\Adobe\Adobe Photoshop 2024\Photoshop.exe",
    r"C:\Program Files\Adobe\Adobe Photoshop 2023\Photoshop.exe",
    r"C:\Program Files\Adobe\Adobe Photoshop CC 2019\Photoshop.exe",
]


@dataclass(frozen=True)
class RenderSettings:
    jsx_path: Path
    output_dir: Path
    photoshop_exe: Path | None = None

    @classmethod
    def from_env(cls) -> RenderSettings:
        import os

        jsx = Path(os.getenv("PHOTOSHOP_JSX", str(DEFAULT_JSX)))
        out = Path(os.getenv("RENDER_OUTPUT_DIR", str(ROOT / "output")))
        exe_raw = os.getenv("PHOTOSHOP_EXE", "").strip()
        exe = Path(exe_raw) if exe_raw else _find_photoshop()
        out.mkdir(parents=True, exist_ok=True)
        return cls(jsx_path=jsx, output_dir=out, photoshop_exe=exe)


def _find_photoshop() -> Path | None:
    for candidate in PHOTOSHOP_CANDIDATES:
        if Path(candidate).is_file():
            return Path(candidate)
    return None


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _jsx_log_path(job_file: Path) -> Path:
    return Path(str(job_file) + ".log")


def _read_jsx_log(job_file: Path) -> str:
    p = _jsx_log_path(job_file)
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8", errors="replace").strip()[-3000:]


def _format_ps_error(job_file: Path, err: Exception) -> str:
    msg = str(err)
    jsx_log = _read_jsx_log(job_file)
    if jsx_log:
        msg = f"{msg}\nJSX log ({_jsx_log_path(job_file).name}):\n{jsx_log}"
    return msg


class PhotoshopRenderer:
    """DocumentRenderer: RenderTask или текстовый блок → PSD + JPG."""

    def __init__(self, settings: RenderSettings | None = None):
        self.settings = settings or RenderSettings.from_env()

    def render_task(self, task: RenderTask) -> RenderResult:
        from portrait_service import resolve_portrait

        portrait = resolve_portrait(task)
        if portrait:
            task.options.portrait_path = portrait

        mockup = get_mockup(task.options.mockup)
        mockup_path = mockup.resolve_path()
        if not mockup_path.is_file():
            return RenderResult(
                job=RenderJob(record=None, text_block=task.text_block),
                output_paths=[],
                status="error",
                message=f"Мокап не найден: {mockup_path}",
            )

        if not self.settings.jsx_path.is_file():
            return RenderResult(
                job=RenderJob(record=None, text_block=task.text_block),
                output_paths=[],
                status="error",
                message=f"JSX-скрипт не найден: {self.settings.jsx_path}",
            )

        work_id = task.job_id or uuid.uuid4().hex[:8]
        base = self.settings.output_dir / f"vu_{_stamp()}_{work_id}"
        job_file = base.with_suffix(".job.json")
        mockup_path = get_mockup(task.options.mockup).resolve_path()
        ext = mockup_path.suffix.lower() or ".psd"
        psd_out = base.with_suffix(ext)
        jpg_out = base.with_suffix(".jpg")

        try:
            job_data = build_photoshop_job(task, output_psd=psd_out, output_jpg=jpg_out)
        except ValueError as e:
            return RenderResult(
                job=RenderJob(record=None, text_block=task.text_block),
                output_paths=[],
                status="error",
                message=str(e),
            )

        from template_cache import WORKER_TEMPLATE_CACHE

        job_data = WORKER_TEMPLATE_CACHE.apply(job_data)
        job_file.write_text(json.dumps(job_data, ensure_ascii=False, indent=2), encoding="utf-8")

        try:
            self._run_photoshop(job_file)
        except Exception as e:
            outputs = [p for p in (psd_out, jpg_out) if p.is_file()]
            if len(outputs) >= 2:
                log.warning("Photoshop reported error but output files exist: %s", e)
            else:
                log.exception("Photoshop render failed")
                return RenderResult(
                    job=RenderJob(record=None, text_block=task.text_block),
                    output_paths=outputs,
                    status="error",
                    message=_format_ps_error(job_file, e),
                )

        outputs = [p for p in (psd_out, jpg_out) if p.is_file()]
        if len(outputs) < 2:
            return RenderResult(
                job=RenderJob(record=None, text_block=task.text_block),
                output_paths=outputs,
                status="error",
                message="Photoshop завершился без выходных файлов. Проверьте PHOTOSHOP_EXE.",
            )

        task.psd_path = str(psd_out)
        task.jpg_path = str(jpg_out)
        return RenderResult(
            job=RenderJob(record=None, text_block=task.text_block),
            output_paths=outputs,
            status="ok",
            message="Готово",
        )

    def render(self, job: RenderJob) -> RenderResult:
        try:
            parse_client_block(job.text_block)
        except TextParseError as e:
            return RenderResult(job=job, output_paths=[], status="error", message=str(e))

        from render_models import RenderOptions, RenderTask

        task = RenderTask.create(
            job.text_block,
            options=RenderOptions(
                mockup=getattr(job, "mockup", "hand") or "hand",
                background=getattr(job, "background", 1) or 1,
                portrait_path=getattr(job, "portrait_path", None),
                generate_portrait=getattr(job, "generate_portrait", False),
            ),
        )
        return self.render_task(task)

    def _run_photoshop(self, job_file: Path) -> None:
        prefer_cli = os.getenv("PHOTOSHOP_USE_CLI", "0").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        order = ("cli", "com") if prefer_cli else ("com", "cli")
        errors: list[str] = []

        for mode in order:
            try:
                ok = self._run_via_cli(job_file) if mode == "cli" else self._run_via_com(job_file)
                if ok:
                    return
                errors.append(f"{mode}: failed without exception")
            except Exception as e:
                errors.append(f"{mode}: {e}")
                log.warning("Photoshop %s failed: %s", mode, e)

        jsx_log = _read_jsx_log(job_file)
        detail = "; ".join(errors)
        if jsx_log:
            detail = f"{detail}\nJSX log:\n{jsx_log}"
        raise RuntimeError(detail or "Photoshop render failed")

    def _wrapper_jsx(self, job_file: Path) -> Path:
        job_path = str(job_file.resolve()).replace("\\", "/")
        jsx_main = str(self.settings.jsx_path.resolve()).replace("\\", "/")
        wrapper = job_file.with_suffix(".run.jsx")
        wrapper.write_text(
            f'var OTRIS_JOB_PATH = "{job_path}";\n$.evalFile("{jsx_main}");\n',
            encoding="utf-8",
        )
        return wrapper

    def _run_via_com(self, job_file: Path) -> bool:
        try:
            import win32com.client  # type: ignore[import-untyped]
        except ImportError:
            return False

        wrapper = self._wrapper_jsx(job_file)
        script = f'$.evalFile("{str(wrapper.resolve()).replace(chr(92), "/")}");'
        ps = win32com.client.Dispatch("Photoshop.Application")
        ps.DisplayDialogs = 3
        ps.DoJavaScript(script)
        return True

    def _run_via_cli(self, job_file: Path) -> bool:
        exe = self.settings.photoshop_exe
        if not exe or not exe.is_file():
            log.error("PHOTOSHOP_EXE not found for CLI mode")
            return False
        wrapper = self._wrapper_jsx(job_file)
        wrapper_s = str(wrapper.resolve())
        # PS 2026: plain path often works better than -r on Windows Server.
        attempts = (
            [str(exe), wrapper_s],
            [str(exe), "-r", wrapper_s],
        )
        last = ""
        for args in attempts:
            try:
                r = subprocess.run(
                    args,
                    capture_output=True,
                    text=True,
                    timeout=900,
                )
                if r.returncode == 0:
                    return True
                last = (r.stderr or r.stdout or f"exit code {r.returncode}").strip()
                log.error("Photoshop CLI %s -> %s", args, last[:800])
            except Exception as e:
                last = str(e)
                log.error("Photoshop CLI exception: %s", e)
        if last:
            raise RuntimeError(last)
        return False


def get_renderer() -> DocumentRenderer:
    settings = RenderSettings.from_env()
    if settings.photoshop_exe or _com_available():
        return PhotoshopRenderer(settings)
    from renderer_stub import StubRenderer

    return StubRenderer()


def _com_available() -> bool:
    try:
        import win32com.client  # type: ignore[import-untyped]

        win32com.client.Dispatch("Photoshop.Application")
        return True
    except Exception:
        return False
