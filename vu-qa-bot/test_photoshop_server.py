#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from photoshop_server import (
    QueueStats,
    WorkerHeartbeat,
    get_server_status,
    is_server_mode,
    queue_stats,
    read_heartbeat,
    recover_stale_jobs,
    render_mode,
    resolve_output_file,
    write_heartbeat,
)
from render_models import RenderOptions, RenderTask
from render_queue import RenderQueue


class TestPhotoshopServer(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        os.environ["RENDER_QUEUE_DIR"] = str(self.tmp / "queue")
        os.environ["RENDER_OUTPUT_DIR"] = str(self.tmp / "output")
        os.environ["RENDER_MODE"] = "server"
        (self.tmp / "output").mkdir(parents=True)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_render_mode_server_default(self):
        self.assertEqual(render_mode().value, "server")
        self.assertTrue(is_server_mode())

    def test_heartbeat_read_write(self):
        hb = WorkerHeartbeat(worker_id="t1", status="idle", jobs_processed=3)
        write_heartbeat(hb)
        loaded = read_heartbeat()
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.worker_id, "t1")
        self.assertTrue(loaded.is_alive())

    def test_queue_stats(self):
        q = RenderQueue(Path(os.environ["RENDER_QUEUE_DIR"]))
        task = RenderTask.create("1  Фамилия      X / X\n5  Номер        0101 123456")
        q.enqueue(task)
        stats = queue_stats()
        self.assertEqual(stats.pending, 1)
        self.assertEqual(stats.processing, 0)

    def test_recover_stale(self):
        qdir = Path(os.environ["RENDER_QUEUE_DIR"])
        q = RenderQueue(qdir)
        task = RenderTask.create("1  Фамилия      X / X\n5  Номер        0101 123456")
        q.enqueue(task)
        claimed = q.claim("w")
        self.assertIsNotNone(claimed)
        job_id = claimed.job_id
        proc = qdir / "processing" / f"{job_id}.json"
        old = time.time() - 2000
        os.utime(proc, (old, old))
        n = recover_stale_jobs(900)
        self.assertEqual(n, 1)
        self.assertTrue((qdir / "pending" / f"{job_id}.json").is_file())

    def test_resolve_output_file(self):
        out = Path(os.environ["RENDER_OUTPUT_DIR"])
        sample = out / "vu_test.jpg"
        sample.write_bytes(b"jpeg")
        resolved = resolve_output_file(sample)
        self.assertEqual(resolved, sample.resolve())
        with self.assertRaises(PermissionError):
            resolve_output_file("/etc/passwd")

    def test_server_status(self):
        st = get_server_status()
        self.assertEqual(st.mode, "server")
        self.assertFalse(st.worker_alive)
        self.assertIsInstance(st.queue, QueueStats)


if __name__ == "__main__":
    unittest.main()
