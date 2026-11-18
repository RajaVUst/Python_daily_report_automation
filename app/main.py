"""FastAPI portal. Run with a SINGLE worker: uvicorn app.main:app --port 8000"""
import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import auth, llm
from .config import BASE_DIR, CONFIG_PATH, load_config
from .db import JobRun, init_db, session_scope
from .scheduler import manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    auth.ensure_admin()
    manager.startup()
    yield
    manager.shutdown()


app = FastAPI(title="Daily Recon", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SECRET_KEY") or secrets.token_hex(32),
    same_site="strict",
    https_only=os.getenv("HTTPS_ONLY", "").lower() in ("1", "true", "yes"),
    max_age=8 * 3600,
)
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


def _local(dt):
    if not dt:
        return ""
    from datetime import timezone
    return dt.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(load_config()["timezone"])).strftime("%Y-%m-%d %H:%M:%S")


templates.env.filters["local"] = _local
templates.env.filters["fromjson"] = json.loads


@app.exception_handler(auth.NotAuthenticated)
async def _unauth(request: Request, exc):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    return RedirectResponse("/login", status_code=303)


# ---------------- auth ----------------
@app.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    ip = request.client.host if request.client else "?"
    if auth.throttled(ip):
        return templates.TemplateResponse(request, "login.html", {"error": "Too many attempts. Try again in a few minutes."}, status_code=429)
    if auth.authenticate(username, password):
        request.session.clear()
        request.session["user"] = username
        return RedirectResponse("/", status_code=303)
    auth.record_failure(ip)
    return templates.TemplateResponse(request, "login.html", {"error": "Invalid username or password"}, status_code=401)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/healthz")
def healthz():
    return {"ok": True}


# ---------------- pages ----------------
@app.get("/")
def dashboard(request: Request, user: str = Depends(auth.require_admin)):
    with session_scope() as s:
        runs = s.query(JobRun).order_by(JobRun.id.desc()).limit(20).all()
    return templates.TemplateResponse(request, "dashboard.html", {"user": user, "runs": runs, "st": manager.status()})


def _get_run(run_id: int) -> JobRun:
    with session_scope() as s:
        run = s.get(JobRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return run


@app.get("/runs/{run_id}")
def run_page(run_id: int, request: Request, user: str = Depends(auth.require_admin)):
    run = _get_run(run_id)
    data = json.loads(run.results_json) if run.results_json else {"summary": None, "checks": []}
    return templates.TemplateResponse(request, "run.html", {"user": user, "run": run, "data": data})


@app.get("/runs/{run_id}/download/{kind}")
def download(run_id: int, kind: str, user: str = Depends(auth.require_admin)):
    run = _get_run(run_id)
    path = {"report": run.report_path, "data": run.data_path}.get(kind)
    if not path or not os.path.exists(path):
        raise HTTPException(404, "File not available")
    return FileResponse(path, filename=os.path.basename(path))


@app.get("/config")
def config_page(request: Request, user: str = Depends(auth.require_admin)):
    return templates.TemplateResponse(request, "config.html", {"user": user, "path": str(CONFIG_PATH), "text": CONFIG_PATH.read_text(encoding="utf-8")})


# ---------------- job control API ----------------
@app.get("/api/job/status")
def job_status(user: str = Depends(auth.require_admin)):
    return manager.status()


@app.post("/api/job/start")
def job_start(user: str = Depends(auth.require_admin)):
    try:
        return {"ok": True, "message": manager.start_job()}
    except Exception as e:
        return JSONResponse({"ok": False, "message": f"Could not start: {e}"}, status_code=400)


@app.post("/api/job/stop")
def job_stop(user: str = Depends(auth.require_admin)):
    return {"ok": True, "message": manager.stop_job()}


@app.post("/api/job/kill")
def job_kill(user: str = Depends(auth.require_admin)):
    ok = manager.kill()
    return {"ok": ok, "message": "Running job killed" if ok else "No job is running"}


@app.post("/api/job/run")
def job_run(user: str = Depends(auth.require_admin)):
    rid = manager.run_now()
    if rid is None:
        return JSONResponse({"ok": False, "message": "A run is already in progress"}, status_code=409)
    return {"ok": True, "message": f"Run #{rid} started", "run_id": rid}


# ---------------- chat about a run ----------------
@app.post("/api/runs/{run_id}/chat")
async def chat(run_id: int, request: Request, user: str = Depends(auth.require_admin)):
    run = _get_run(run_id)
    if not run.results_json:
        raise HTTPException(400, "This run has no results to discuss")
    body = await request.json()
    message = str(body.get("message", "")).strip()
    if not message:
        raise HTTPException(400, "Empty message")
    data = json.loads(run.results_json)
    history = body.get("history") if isinstance(body.get("history"), list) else []
    answer = llm.chat(load_config()["llm"], data["checks"], data["summary"], history, message)
    return {"answer": answer}
