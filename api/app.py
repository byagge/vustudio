#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

VU_ROOT = Path(__file__).resolve().parent.parent / "vu-qa-bot"
WEB_ROOT = Path(__file__).resolve().parent.parent / "web" / "static"
if str(VU_ROOT) not in sys.path:
    sys.path.insert(0, str(VU_ROOT))

from fastapi import Depends, FastAPI, File, HTTPException, Security, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles

from config import Settings
from eval_rules import evaluate, validate
from formatter import (
    BANNER,
    dataset_filename,
    format_client_block,
    format_debug_block,
    format_jsonl_line,
    record_to_json,
)
from photoshop_text import (
    get_render_server_status,
    get_substitute_status,
    substitute_text_queued,
    wait_substitute,
)
from vu_testdata import (
    BIRTH_PLACES,
    MUTATORS,
    REGIONS,
    IdentityError,
    make_mutated,
    make_valid,
    new_rng,
    parse_identity,
    parse_me,
    parse_place,
)

from .schemas import (
    AdminDashboardResponse,
    AdminRecoverResponse,
    BackgroundItem,
    BackgroundListResponse,
    BackgroundPreviewItem,
    DatasetRequest,
    DatasetResponse,
    EvaluateRequest,
    EvaluateResponse,
    GenerateRequest,
    GenerateResponse,
    MockupItem,
    MockupsResponse,
    PortraitGenerateRequest,
    PortraitGenerateResponse,
    PortraitUploadResponse,
    QueueJobItem,
    QueueJobsResponse,
    QueueStatsResponse,
    RegionItem,
    RenderRequest,
    RenderResponse,
    RenderServerStatusResponse,
    SceneVerifyResponse,
    ValidateRequest,
    ValidateResponse,
    WorkerInfo,
)

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def create_app() -> FastAPI:
    settings = Settings.load()
    app = FastAPI(
        title="VU QA Platform API",
        description="Генератор и валидатор синтетических записей ВУ (QA/тестирование)",
        version="1.0.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def auth(key: str | None = Security(_api_key_header)) -> None:
        if settings.api_key and key != settings.api_key:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")

    @app.get("/api/v1/mockups", response_model=MockupsResponse)
    async def list_mockups_api():
        from mockup_scene import list_mockups_info

        items = [
            MockupItem(
                kind=m.kind,
                title=m.title,
                supports_background=m.supports_background,
                supports_portrait=m.supports_portrait,
                mockup_variant=m.mockup_variant,
                backgrounds=[
                    BackgroundItem(id=b.id, layer_name=b.layer_name) for b in m.backgrounds
                ],
            )
            for m in list_mockups_info()
        ]
        return MockupsResponse(mockups=items)

    @app.post("/api/v1/portrait/generate", response_model=PortraitGenerateResponse)
    async def portrait_generate(body: PortraitGenerateRequest, _: None = Depends(auth)):
        import asyncio

        from portrait_service import generate_ai_portrait
        from render_models import block_to_dict
        from text_parser import TextParseError, parse_client_block

        if body.fields:
            fields = body.fields
        elif body.text_block:
            try:
                fields = block_to_dict(parse_client_block(body.text_block))
            except TextParseError as e:
                raise HTTPException(400, str(e)) from e
        else:
            raise HTTPException(400, "Укажите text_block или fields")

        result = await asyncio.to_thread(generate_ai_portrait, fields)
        if not result.ok:
            raise HTTPException(503, result.message)
        return PortraitGenerateResponse(
            ok=True,
            portrait_path=result.path_str,
            message=result.message,
            source=result.source,
            provider=result.provider,
        )

    @app.get("/api/v1/portrait/download")
    async def portrait_download(path: str, _: None = Depends(auth)):
        file_path = Path(path)
        portraits_root = Settings.load().render_output_dir / "portraits"
        try:
            file_path.resolve().relative_to(portraits_root.resolve())
        except ValueError:
            raise HTTPException(403, "Path not allowed") from None
        if not file_path.is_file():
            raise HTTPException(404, "File not found")
        return FileResponse(file_path, media_type="image/jpeg", filename=file_path.name)

    @app.get("/api/v1/render/server", response_model=RenderServerStatusResponse)
    @app.get("/api/v1/render/server/status", response_model=RenderServerStatusResponse)
    async def render_server_status(_: None = Depends(auth)):
        raw = get_render_server_status()
        worker_raw = raw.get("worker")
        worker = WorkerInfo(**worker_raw) if worker_raw else None
        if worker and worker_raw.get("updated_at"):
            from photoshop_server import WorkerHeartbeat

            hb = WorkerHeartbeat.from_dict(worker_raw)
            worker.age_sec = hb.age_sec()
        q = raw["queue"]
        return RenderServerStatusResponse(
            mode=raw["mode"],
            worker_alive=raw["worker_alive"],
            worker=worker,
            queue=QueueStatsResponse(
                pending=q["pending"],
                processing=q["processing"],
                done=q["done"],
                failed=q["failed"],
                total=q["pending"] + q["processing"] + q["done"] + q["failed"],
            ),
            photoshop_configured=raw["photoshop_configured"],
            photoshop_available=raw["photoshop_available"],
            output_dir=raw["output_dir"],
            queue_dir=raw["queue_dir"],
            message=raw["message"],
        )

    @app.get("/api/v1/render/queue", response_model=QueueStatsResponse)
    async def render_queue_stats(_: None = Depends(auth)):
        from photoshop_server import queue_stats

        s = queue_stats()
        return QueueStatsResponse(
            pending=s.pending,
            processing=s.processing,
            done=s.done,
            failed=s.failed,
            total=s.total,
        )

    @app.get("/api/v1/render/queue/jobs", response_model=QueueJobsResponse)
    async def render_queue_jobs(status: str = "", limit: int = 50, _: None = Depends(auth)):
        from photoshop_server import queue_jobs

        rows = queue_jobs(status=status, limit=max(1, min(limit, 200)))
        return QueueJobsResponse(jobs=[QueueJobItem(**r) for r in rows], total=len(rows))

    @app.get("/api/v1/mockups/backgrounds", response_model=BackgroundListResponse)
    async def mockup_backgrounds():
        from background_previews import list_previews

        items = [BackgroundPreviewItem(**b) for b in list_previews()]
        return BackgroundListResponse(backgrounds=items)

    @app.get("/api/v1/mockups/backgrounds/{bg_id}/preview")
    async def mockup_background_preview(bg_id: int):
        from background_previews import preview_file

        path = preview_file(bg_id)
        if not path:
            raise HTTPException(404, "Превью не найдено")
        media = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        return FileResponse(path, media_type=media)

    @app.post("/api/v1/mockups/backgrounds/extract")
    async def mockup_backgrounds_extract(overwrite: bool = False, _: None = Depends(auth)):
        from background_previews import extract_previews_async

        return extract_previews_async(overwrite=overwrite)

    @app.get("/api/v1/mockups/backgrounds/extract/status")
    async def mockup_backgrounds_extract_status(_: None = Depends(auth)):
        from background_previews import extract_state

        return extract_state()

    @app.get("/api/v1/render/scene/verify", response_model=SceneVerifyResponse)
    async def render_scene_verify(refresh: bool = False, _: None = Depends(auth)):
        from admin_tools import scene_report

        raw = scene_report(refresh=refresh)
        return SceneVerifyResponse(
            ok=raw.get("ok"),
            status=raw.get("status", "ready"),
            templates=raw.get("templates", {}),
        )

    @app.get("/api/v1/admin/dashboard", response_model=AdminDashboardResponse)
    async def admin_dashboard(_: None = Depends(auth)):
        from admin_tools import admin_dashboard as dash

        raw = dash()
        q = raw["queue"]
        return AdminDashboardResponse(
            server=raw["server"],
            scene_verify=raw["scene_verify"],
            queue=QueueStatsResponse(
                pending=q["pending"],
                processing=q["processing"],
                done=q["done"],
                failed=q["failed"],
                total=q["pending"] + q["processing"] + q["done"] + q["failed"],
            ),
        )

    @app.post("/api/v1/admin/recover-stale", response_model=AdminRecoverResponse)
    async def admin_recover_stale(_: None = Depends(auth)):
        from admin_tools import admin_recover_stale

        raw = admin_recover_stale()
        q = raw["queue"]
        return AdminRecoverResponse(
            recovered=raw["recovered"],
            queue=QueueStatsResponse(
                pending=q["pending"],
                processing=q["processing"],
                done=0,
                failed=0,
                total=q["pending"] + q["processing"],
            ),
        )

    @app.post("/api/v1/portrait/upload", response_model=PortraitUploadResponse)
    async def portrait_upload(file: UploadFile = File(...), _: None = Depends(auth)):
        from portrait_service import prepare_upload

        data = await file.read()
        if len(data) < 100:
            raise HTTPException(400, "Файл слишком мал")
        suffix = Path(file.filename or "photo.jpg").suffix or ".jpg"
        result = prepare_upload(data, user_id=0, suffix=suffix)
        if not result.ok:
            raise HTTPException(400, result.message)
        return PortraitUploadResponse(
            ok=True,
            portrait_path=result.path_str or "",
            message=result.message,
        )

    @app.post("/api/v1/render", response_model=RenderResponse)
    async def render_mockup(body: RenderRequest, _: None = Depends(auth)):
        from photoshop_server import get_server_status, is_server_mode

        if body.wait and is_server_mode():
            st = get_server_status()
            if not st.worker_alive and st.queue.processing:
                raise HTTPException(
                    503,
                    "Render-worker offline. Запустите render_worker.py на Windows.",
                )

        queued = substitute_text_queued(
            body.text_block,
            mockup=body.mockup,
            background=body.background,
            portrait_path=body.portrait_path,
            generate_portrait=body.generate_portrait,
        )
        if not queued.ok:
            raise HTTPException(400, queued.message)

        if body.wait:
            import asyncio

            done = await asyncio.to_thread(wait_substitute, queued.job_id, 120, 1.0)
            if done.ok:
                return RenderResponse(
                    job_id=done.job_id,
                    status="done",
                    message=done.message,
                    fields=done.fields,
                    psd_path=str(done.psd_path) if done.psd_path else None,
                    jpg_path=str(done.jpg_path) if done.jpg_path else None,
                )
            raise HTTPException(503, done.message)

        return RenderResponse(
            job_id=queued.job_id,
            status="pending",
            message=queued.message,
            fields=queued.fields,
        )

    @app.get("/api/v1/render/{job_id}", response_model=RenderResponse)
    async def render_status(job_id: str, _: None = Depends(auth)):
        status = get_substitute_status(job_id)
        if not status:
            raise HTTPException(404, "Job not found")
        return RenderResponse(
            job_id=job_id,
            status=status.status or ("done" if status.ok else "failed"),
            message=status.message,
            fields=status.fields,
            psd_path=str(status.psd_path) if status.psd_path else None,
            jpg_path=str(status.jpg_path) if status.jpg_path else None,
        )

    @app.get("/api/v1/render/download/{kind}")
    async def render_download(kind: str, path: str, _: None = Depends(auth)):
        from photoshop_server import resolve_output_file

        if kind not in {"jpg", "psd", "psb"}:
            raise HTTPException(400, "kind must be jpg, psd or psb")
        try:
            file_path = resolve_output_file(path)
        except PermissionError:
            raise HTTPException(403, "Path not allowed") from None
        except FileNotFoundError:
            raise HTTPException(404, "File not found") from None
        media = "image/jpeg" if kind == "jpg" else "application/octet-stream"
        return FileResponse(file_path, media_type=media, filename=file_path.name)

    @app.get("/health")
    async def health():
        from photoshop_server import get_server_status

        st = get_server_status()
        return {
            "status": "ok",
            "regions": len(REGIONS),
            "render_mode": st.mode,
            "worker_alive": st.worker_alive,
            "queue_pending": st.queue.pending,
        }

    @app.get("/api/v1/regions", response_model=list[RegionItem])
    async def list_regions():
        return [RegionItem(code=c, name=n) for c, n in sorted(REGIONS.items())]

    @app.post("/api/v1/generate", response_model=GenerateResponse)
    async def generate(body: GenerateRequest, _: None = Depends(auth)):
        try:
            if body.identity:
                ident = parse_identity(body.identity)
                place = parse_place(body.birthplace) if body.birthplace else None
            elif body.me:
                ident, place = parse_me(body.me)
            else:
                raise HTTPException(400, "Укажите identity или me")
        except IdentityError as e:
            raise HTTPException(400, str(e)) from e

        if body.region_code and body.region_code not in REGIONS:
            raise HTTPException(400, f"Неизвестный код региона: {body.region_code}")

        rec = make_valid(
            new_rng(body.seed),
            identity=ident,
            region_code=body.region_code,
            birth_place=place or body.birthplace,
            valid_now=body.valid_now,
        )
        rules = validate(rec.to_dict())
        return GenerateResponse(
            record=rec.to_dict(),
            text_block=format_client_block(rec),
            debug_block=format_debug_block(rec),
            record_json=record_to_json(rec, indent=None),
            validation_status="green" if not rules else "red",
            broken_rules=rules,
        )

    @app.post("/api/v1/validate", response_model=ValidateResponse)
    async def validate_record(body: ValidateRequest, _: None = Depends(auth)):
        rules = validate(body.record)
        return ValidateResponse(status="green" if not rules else "red", broken_rules=rules)

    @app.post("/api/v1/evaluate", response_model=EvaluateResponse)
    async def evaluate_dataset(body: EvaluateRequest, _: None = Depends(auth)):
        res = evaluate(body.records, verbose=False)
        return EvaluateResponse(**res)

    @app.post("/api/v1/dataset", response_model=DatasetResponse)
    async def build_dataset(body: DatasetRequest, _: None = Depends(auth)):
        ident = None
        if body.identity:
            try:
                ident = parse_identity(body.identity)
            except IdentityError as e:
                raise HTTPException(400, str(e)) from e

        rng = new_rng(body.seed)
        records = []
        for _ in range(body.valid):
            records.append(
                make_valid(
                    rng,
                    identity=ident,
                    region_code=body.region_code,
                    birth_place=body.birthplace,
                    valid_now=body.valid_now,
                ).to_dict()
            )
        names = list(MUTATORS)
        for i in range(body.mutated):
            records.append(
                make_mutated(
                    rng,
                    names[i % len(names)],
                    identity=ident,
                    region_code=body.region_code,
                    birth_place=body.birthplace,
                    valid_now=body.valid_now,
                ).to_dict()
            )
        return DatasetResponse(count=len(records), records=records)

    @app.get("/api/v1/birthplaces")
    async def list_birthplaces():
        return BIRTH_PLACES

    @app.post("/api/v1/dataset/download")
    async def download_dataset(body: DatasetRequest, _: None = Depends(auth)):
        ident = None
        if body.identity:
            try:
                ident = parse_identity(body.identity)
            except IdentityError as e:
                raise HTTPException(400, str(e)) from e

        rng = new_rng(body.seed)
        lines: list[str] = []
        for _ in range(body.valid):
            rec = make_valid(
                rng,
                identity=ident,
                region_code=body.region_code,
                birth_place=body.birthplace,
                valid_now=body.valid_now,
            )
            lines.append(format_jsonl_line(rec))
        names = list(MUTATORS)
        for i in range(body.mutated):
            rec = make_mutated(
                rng,
                names[i % len(names)],
                identity=ident,
                region_code=body.region_code,
                birth_place=body.birthplace,
                valid_now=body.valid_now,
            )
            lines.append(format_jsonl_line(rec))

        content = "\n".join(lines) + "\n"
        fname = dataset_filename(body.valid, body.mutated)
        return Response(
            content=content.encode("utf-8"),
            media_type="application/x-ndjson",
            headers={
                "Content-Disposition": f'attachment; filename="{fname}"',
                "X-Dataset-Banner": BANNER,
                "X-Dataset-Valid": str(body.valid),
                "X-Dataset-Mutated": str(body.mutated),
            },
        )

    if WEB_ROOT.is_dir():
        app.mount("/static", StaticFiles(directory=str(WEB_ROOT)), name="static")

        @app.get("/")
        async def web_panel():
            return FileResponse(WEB_ROOT / "index.html")

    return app
