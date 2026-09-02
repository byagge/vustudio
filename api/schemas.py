from __future__ import annotations

from pydantic import BaseModel, Field


class RegionItem(BaseModel):
    code: str
    name: str


class GenerateRequest(BaseModel):
    identity: str | None = Field(
        None,
        description='ФАМИЛИЯ ИМЯ ОТЧЕСТВО ДД.ММ.ГГГГ',
        examples=["АБСАЛЯМОВ ВЛАДИСЛАВ НАИЛЕВИЧ 08.09.1983"],
    )
    me: str | None = Field(
        None,
        description="ФИО + дата + место рождения одной строкой",
        examples=["АБСАЛЯМОВ ВЛАДИСЛАВ НАИЛЕВИЧ 08.09.1983 Г. ХАБАРОВСК"],
    )
    region_code: str | None = Field(None, description="Код подразделения ГИБДД, напр. 77")
    birthplace: str | None = None
    valid_now: bool = Field(True, description="Срок действия ещё не истёк")
    seed: int | None = None


class GenerateResponse(BaseModel):
    record: dict
    text_block: str
    debug_block: str
    record_json: str
    validation_status: str
    broken_rules: list[str]


class ValidateRequest(BaseModel):
    record: dict


class ValidateResponse(BaseModel):
    status: str
    broken_rules: list[str]


class EvaluateRequest(BaseModel):
    records: list[dict]


class EvaluateResponse(BaseModel):
    records: int
    valid: int
    mutated: int
    tp: int
    fp: int
    tn: int
    fn: int
    precision: float
    recall: float
    false_negatives_by_rule: dict
    false_positives: dict
    non_synthetic: int


class DatasetRequest(BaseModel):
    valid: int = Field(10, ge=0, le=10000)
    mutated: int = Field(0, ge=0, le=10000)
    identity: str | None = None
    region_code: str | None = None
    birthplace: str | None = None
    valid_now: bool = False
    seed: int | None = None


class RenderRequest(BaseModel):
    text_block: str = Field(..., description="Клиентский блок полей ВУ")
    mockup: str = Field("hand", description="blank | hand | original")
    background: int = Field(1, ge=1, le=10)
    portrait_path: str | None = None
    generate_portrait: bool = False
    wait: bool = Field(True, description="Ждать завершения worker (до 120 сек)")


class RenderResponse(BaseModel):
    job_id: str
    status: str
    message: str
    fields: dict | None = None
    psd_path: str | None = None
    jpg_path: str | None = None


class PortraitGenerateRequest(BaseModel):
    text_block: str | None = Field(None, description="Блок полей ВУ для демографии")
    fields: dict | None = Field(None, description="JSON полей (альтернатива text_block)")


class PortraitGenerateResponse(BaseModel):
    ok: bool
    portrait_path: str | None = None
    message: str = ""
    source: str = ""
    provider: str = ""


class BackgroundItem(BaseModel):
    id: int
    layer_name: str


class MockupItem(BaseModel):
    kind: str
    title: str
    supports_background: bool
    supports_portrait: bool
    mockup_variant: str | None
    backgrounds: list[BackgroundItem]


class MockupsResponse(BaseModel):
    mockups: list[MockupItem]


class QueueStatsResponse(BaseModel):
    pending: int
    processing: int
    done: int
    failed: int
    total: int


class WorkerInfo(BaseModel):
    worker_id: str | None = None
    status: str = "unknown"
    updated_at: str | None = None
    age_sec: float | None = None
    current_job_id: str | None = None
    photoshop_exe: str | None = None
    photoshop_available: bool = False
    jobs_processed: int = 0
    last_job_ms: int | None = None
    last_error: str | None = None
    hostname: str | None = None


class RenderServerStatusResponse(BaseModel):
    mode: str
    worker_alive: bool
    worker: WorkerInfo | None = None
    queue: QueueStatsResponse
    photoshop_configured: bool
    photoshop_available: bool
    output_dir: str
    queue_dir: str
    message: str = ""


class QueueJobItem(BaseModel):
    job_id: str
    status: str
    mockup: str | None = None
    background: int | None = None
    created_at: str = ""
    updated_at: str = ""
    title: str = ""
    error: str | None = None
    jpg_path: str | None = None
    psd_path: str | None = None


class QueueJobsResponse(BaseModel):
    jobs: list[QueueJobItem]
    total: int


class BackgroundPreviewItem(BaseModel):
    id: int
    layer_name: str
    has_preview: bool


class BackgroundListResponse(BaseModel):
    backgrounds: list[BackgroundPreviewItem]


class SceneVerifyResponse(BaseModel):
    ok: bool | None = None
    status: str = "ready"
    templates: dict[str, dict] = {}


class AdminRecoverResponse(BaseModel):
    recovered: int
    queue: QueueStatsResponse


class AdminDashboardResponse(BaseModel):
    server: dict
    scene_verify: dict
    queue: QueueStatsResponse


class PortraitUploadResponse(BaseModel):
    ok: bool
    portrait_path: str
    message: str = ""


class DatasetResponse(BaseModel):
    count: int
    records: list[dict]
