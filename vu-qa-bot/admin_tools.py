#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Админ-операции: статус worker, очередь, восстановление задач."""
from __future__ import annotations

import threading
import time
from typing import Any

from photoshop_server import get_server_status, queue_stats, recover_stale_jobs
from mockup_scene import verify_all_scenes

# Разбор PSB занимает десятки секунд на больших мокапах, поэтому дашборд
# читает кэш, а само сканирование идёт в фоновом потоке.
SCENE_TTL_SEC = 900.0
_scene_lock = threading.Lock()
_scene_cache: dict[str, Any] = {"data": None, "ts": 0.0, "scanning": False}


def _scene_scan() -> dict[str, Any]:
    try:
        data = verify_all_scenes()
    except Exception as exc:  # noqa: BLE001 — отчёт не должен ронять панель
        data = {"ok": False, "templates": {}, "error": str(exc)}
    data["status"] = "ready"
    with _scene_lock:
        _scene_cache.update(data=data, ts=time.monotonic(), scanning=False)
    return data


def scene_report(refresh: bool = False) -> dict[str, Any]:
    """Отчёт по мокапам из кэша; при промахе запускает фоновое сканирование."""
    with _scene_lock:
        data = _scene_cache["data"]
        fresh = data is not None and (time.monotonic() - _scene_cache["ts"]) < SCENE_TTL_SEC
        if fresh and not refresh:
            return data
        if _scene_cache["scanning"]:
            return {"ok": None, "status": "scanning", "templates": {}}
        _scene_cache["scanning"] = True

    threading.Thread(target=_scene_scan, daemon=True).start()
    return {"ok": None, "status": "scanning", "templates": {}}


def admin_dashboard() -> dict[str, Any]:
    st = get_server_status()
    return {
        "server": st.to_dict(),
        "scene_verify": scene_report(),
        "queue": {
            "pending": st.queue.pending,
            "processing": st.queue.processing,
            "done": st.queue.done,
            "failed": st.queue.failed,
            "total": st.queue.total,
        },
    }


def admin_recover_stale() -> dict[str, Any]:
    n = recover_stale_jobs()
    st = get_server_status()
    return {
        "recovered": n,
        "queue": {
            "pending": st.queue.pending,
            "processing": st.queue.processing,
        },
    }


def format_status_text() -> str:
    st = get_server_status()
    q = st.queue
    worker = "online" if st.worker_alive else "OFFLINE"
    lines = [
        f"Режим: {st.mode}",
        f"Worker: {worker}",
        f"Очередь: pending={q.pending} processing={q.processing} done={q.done} failed={q.failed}",
        f"Photoshop: {'OK' if st.photoshop_available else 'нет'}",
    ]
    if st.worker and st.worker.current_job_id:
        lines.append(f"Job: {st.worker.current_job_id}")
    if st.message:
        lines.append(st.message)
    return "\n".join(lines)
