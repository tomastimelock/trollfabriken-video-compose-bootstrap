from __future__ import annotations

"""FastAPI REST server for video-compose.

Endpoints:
    POST /render       — Submit a render job (sync or async)
    GET  /jobs/{id}    — Get job status and result
    GET  /jobs         — List recent jobs
    POST /validate     — Validate a spec without rendering
    GET  /schema       — Return the TVCS JSON Schema
    GET  /health       — Health check
"""

import logging
import threading
from pathlib import Path
from typing import Any

try:
    from fastapi import FastAPI, HTTPException, BackgroundTasks
    from fastapi.responses import JSONResponse, FileResponse
    from pydantic import BaseModel
except ImportError as exc:
    raise ImportError(
        "FastAPI is required for the REST server — pip install 'video-compose[server]'"
    ) from exc

logger = logging.getLogger(__name__)

app = FastAPI(
    title="video-compose API",
    description="JSON-driven video composition engine (Trollfabriken TVCS)",
    version="0.6.0",
)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class RenderRequest(BaseModel):
    spec: dict[str, Any]
    output_dir: str | None = None
    async_mode: bool = False
    export_png: bool = False
    export_gif: bool = False
    export_webm: bool = False


class ValidateRequest(BaseModel):
    spec: dict[str, Any]


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    video_path: str | None = None
    png_dir: str | None = None
    error: str | None = None
    created_at: str | None = None
    finished_at: str | None = None


# ---------------------------------------------------------------------------
# In-process job store (for servers without a full job manager)
# ---------------------------------------------------------------------------

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _new_job(spec: dict, output_dir: str | None) -> str:
    import uuid
    from datetime import datetime, timezone
    job_id = str(uuid.uuid4())[:8]
    with _jobs_lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "status": "pending",
            "spec": spec,
            "output_dir": output_dir,
            "video_path": None,
            "png_dir": None,
            "error": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
        }
    return job_id


def _run_job(job_id: str, export_png: bool) -> None:
    from datetime import datetime, timezone
    from video_compose.api import compose

    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return

    with _jobs_lock:
        _jobs[job_id]["status"] = "running"

    try:
        result = compose(
            job["spec"],
            output_dir=job.get("output_dir"),
            export_png=export_png,
        )
        with _jobs_lock:
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["video_path"] = str(result.video_path) if result.video_path else None
            _jobs[job_id]["png_dir"] = str(result.png_dir) if result.png_dir else None
            _jobs[job_id]["finished_at"] = datetime.now(timezone.utc).isoformat()
    except Exception as exc:
        logger.exception("Job %s failed", job_id)
        with _jobs_lock:
            _jobs[job_id]["status"] = "failed"
            _jobs[job_id]["error"] = str(exc)
            _jobs[job_id]["finished_at"] = datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": "0.6.0"}


@app.get("/schema")
def schema() -> JSONResponse:
    from video_compose.schema.spec import TVCSSpec
    return JSONResponse(TVCSSpec.model_json_schema())


@app.post("/validate")
def validate_spec(req: ValidateRequest) -> dict:
    from video_compose.api import validate
    result = validate(req.spec)
    return {
        "valid": result.is_valid,
        "errors": result.errors,
        "warnings": result.warnings,
    }


@app.post("/render")
def render(req: RenderRequest, background_tasks: BackgroundTasks) -> dict:
    if req.async_mode:
        job_id = _new_job(req.spec, req.output_dir)
        background_tasks.add_task(_run_job, job_id, req.export_png)
        return {"job_id": job_id, "status": "pending"}

    # Synchronous render
    from video_compose.api import compose
    try:
        result = compose(req.spec, output_dir=req.output_dir, export_png=req.export_png)
        return {
            "status": "done",
            "video_path": str(result.video_path) if result.video_path else None,
            "png_dir": str(result.png_dir) if result.png_dir else None,
            "warnings": result.warnings,
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/jobs")
def list_jobs(limit: int = 20) -> list[dict]:
    with _jobs_lock:
        jobs = list(_jobs.values())
    jobs.sort(key=lambda j: j.get("created_at", ""), reverse=True)
    return jobs[:limit]


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")
    return job


@app.get("/jobs/{job_id}/download")
def download_job(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")
    if job["status"] != "done" or not job.get("video_path"):
        raise HTTPException(status_code=409, detail=f"Job {job_id!r} not ready (status={job['status']!r})")
    path = Path(job["video_path"])
    if not path.exists():
        raise HTTPException(status_code=410, detail="Output file no longer available")
    return FileResponse(str(path), media_type="video/mp4", filename=path.name)
