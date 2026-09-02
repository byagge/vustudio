#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Файловая очередь задач рендера (in-memory on disk, без Redis)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from render_models import JobStatus, RenderTask
from render_models import _now


class RenderQueue:
    def __init__(self, root: Path):
        self.root = root
        for name in ("pending", "processing", "done", "failed"):
            (root / name).mkdir(parents=True, exist_ok=True)

    def enqueue(self, task: RenderTask) -> RenderTask:
        task.status = JobStatus.PENDING.value
        task.updated_at = _now()
        self._write(self.root / "pending" / f"{task.job_id}.json", task)
        return task

    def claim(self, worker_id: str = "worker") -> RenderTask | None:
        pending = sorted((self.root / "pending").glob("*.json"), key=lambda p: p.stat().st_mtime)
        for path in pending:
            try:
                task = RenderTask.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, KeyError):
                path.unlink(missing_ok=True)
                continue
            proc = self.root / "processing" / f"{task.job_id}.json"
            try:
                os.replace(path, proc)
            except OSError:
                continue
            task.status = JobStatus.PROCESSING.value
            task.updated_at = _now()
            data = task.to_dict()
            data["worker"] = worker_id
            proc.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return task
        return None

    def complete(self, task: RenderTask) -> None:
        task.status = JobStatus.DONE.value
        task.updated_at = _now()
        self._move(task.job_id, "processing", "done", task)

    def fail(self, task: RenderTask, error: str) -> None:
        task.status = JobStatus.FAILED.value
        task.error = error
        task.updated_at = _now()
        src = "processing" if (self.root / "processing" / f"{task.job_id}.json").exists() else "pending"
        self._move(task.job_id, src, "failed", task)

    def get(self, job_id: str) -> RenderTask | None:
        for folder in ("pending", "processing", "done", "failed"):
            path = self.root / folder / f"{job_id}.json"
            if path.is_file():
                return RenderTask.from_dict(json.loads(path.read_text(encoding="utf-8")))
        return None

    def requeue(self, task: RenderTask) -> None:
        task.status = JobStatus.PENDING.value
        task.updated_at = _now()
        src = "processing" if (self.root / "processing" / f"{task.job_id}.json").exists() else "failed"
        if (self.root / src / f"{task.job_id}.json").exists():
            self._move(task.job_id, src, "pending", task)
        else:
            self.enqueue(task)

    def wait_done(self, job_id: str, timeout: float = 600, poll: float = 1.0) -> RenderTask | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            task = self.get(job_id)
            if task and task.status in {JobStatus.DONE.value, JobStatus.FAILED.value}:
                return task
            time.sleep(poll)
        return self.get(job_id)

    def stats(self) -> dict[str, int]:
        return {
            "pending": len(list((self.root / "pending").glob("*.json"))),
            "processing": len(list((self.root / "processing").glob("*.json"))),
            "done": len(list((self.root / "done").glob("*.json"))),
            "failed": len(list((self.root / "failed").glob("*.json"))),
        }

    def list_jobs(self, statuses: tuple[str, ...] = (), limit: int = 100) -> list[dict]:
        """Задачи очереди, новые сверху. Пустой statuses — все папки."""
        folders = statuses or ("pending", "processing", "done", "failed")
        rows: list[tuple[float, dict]] = []
        for folder in folders:
            for path in (self.root / folder).glob("*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                opts = data.get("options") or {}
                fields = data.get("fields") or {}
                rows.append(
                    (
                        path.stat().st_mtime,
                        {
                            "job_id": data.get("job_id", path.stem),
                            "status": data.get("status", folder),
                            "mockup": opts.get("mockup"),
                            "background": opts.get("background"),
                            "created_at": data.get("created_at", ""),
                            "updated_at": data.get("updated_at", ""),
                            "title": fields.get("surname_ru") or fields.get("number") or "",
                            "error": data.get("error"),
                            "jpg_path": data.get("jpg_path"),
                            "psd_path": data.get("psd_path"),
                        },
                    )
                )
        rows.sort(key=lambda r: r[0], reverse=True)
        return [r[1] for r in rows[:limit]]

    def recover_stale(self, max_age_sec: float = 900) -> int:
        """Вернуть зависшие processing-задачи в pending (worker упал)."""
        recovered = 0
        cutoff = time.time() - max_age_sec
        proc_dir = self.root / "processing"
        for path in sorted(proc_dir.glob("*.json")):
            if path.stat().st_mtime > cutoff:
                continue
            try:
                task = RenderTask.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, KeyError):
                path.unlink(missing_ok=True)
                continue
            task.status = JobStatus.PENDING.value
            task.updated_at = _now()
            task.error = None
            self._move(task.job_id, "processing", "pending", task)
            recovered += 1
        return recovered

    def _move(self, job_id: str, src: str, dst: str, task: RenderTask) -> None:
        (self.root / src / f"{job_id}.json").unlink(missing_ok=True)
        self._write(self.root / dst / f"{job_id}.json", task)

    def _write(self, path: Path, task: RenderTask) -> None:
        path.write_text(json.dumps(task.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
