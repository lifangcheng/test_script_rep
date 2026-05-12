from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.task_store import store
from graph.builder import compile_graph
from graph.state import CANState
from utils.io import ensure_dir, write_json


# Serve UI by default unless explicitly asked for docs
app = FastAPI(title="can-agent", version="0.1.0", docs_url=None, redoc_url=None, openapi_url="/openapi.json")

@app.middleware("http")
async def log_requests(request, call_next):
    response = await call_next(request)
    try:
        print(f"[req] {request.method} {request.url.path} -> {response.status_code}")
    except Exception:
        pass
    return response

# 服务前端打包文件（更健壮：/assets 静态，其他路由回退 index.html）
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"
INDEX_FILE = FRONTEND_DIR / "index.html"
print(f"[frontend] dist={FRONTEND_DIR} exists={FRONTEND_DIR.exists()} index={INDEX_FILE.exists()}")
if FRONTEND_DIR.exists():
    assets_dir = FRONTEND_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/", include_in_schema=False)
    def serve_root():
        if INDEX_FILE.exists():
            return FileResponse(str(INDEX_FILE))
        return RedirectResponse(url="/docs")
else:
    @app.get("/", include_in_schema=False)
    def root_redirect():
        return JSONResponse({"message": "UI not built, run npm run build under frontend"}, status_code=503)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 前端路由回退：除 API 路径外，全部返回 index.html（避免显示 /docs 页面）
if FRONTEND_DIR.exists():
    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_frontend(full_path: str):
        # 已知 API 前缀列表，直接返回 404 让 FastAPI 继续匹配
        api_prefixes = ("run", "status", "report", "ai_report", "signals", "download")
        first = full_path.split("/")[0] if full_path else ""
        if first in api_prefixes:
            raise HTTPException(status_code=404)
        if INDEX_FILE.exists():
            return FileResponse(str(INDEX_FILE))
        return JSONResponse({"message": "UI not built"}, status_code=503)

class RunRequest(BaseModel):
    blf_path: str
    dbc_path: str
    enable_ai: bool = False
    config_path: str = ""
    output_dir: str = "outputs"


class UploadResponse(BaseModel):
    file_id: str
    path: str


class RunResponse(BaseModel):
    task_id: str


UPLOAD_ROOT = Path(tempfile.gettempdir()) / "can_agent_uploads"
ensure_dir(UPLOAD_ROOT)


def _save_upload(file: UploadFile, subdir: str) -> Path:
    target_dir = UPLOAD_ROOT / subdir
    ensure_dir(target_dir)
    filename = file.filename or "uploaded.bin"
    target_path = target_dir / filename
    with target_path.open("wb") as f:
        while chunk := file.file.read(1024 * 1024):
            f.write(chunk)
    return target_path


def _create_archive(src_dir: Path) -> Path:
    # 将输出目录打包为 zip，返回 zip 路径
    ensure_dir(src_dir)
    tmp = Path(tempfile.gettempdir()) / f"can_agent_{src_dir.name}.zip"
    if tmp.exists():
        tmp.unlink()
    shutil.make_archive(tmp.with_suffix(""), "zip", root_dir=src_dir)
    return tmp


def _run_task(task_id: str, req: RunRequest) -> None:
    out_dir = Path(req.output_dir).resolve() / task_id
    ensure_dir(out_dir)

    store.update(task_id, status="running", output_dir=str(out_dir))

    state = CANState(
        blf_path=str(Path(req.blf_path).resolve()),
        dbc_path=str(Path(req.dbc_path).resolve()),
        config={"config_path": req.config_path} if req.config_path else {},
        enable_ai=bool(req.enable_ai),
        output_dir=str(out_dir),
    )

    g = compile_graph()
    final_state: CANState = g.invoke(state)

    status_payload = {
        "task_id": task_id,
        "status": final_state.status,
        "error": final_state.error,
        "logs": final_state.logs,
        "output_dir": str(out_dir),
    }

    write_json(f"{out_dir}/status.json", status_payload)

    if final_state.status == "failed":
        store.update(task_id, status="failed", error=final_state.error, logs=final_state.logs)
    else:
        store.update(task_id, status="success", error=None, logs=final_state.logs)


@app.post("/run", response_model=RunResponse)
def run(req: RunRequest, bg: BackgroundTasks) -> RunResponse:
    task = store.create(output_dir="")
    bg.add_task(_run_task, task.task_id, req)
    return RunResponse(task_id=task.task_id)


@app.post("/upload/blf", response_model=UploadResponse)
async def upload_blf(file: UploadFile = File(...)):
    path = _save_upload(file, subdir="blf")
    return UploadResponse(file_id=uuid4().hex, path=str(path))


@app.post("/upload/dbc", response_model=UploadResponse)
async def upload_dbc(file: UploadFile = File(...)):
    path = _save_upload(file, subdir="dbc")
    return UploadResponse(file_id=uuid4().hex, path=str(path))


@app.get("/status/{task_id}")
def status(task_id: str):
    rec = store.get(task_id)
    if not rec:
        # fallback: check filesystem status.json under outputs/{task_id}
        status_path = Path("outputs") / task_id / "status.json"
        if status_path.exists():
            try:
                with status_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                return JSONResponse(data)
            except Exception:
                pass
        return JSONResponse({"task_id": task_id, "status": "not_found"}, status_code=404)

    payload = {
        "task_id": rec.task_id,
        "status": rec.status,
        "error": rec.error,
        "logs": rec.logs,
        "output_dir": rec.output_dir,
    }
    return JSONResponse(payload)


@app.get("/report/{task_id}")
def report(task_id: str):
    rec = store.get(task_id)
    if not rec or not rec.output_dir:
        raise HTTPException(status_code=404, detail="task not found")

    report_json = Path(rec.output_dir) / "report.json"
    if not report_json.exists():
        raise HTTPException(status_code=404, detail="report not generated yet")

    return FileResponse(str(report_json), media_type="application/json")


@app.get("/ai_report/{task_id}")
def ai_report(task_id: str):
    rec = store.get(task_id)
    if not rec or not rec.output_dir:
        raise HTTPException(status_code=404, detail="task not found")

    p = Path(rec.output_dir) / "ai_report.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail="ai report not generated yet")

    return FileResponse(str(p), media_type="application/json")


@app.get("/download/{task_id}")
def download(task_id: str):
    """打包输出目录为 zip 并返回下载。"""
    rec = store.get(task_id)
    if not rec or not rec.output_dir:
        raise HTTPException(status_code=404, detail="task not found")

    out_dir = Path(rec.output_dir)
    if not out_dir.exists():
        raise HTTPException(status_code=404, detail="output directory not found")

    zip_path = _create_archive(out_dir)
    return FileResponse(
        str(zip_path),
        media_type="application/zip",
        filename=f"{task_id}.zip",
    )


@app.get("/signals")
def signals(task_id: str = "", signal: str = ""):
    if not task_id:
        raise HTTPException(status_code=400, detail="task_id is required")

    rec = store.get(task_id)
    if not rec or not rec.output_dir:
        raise HTTPException(status_code=404, detail="task not found")

    sig_root = Path(rec.output_dir) / "signals"
    idx = sig_root / "index.json"
    if not idx.exists():
        raise HTTPException(status_code=404, detail="signals index not generated yet")

    if not signal:
        return JSONResponse(json.loads(idx.read_text(encoding="utf-8")))

    safe = "".join(c if (c.isalnum() or c in "-_ .") else "_" for c in signal).replace(" ", "_")
    safe = safe[:180] if len(safe) > 180 else safe
    p = sig_root / "data" / f"{safe}.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail="signal data not found")

    return JSONResponse(json.loads(p.read_text(encoding="utf-8")))
