"""The daily pipeline: query -> Excel -> compare -> summarize -> report -> email."""
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from . import compare, emailer, excel, llm, sources
from .config import OUTPUT_DIR, load_config
from .db import JobRun, session_scope, utcnow

log = logging.getLogger("runner")


def _update(run_id: int, **fields) -> None:
    with session_scope() as s:
        run = s.get(JobRun, run_id)
        for k, v in fields.items():
            setattr(run, k, v)


def _fmt(template: str, **kw) -> str:
    try:
        return template.format(**kw)
    except (KeyError, IndexError):
        return template


def execute_run(run_id: int) -> None:
    cfg = load_config()
    tz = ZoneInfo(cfg["timezone"])
    now = datetime.now(tz)
    stamp = now.strftime("%Y%m%d_%H%M%S")
    job = cfg["job"]["name"]
    _update(run_id, status="running")

    with session_scope() as s:
        trigger = s.get(JobRun, run_id).trigger

    try:
        # 1. Run configured queries (read-only) against the source DB
        data, query_errors = {}, {}
        for q in cfg["queries"]:
            try:
                data[q["name"]] = sources.run_query(cfg["source"], q["sql"])
                log.info("query %s: %d rows", q["name"], len(data[q["name"]][1]))
            except Exception as e:
                query_errors[q["name"]] = str(e)
                log.error("query %s failed: %s", q["name"], e)
        if cfg["queries"] and not data:
            raise RuntimeError("All queries failed: " + "; ".join(f"{k}: {v}" for k, v in query_errors.items()))

        # 2. Populate Excel with the raw results
        data_path = OUTPUT_DIR / f"{job}_{stamp}_data.xlsx"
        excel.write_data_workbook(data_path, data)

        # 3. Compare with expected values (inline config and/or reference file)
        reference = compare.load_reference(cfg.get("reference_file"))
        results = compare.evaluate(cfg["checks"], data, query_errors, reference)
        summary = compare.summarize(results)

        # 4. LLM summary (optional, fails soft) and report workbook
        llm_text = llm.summarize(cfg["llm"], results, summary)
        text_summary = llm_text or llm.fallback_summary(results, summary)
        report_path = OUTPUT_DIR / f"{job}_{stamp}_report.xlsx"
        meta = {"run_id": run_id, "trigger": trigger, "title": now.strftime("%d %b %Y"),
                "when": now.strftime("%Y-%m-%d %H:%M %Z")}
        excel.write_report_workbook(report_path, meta, results, summary, llm_text)

        # 5. Email
        email_cfg = cfg["email"]
        email_status = "disabled"
        try:
            ctx = dict(date=now.strftime("%Y-%m-%d"), status=summary["overall"], job=job, **summary)
            subject = _fmt(email_cfg.get("subject", "Daily reconciliation {date}: {status}"), **ctx)
            body = (f"Daily reconciliation - {ctx['date']}\n"
                    f"Overall: {summary['overall']} ({summary['passed']} passed, {summary['failed']} failed, "
                    f"{summary['errors']} errors)\n\n{text_summary}\n\n"
                    "The full report is attached.")
            attach = [report_path] + ([data_path] if email_cfg.get("attach_raw_data") else [])
            email_status = emailer.send(email_cfg, subject, body, attach)
        except Exception as e:
            email_status = f"FAILED: {e}"
            log.error("email failed: %s", e)

        _update(run_id, status="success", finished_at=utcnow(), report_path=str(report_path),
                data_path=str(data_path), results_json=json.dumps({"summary": summary, "checks": results}),
                llm_summary=text_summary, email_status=email_status)
    except Exception as e:
        log.exception("run %s failed", run_id)
        failure_status = "disabled"
        try:
            ec = cfg["email"]
            if ec.get("enabled") and ec.get("send_on_failure", True):
                failure_status = emailer.send(ec, f"Daily reconciliation FAILED {now:%Y-%m-%d}",
                                              f"The {job} run failed before a report could be produced:\n\n{e}")
        except Exception as e2:
            failure_status = f"FAILED: {e2}"
        _update(run_id, status="failed", finished_at=utcnow(), error=str(e), email_status=failure_status)
