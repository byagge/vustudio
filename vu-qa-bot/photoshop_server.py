#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Серверная обработка Photoshop (task1.md § «Серверная обработка»).

Архитектура:
  бот / API → файловая очередь → render_worker (Windows) → Photoshop → output/

Бот и API только ставят задачи и читают результат; Photoshop запускается
исключительно в render_worker на Windows-машине с одним инстансом и lock.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


class RenderMode(str, Enum):
    """local — Photoshop в том же процессе (CLI на Windows); server — только очередь."""

    LOCAL = "local"
    SERVER = "server"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def render_mode() -> RenderMode:
    raw = os.getenv("RENDER_MODE", "server").strip().lower()
    if raw in {"local", "direct", "inline"}:
        return RenderMode.LOCAL
    return RenderMode.SERVER


def is_server_mode() -> bool:
    return render_mode() == RenderMode.SERVER


def queue_dir() -> Path:
    p = Path(os.getenv("RENDER_QUEUE_DIR", str(ROOT / "queue")))
    p.mkdir(parents=True, exist_ok=True)
    return p


def output_dir() -> Path:
    p = Path(os.getenv("RENDER_OUTPUT_DIR", str(ROOT / "output")))
    p.mkdir(parents=True, exist_ok=True)
    return p


def heartbeat_path() -> Path:
    return queue_dir() / ".worker_heartbeat.json"


def lock_path() -> Path:
    return queue_dir() / ".photoshop.lock"


def heartbeat_ttl_sec() -> float:
    return float(os.getenv("RENDER_WORKER_HEARTBEAT_TTL", "90"))


def stale_job_sec() -> float:
    return float(os.getenv("RENDER_STALE_JOB_SEC", "900"))


@dataclass
class QueueStats:
    pending: int = 0
    processing: int = 0
    done: int = 0
    failed: int = 0

    @property
    def total(self) -> int:
        return self.pending + self.processing + self.done + self.failed


@dataclass
class WorkerHeartbeat:
    worker_id: str = "worker-1"
    pid: int = 0
    updated_at: str = ""
    status: str = "unknown"
    current_job_id: str | None = None
    photoshop_exe: str | None = None
    photoshop_available: bool = False
    template_cache: bool = False
    jobs_processed: int = 0
    last_job_ms: int | None = None
    last_error: str | None = None
    hostname: str = ""

    def age_sec(self) -> float | None:
        if not self.updated_at:
            return None
        try:
            ts = datetime.fromisoformat(self.updated_at.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds())
        except ValueError:
            return None

    def is_alive(self, ttl: float | None = None) -> bool:
        age = self.age_sec()
        if age is None:
            return False
        return age <= (ttl if ttl is not None else heartbeat_ttl_sec())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkerHeartbeat:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class RenderServerStatus:
    mode: str
    worker_alive: bool
    worker: WorkerHeartbeat | None
    queue: QueueStats
    photoshop_configured: bool
    photoshop_available: bool
    output_dir: str
    queue_dir: str
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "worker_alive": self.worker_alive,
            "worker": self.worker.to_dict() if self.worker else None,
            "queue": asdict(self.queue),
            "photoshop_configured": self.photoshop_configured,
            "photoshop_available": self.photoshop_available,
            "output_dir": self.output_dir,
            "queue_dir": self.queue_dir,
            "message": self.message,
        }


def write_heartbeat(hb: WorkerHeartbeat) -> None:
    hb.updated_at = _now_iso()
    heartbeat_path().write_text(
        json.dumps(hb.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_heartbeat() -> WorkerHeartbeat | None:
    path = heartbeat_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return WorkerHeartbeat.from_dict(data)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def check_photoshop_exe() -> tuple[bool, Path | None]:
    from photoshop_renderer import RenderSettings, _find_photoshop

    exe = RenderSettings.from_env().photoshop_exe or _find_photoshop()
    if exe and exe.is_file():
        return True, exe
    return False, exe


def check_photoshop_com() -> bool:
    try:
        import win32com.client  # type: ignore[import-untyped]

        win32com.client.Dispatch("Photoshop.Application")
        return True
    except Exception:
        return False


def photoshop_available() -> bool:
    ok, _ = check_photoshop_exe()
    if not ok:
        return False
    if os.name == "nt":
        return check_photoshop_com()
    return ok


def queue_stats() -> QueueStats:
    from render_queue import RenderQueue

    q = RenderQueue(queue_dir())
    raw = q.stats()
    return QueueStats(**raw)


def queue_jobs(status: str = "", limit: int = 100) -> list[dict]:
    from render_queue import RenderQueue

    allowed = ("pending", "processing", "done", "failed")
    statuses = (status,) if status in allowed else ()
    return RenderQueue(queue_dir()).list_jobs(statuses=statuses, limit=limit)


def recover_stale_jobs(max_age_sec: float | None = None) -> int:
    from render_queue import RenderQueue

    return RenderQueue(queue_dir()).recover_stale(max_age_sec or stale_job_sec())


def resolve_output_file(path: str | Path) -> Path:
    """Безопасный путь к файлу рендера (только внутри output/)."""
    file_path = Path(path).resolve()
    root = output_dir().resolve()
    try:
        file_path.relative_to(root)
    except ValueError as e:
        raise PermissionError(f"Path outside output dir: {path}") from e
    if not file_path.is_file():
        raise FileNotFoundError(str(file_path))
    return file_path


def get_server_status() -> RenderServerStatus:
    hb = read_heartbeat()
    alive = hb.is_alive() if hb else False
    configured, _ = check_photoshop_exe()
    ps_ok = hb.photoshop_available if hb and alive else (photoshop_available() if configured else False)
    stats = queue_stats()

    if is_server_mode():
        if alive:
            msg = "Worker online"
        elif stats.processing and stats.pending:
            msg = "Worker offline; есть задачи в очереди"
        elif stats.processing:
            msg = "Worker offline; задача зависла в processing"
        else:
            msg = "Worker offline — запустите render_worker.py на Windows"
    else:
        msg = "RENDER_MODE=local — Photoshop может запускаться локально"

    return RenderServerStatus(
        mode=render_mode().value,
        worker_alive=alive,
        worker=hb,
        queue=stats,
        photoshop_configured=configured,
        photoshop_available=ps_ok,
        output_dir=str(output_dir()),
        queue_dir=str(queue_dir()),
        message=msg,
    )


def ensure_server_ready() -> str | None:
    """Проверка перед постановкой в очередь. None = OK."""
    if not is_server_mode():
        return None
    status = get_server_status()
    if status.queue.processing and not status.worker_alive:
        recover_stale_jobs()
        status = get_server_status()
    if status.queue.pending > 100:
        return "Очередь переполнена (>100 pending)"
    return None


def build_worker_heartbeat(
    worker_id: str,
    *,
    status: str = "idle",
    current_job_id: str | None = None,
    jobs_processed: int = 0,
    last_job_ms: int | None = None,
    last_error: str | None = None,
) -> WorkerHeartbeat:
    import socket

    configured, exe = check_photoshop_exe()
    from template_cache import TemplateCache

    return WorkerHeartbeat(
        worker_id=worker_id,
        pid=os.getpid(),
        status=status,
        current_job_id=current_job_id,
        photoshop_exe=str(exe) if exe else None,
        photoshop_available=photoshop_available() if configured else False,
        template_cache=TemplateCache.enabled(),
        jobs_processed=jobs_processed,
        last_job_ms=last_job_ms,
        last_error=last_error,
        hostname=socket.gethostname(),
    )
