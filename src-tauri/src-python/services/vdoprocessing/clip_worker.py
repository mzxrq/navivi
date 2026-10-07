"""Attraction work for one photo in a short-lived child process.

Everything a photo loads (depth and LaMa for 3D keyframes or the fallback,
RapidOCR for sign lock, whole clips of frames for the walk checks) stays held
by a Python process until it exits - in the pipeline it grew to 7.6 GB and
starved the next LTXV shot (2026-10-07). One child per job hands it all back to
Windows. The child stops if the pipeline that started it goes away (cancel),
and stops the ComfyUI server it started, so nothing keeps running on the GPU.
"""

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict

from services.logger.logger import setup_logger

logger = setup_logger("ClipWorker")

_ROOT = Path(__file__).resolve().parents[2]


def run(job: Dict[str, Any], work_dir: Path) -> Dict[str, Any]:
    """Runs `job` ({"kind": "clip" | "signlock", ...}) in a child and returns
    its result. Raises when the child fails or leaves no result."""
    from services.vdoprocessing.comfyui_i2v_client import _kill_process_tree

    work_dir.mkdir(parents=True, exist_ok=True)
    tag = uuid.uuid4().hex[:8]
    job_file, result_file = work_dir / f"job_{tag}.json", work_dir / f"result_{tag}.json"
    job_file.write_text(
        json.dumps(dict(job, parent_pid=os.getpid(), result=str(result_file)), ensure_ascii=False),
        encoding="utf-8",
    )
    proc = subprocess.Popen([sys.executable, "-m", "services.vdoprocessing.clip_worker", str(job_file)], cwd=_ROOT)
    try:
        code = proc.wait()
    except BaseException:
        _kill_process_tree(proc.pid)
        raise
    finally:
        job_file.unlink(missing_ok=True)
    try:
        if code != 0 or not result_file.is_file():
            raise RuntimeError(f"clip worker ({job['kind']}) exited with code {code}")
        return json.loads(result_file.read_text(encoding="utf-8"))
    finally:
        result_file.unlink(missing_ok=True)


def _watch_parent(pid: int) -> None:
    import psutil

    while True:
        time.sleep(2)
        if not psutil.pid_exists(pid):
            logger.warning("Pipeline (%d) is gone - stopping this clip.", pid)
            try:
                from services.vdoprocessing.comfyui_i2v_client import ComfyUII2VClient

                ComfyUII2VClient.stop_server()
            finally:
                os._exit(3)


def main(job_file: str) -> None:
    job = json.loads(Path(job_file).read_text(encoding="utf-8"))
    threading.Thread(target=_watch_parent, args=(int(job["parent_pid"]),), daemon=True).start()

    from services.config.job_config import JobConfigManager
    from services.vdoprocessing.comfyui_i2v_client import ComfyUII2VClient
    from services.vdoprocessing.img2vdo import AttractionVideoGenerator

    result: Dict[str, Any] = {}
    try:
        if job["kind"] == "clip":
            generator = AttractionVideoGenerator(JobConfigManager(job["config_path"]))
            result["clip"] = generator._generate_single_clip_here(
                job["image"], job["prompt"], job["duration"], save_path=job["save_path"], place=job.get("place"),
            )
        elif job["kind"] == "signlock":
            from services.vdoprocessing.sign_lock import lock_signs

            result["locked"] = lock_signs(job["clip"], job["image"])
        else:
            raise ValueError(f"Unknown job kind {job['kind']!r}")
    finally:
        ComfyUII2VClient.stop_server()
    Path(job["result"]).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
