from __future__ import annotations

import logging
import threading
import time
import urllib.request
import urllib.error
import json
from pathlib import Path
from typing import TYPE_CHECKING

from video_compose.jobs.manager import JobManager

if TYPE_CHECKING:
    from video_compose.schema.spec import TVCSSpec

logger = logging.getLogger(__name__)

_manager = JobManager()


def submit_async(
    spec: "TVCSSpec",
    output_dir: Path | None = None,
    spec_path: str | None = None,
) -> str:
    """Submit a render job for background execution. Returns job ID immediately."""
    webhook_url = getattr(spec.output, "webhook_url", None)
    out_path = str(output_dir / "output.mp4") if output_dir else spec.output.path

    job_id = _manager.create_job(
        spec_path=spec_path,
        output_path=out_path,
        webhook_url=webhook_url,
    )
    logger.info("Async job %s submitted", job_id)

    thread = threading.Thread(
        target=_run_job,
        args=(job_id, spec, output_dir),
        daemon=False,
        name=f"vc-job-{job_id}",
    )
    thread.start()
    return job_id


def _run_job(job_id: str, spec: "TVCSSpec", output_dir: Path | None) -> None:
    _manager.update_status(job_id, "running")
    t0 = time.monotonic()
    try:
        from video_compose.assembler.assembler import Assembler
        assembler = Assembler(spec, output_dir=output_dir)
        final_path = assembler.run()
        elapsed = time.monotonic() - t0
        _manager.update_status(job_id, "done", output_path=str(final_path))
        logger.info("Job %s done in %.1fs → %s", job_id, elapsed, final_path)
        _deliver_webhook(job_id, "done", str(final_path), None, elapsed)
    except Exception as exc:
        elapsed = time.monotonic() - t0
        error = str(exc)
        _manager.update_status(job_id, "failed", error=error)
        logger.error("Job %s failed after %.1fs: %s", job_id, elapsed, error)
        _deliver_webhook(job_id, "failed", None, error, elapsed)


def _deliver_webhook(
    job_id: str,
    status: str,
    output_path: str | None,
    error: str | None,
    duration_s: float,
) -> None:
    job = _manager.get_job(job_id)
    if not job or not job.get("webhook_url"):
        return

    url = job["webhook_url"]
    payload = json.dumps({
        "job_id": job_id,
        "status": status,
        "output_path": output_path,
        "duration_s": round(duration_s, 2),
        "error": error,
        "finished_at": job.get("finished_at"),
    }).encode()

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            logger.info("Webhook delivered → %s (job %s)", url, job_id)
    except urllib.error.URLError as exc:
        logger.warning("Webhook delivery failed for job %s: %s", job_id, exc)


def get_manager() -> JobManager:
    """Return the shared global JobManager instance."""
    return _manager
