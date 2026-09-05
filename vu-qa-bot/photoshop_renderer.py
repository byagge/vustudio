#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Рендер PSD + JPG через Adobe Photoshop (Windows COM / CLI)."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import time
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

        jsx = _resolve_jsx()
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


def _resolve_jsx() -> Path:
    """Use packaged render.jsx if it is newer than PHOTOSHOP_JSX (stale VPS copy)."""
    env_raw = os.getenv("PHOTOSHOP_JSX", "").strip()
    env_jsx = Path(env_raw) if env_raw else None
    packaged = DEFAULT_JSX

    if env_jsx and env_jsx.is_file():
        try:
            same = packaged.is_file() and env_jsx.resolve() == packaged.resolve()
        except OSError:
            same = False
        if packaged.is_file() and not same:
            if packaged.stat().st_mtime > env_jsx.stat().st_mtime:
                log.warning(
                    "PHOTOSHOP_JSX is older than packaged render.jsx (%s → %s)",
                    env_jsx,
                    packaged,
                )
                return packaged
        return env_jsx
    if packaged.is_file():
        if env_jsx:
            log.warning("PHOTOSHOP_JSX not found (%s), using %s", env_jsx, packaged)
        return packaged
    return env_jsx or packaged


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


def _outputs_ready(*paths: Path) -> bool:
    return all(p.is_file() and p.stat().st_size > 0 for p in paths)


def _wait_outputs(*paths: Path, timeout: float = 8.0) -> bool:
    """Wait until output files exist, have size, and size stops growing."""
    start = time.time()
    last: tuple[int, ...] | None = None
    while time.time() - start < timeout:
        if _outputs_ready(*paths):
            sizes = tuple(p.stat().st_size for p in paths)
            if last == sizes:
                return True
            last = sizes
        else:
            last = None
        time.sleep(0.35)
    return _outputs_ready(*paths)


def _jsx_reported_ok(job_file: Path) -> bool:
    log_text = _read_jsx_log(job_file)
    if not log_text:
        return False
    lines = [ln.strip() for ln in log_text.splitlines() if ln.strip()]
    return bool(lines) and lines[-1] == "ok"


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
        except (ValueError, FileNotFoundError, OSError) as e:
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
            self._run_photoshop(job_file, psd_out, jpg_out)
        except Exception as e:
            if _wait_outputs(psd_out, jpg_out, timeout=8) or _outputs_ready(psd_out, jpg_out):
                log.warning("Photoshop reported error but output files exist: %s", e)
            else:
                log.exception("Photoshop render failed")
                return RenderResult(
                    job=RenderJob(record=None, text_block=task.text_block),
                    output_paths=[p for p in (psd_out, jpg_out) if p.is_file()],
                    status="error",
                    message=_format_ps_error(job_file, e),
                )

        if not _outputs_ready(psd_out, jpg_out):
            _wait_outputs(psd_out, jpg_out, timeout=8)
        if not _outputs_ready(psd_out, jpg_out):
            return RenderResult(
                job=RenderJob(record=None, text_block=task.text_block),
                output_paths=[p for p in (psd_out, jpg_out) if p.is_file()],
                status="error",
                message=_format_ps_error(
                    job_file,
                    RuntimeError("Photoshop завершился без выходных файлов. Проверьте PHOTOSHOP_EXE."),
                ),
            )

        task.psd_path = str(psd_out)
        task.jpg_path = str(jpg_out)
        return RenderResult(
            job=RenderJob(record=None, text_block=task.text_block),
            output_paths=[psd_out, jpg_out],
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

    def _run_photoshop(self, job_file: Path, psd_out: Path, jpg_out: Path) -> None:
        prefer_cli = os.getenv("PHOTOSHOP_USE_CLI", "0").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        errors: list[str] = []
        waited = False

        def saved() -> bool:
            """Files present and no longer growing. Waits the full grace period once."""
            nonlocal waited
            if _outputs_ready(psd_out, jpg_out):
                return _wait_outputs(psd_out, jpg_out, timeout=60)
            if waited:
                return False
            waited = True
            return _wait_outputs(psd_out, jpg_out, timeout=8)

        def run_cli() -> None:
            if not self._run_via_cli(job_file, psd_out, jpg_out) and not saved():
                raise RuntimeError("CLI finished without output files")

        def run_com() -> bool:
            """True if JS ran or files exist. False if COM cannot start Photoshop."""
            return self._run_via_com(job_file, psd_out, jpg_out)

        try:
            if prefer_cli:
                run_cli()
                if saved():
                    return
            else:
                com_started = run_com()
                if com_started:
                    if saved():
                        return
                    raise RuntimeError("COM finished without output files")
                run_cli()
                if saved():
                    return
        except Exception as e:
            if saved():
                log.warning("Photoshop error after successful save: %s", e)
                return
            errors.append(str(e))
            log.warning("Photoshop failed: %s", e)

        if saved():
            return

        jsx_log = _read_jsx_log(job_file)
        detail = "; ".join(errors) or "Photoshop render failed"
        if jsx_log:
            detail = f"{detail}\nJSX log:\n{jsx_log}"
        raise RuntimeError(detail)

    def _wrapper_jsx(self, job_file: Path) -> Path:
        job_path = str(job_file.resolve()).replace("\\", "/")
        jsx_main = str(self.settings.jsx_path.resolve()).replace("\\", "/")
        wrapper = job_file.with_suffix(".run.jsx")
        wrapper.write_text(
            "\n".join(
                [
                    "#target photoshop",
                    f'var OTRIS_JOB_PATH = "{job_path}";',
                    "try { app.displayDialogs = DialogModes.NO; } catch (e0) {}",
                    "try {",
                    f'    $.evalFile("{jsx_main}");',
                    "} catch (e) {",
                    "    try {",
                    f'        var _f = new File("{job_path}.log");',
                    '        _f.encoding = "UTF-8";',
                    '        _f.open("a");',
                    '        _f.writeln("wrapper catch: " + e);',
                    "        _f.close();",
                    "    } catch (e2) {}",
                    "}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return wrapper

    def _run_via_com(self, job_file: Path, psd_out: Path, jpg_out: Path) -> bool:
        """
        Run JSX via Photoshop COM.
        Returns False if COM/Photoshop cannot start (caller may try CLI).
        Returns True if the script was invoked. Raises if invoked and files are missing.
        """
        try:
            import win32com.client  # type: ignore[import-untyped]
        except ImportError:
            return False

        try:
            ps = win32com.client.Dispatch("Photoshop.Application")
        except Exception as e:
            log.warning("Photoshop COM Dispatch failed: %s", e)
            return False

        wrapper = self._wrapper_jsx(job_file)
        wrapper_js = str(wrapper.resolve()).replace("\\", "/")
        try:
            ps.DisplayDialogs = 3
        except Exception:
            pass

        script = f'$.evalFile("{wrapper_js}");'
        try:
            try:
                ps.DoJavaScript(script, None, 1)
            except TypeError:
                ps.DoJavaScript(script)
        except Exception as e:
            if _wait_outputs(psd_out, jpg_out, timeout=8) or (
                _jsx_reported_ok(job_file) and _outputs_ready(psd_out, jpg_out)
            ):
                log.warning("Photoshop COM exception after save (ignored): %s", e)
                return True
            raise

        if _wait_outputs(psd_out, jpg_out, timeout=8) or _outputs_ready(psd_out, jpg_out):
            return True
        raise RuntimeError("Photoshop COM finished without output files")

    def _run_via_cli(self, job_file: Path, psd_out: Path, jpg_out: Path) -> bool:
        exe = self.settings.photoshop_exe
        if not exe or not exe.is_file():
            log.error("PHOTOSHOP_EXE not found for CLI mode")
            return False
        wrapper = self._wrapper_jsx(job_file)
        wrapper_s = str(wrapper.resolve())
        args = [str(exe), "-r", wrapper_s]
        started = time.time()
        try:
            r = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=900,
            )
            elapsed = time.time() - started
            extra = 180.0 if r.returncode != 0 and elapsed < 8 else 8.0
            if _wait_outputs(psd_out, jpg_out, timeout=extra) or _outputs_ready(psd_out, jpg_out):
                if r.returncode != 0:
                    log.warning(
                        "Photoshop CLI exit %s after successful save",
                        r.returncode,
                    )
                return True
            last = (r.stderr or r.stdout or f"exit code {r.returncode}").strip()
            log.error("Photoshop CLI %s -> %s", args, last[:800])
            if last:
                raise RuntimeError(last)
        except Exception as e:
            if _wait_outputs(psd_out, jpg_out, timeout=8) or _outputs_ready(psd_out, jpg_out):
                log.warning("Photoshop CLI exception after save (ignored): %s", e)
                return True
            raise
        return _outputs_ready(psd_out, jpg_out)


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
