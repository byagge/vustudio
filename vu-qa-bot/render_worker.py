#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render-worker: серверная обработка Photoshop (Windows VPS)."""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

import load_env  # noqa: F401 — .env до RenderSettings.from_env()

from photoshop_renderer import PhotoshopRenderer, RenderSettings
from photoshop_server import build_worker_heartbeat, check_photoshop_exe, lock_path, queue_dir, recover_stale_jobs, stale_job_sec, write_heartbeat
from render_queue import RenderQueue

log = logging.getLogger("render_worker")


def _acquire_lock(path: Path):
    """Блокировка одного инстанса Photoshop (task1.md)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+b")
    try:
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fh
    except (OSError, ImportError):
        fh.close()
        return None


def _release_lock(lock) -> None:
    if lock is None:
        return
    try:
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    finally:
        lock.close()


def main() -> int:
    qdir = queue_dir()
    poll = float(os.getenv("RENDER_WORKER_POLL", "2"))
    worker_id = os.getenv("RENDER_WORKER_ID", "worker-1")
    heartbeat_sec = float(os.getenv("RENDER_WORKER_HEARTBEAT", "15"))

    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    recovered = recover_stale_jobs(stale_job_sec())
    if recovered:
        log.warning("recovered %s stale job(s) from processing", recovered)

    queue = RenderQueue(qdir)
    renderer = PhotoshopRenderer(RenderSettings.from_env())
    lock_file = lock_path()

    configured, exe = check_photoshop_exe()
    if not configured:
        log.error(
            "Photoshop не найден. Укажите PHOTOSHOP_EXE в .env (ожидался exe на Windows)."
        )
        write_heartbeat(
            build_worker_heartbeat(
                worker_id,
                status="error",
                last_error="Photoshop executable not found",
            )
        )
        return 2

    from font_registry import ensure_fonts_installed

    font_errors = ensure_fonts_installed()
    if font_errors:
        log.error("fonts: %s", "; ".join(font_errors))
        write_heartbeat(
            build_worker_heartbeat(
                worker_id,
                status="error",
                last_error="; ".join(font_errors),
            )
        )
        return 3

    jobs_processed = 0
    last_heartbeat = 0.0
    log.info(
        "worker %s started queue=%s photoshop=%s",
        worker_id,
        qdir,
        exe,
    )

    while True:
        now = time.time()
        if now - last_heartbeat >= heartbeat_sec:
            write_heartbeat(
                build_worker_heartbeat(worker_id, status="idle", jobs_processed=jobs_processed)
            )
            last_heartbeat = now

        task = queue.claim(worker_id)
        if not task:
            time.sleep(poll)
            continue

        lock = _acquire_lock(lock_file)
        if lock is None:
            log.warning("Photoshop busy, requeue job %s", task.job_id)
            queue.requeue(task)
            time.sleep(poll)
            continue

        write_heartbeat(
            build_worker_heartbeat(
                worker_id,
                status="processing",
                current_job_id=task.job_id,
                jobs_processed=jobs_processed,
            )
        )
        last_heartbeat = time.time()

        log.info(
            "processing job %s mockup=%s bg=%s",
            task.job_id,
            task.options.mockup,
            task.options.background,
        )
        started = time.perf_counter()
        last_error: str | None = None
        try:
            result = renderer.render_task(task)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            if result.status == "ok":
                for p in result.output_paths:
                    if p.suffix.lower() in {".jpg", ".jpeg"}:
                        task.jpg_path = str(p)
                    elif p.suffix.lower() in {".psd", ".psb"}:
                        task.psd_path = str(p)
                queue.complete(task)
                jobs_processed += 1
                log.info("job %s done in %sms", task.job_id, elapsed_ms)
                write_heartbeat(
                    build_worker_heartbeat(
                        worker_id,
                        status="idle",
                        jobs_processed=jobs_processed,
                        last_job_ms=elapsed_ms,
                    )
                )
            else:
                last_error = result.message
                queue.fail(task, result.message)
                log.error("job %s failed: %s", task.job_id, result.message)
                write_heartbeat(
                    build_worker_heartbeat(
                        worker_id,
                        status="idle",
                        jobs_processed=jobs_processed,
                        last_job_ms=elapsed_ms,
                        last_error=last_error,
                    )
                )
        except Exception as e:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            log.exception("job %s crashed", task.job_id)
            queue.fail(task, str(e))
            write_heartbeat(
                build_worker_heartbeat(
                    worker_id,
                    status="idle",
                    jobs_processed=jobs_processed,
                    last_job_ms=elapsed_ms,
                    last_error=str(e),
                )
            )
        finally:
            _release_lock(lock)
            last_heartbeat = 0.0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        sys.exit(0)
