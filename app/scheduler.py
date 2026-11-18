"""Job control. Start = enable the schedule, Stop = disable it (a running run finishes),
Kill = terminate the run in progress immediately, Run now = trigger a manual run."""
import logging
import subprocess
import sys
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import BASE_DIR, load_config
from .db import JobRun, JobState, session_scope, utcnow

log = logging.getLogger("scheduler")
JOB_ID = "daily_recon"


class JobManager:
    def __init__(self):
        self.sched = BackgroundScheduler()
        self.lock = threading.RLock()
        self.proc: subprocess.Popen | None = None
        self.run_id: int | None = None
        self.killed: set[int] = set()

    # ---------- lifecycle ----------
    def startup(self) -> None:
        cfg = load_config()
        self.sched.configure(timezone=cfg["timezone"])
        self.sched.start()
        with session_scope() as s:
            for r in s.query(JobRun).filter(JobRun.status.in_(["queued", "running"])).all():
                r.status, r.finished_at, r.error = "failed", utcnow(), "Orphaned (application restarted)"
        with session_scope() as s:
            if self._state(s).enabled:
                self._add_schedule()

    def shutdown(self) -> None:
        self.kill()
        self.sched.shutdown(wait=False)

    def _state(self, s) -> JobState:
        name = load_config()["job"]["name"]
        st = s.query(JobState).filter_by(name=name).first()
        if not st:
            st = JobState(name=name, enabled=False)
            s.add(st)
            s.flush()
        return st

    def _add_schedule(self) -> None:
        cfg = load_config()
        trig = CronTrigger.from_crontab(cfg["job"]["cron"], timezone=cfg["timezone"])
        self.sched.add_job(lambda: self.spawn("scheduled"), trig, id=JOB_ID, replace_existing=True,
                           max_instances=1, coalesce=True, misfire_grace_time=3600)

    # ---------- actions ----------
    def start_job(self) -> str:
        with self.lock:
            self._add_schedule()  # re-reads cron from config
            with session_scope() as s:
                self._state(s).enabled = True
        return "Schedule started"

    def stop_job(self) -> str:
        with self.lock:
            if self.sched.get_job(JOB_ID):
                self.sched.remove_job(JOB_ID)
            with session_scope() as s:
                self._state(s).enabled = False
        return "Schedule stopped" + (" (current run will finish)" if self.is_active() else "")

    def run_now(self) -> int | None:
        return self.spawn("manual")

    def kill(self) -> bool:
        with self.lock:
            if not self.is_active():
                return False
            self.killed.add(self.run_id)
            proc = self.proc
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        return True

    # ---------- internals ----------
    def is_active(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def spawn(self, trigger: str) -> int | None:
        with self.lock:
            if self.is_active():
                log.warning("Run already in progress; skipping %s trigger", trigger)
                return None
            with session_scope() as s:
                run = JobRun(job_name=load_config()["job"]["name"], trigger=trigger, status="queued", started_at=utcnow())
                s.add(run)
                s.flush()
                rid = run.id
            proc = subprocess.Popen([sys.executable, "-m", "app.run_job", "--run-id", str(rid)], cwd=BASE_DIR)
            with session_scope() as s:
                s.get(JobRun, rid).pid = proc.pid
            self.proc, self.run_id = proc, rid
            threading.Thread(target=self._watch, args=(proc, rid), daemon=True).start()
            return rid

    def _watch(self, proc: subprocess.Popen, rid: int) -> None:
        code = proc.wait()
        with self.lock:
            was_killed = rid in self.killed
            self.killed.discard(rid)
            if self.run_id == rid:
                self.proc, self.run_id = None, None
        with session_scope() as s:
            run = s.get(JobRun, rid)
            if was_killed:
                run.status, run.error, run.finished_at = "killed", "Killed from portal", utcnow()
            elif run.status in ("queued", "running"):
                run.status, run.finished_at = "failed", utcnow()
                run.error = f"Process exited unexpectedly (code {code})"

    def status(self) -> dict:
        cfg = load_config()
        tz = ZoneInfo(cfg["timezone"])
        job = self.sched.get_job(JOB_ID)
        nxt = job.next_run_time.astimezone(tz).strftime("%Y-%m-%d %H:%M %Z") if job and job.next_run_time else None
        with session_scope() as s:
            last = s.query(JobRun).order_by(JobRun.id.desc()).first()
            return {
                "enabled": bool(job),
                "next_run": nxt,
                "cron": cfg["job"]["cron"],
                "timezone": cfg["timezone"],
                "running": self.is_active(),
                "running_run_id": self.run_id if self.is_active() else None,
                "last_run_id": last.id if last else None,
                "last_run_status": last.status if last else None,
            }


manager = JobManager()
