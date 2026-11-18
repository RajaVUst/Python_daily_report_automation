# Daily Recon

Automates a daily manual check: run read-only queries on Oracle, write the results to Excel,
compare row counts / column totals with expected values, build a summary report (with a Claude-written
explanation of mismatches) and email it. An admin portal starts, stops and kills the job.

## Quick start (demo mode, no Oracle needed)

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # set SECRET_KEY, ADMIN_PASSWORD, ANTHROPIC_API_KEY
python scripts/seed_demo.py                            # creates data/demo_source.db
uvicorn app.main:app --port 8000                       # keep a SINGLE worker
```

Open http://localhost:8000, sign in as the admin, press **Run now**. Reports land in `output/`.

## Going live with Oracle

1. In `config/config.yaml` set `source.type: oracle` and define your `queries` (SELECT / WITH only).
2. Put `ORACLE_USER`, `ORACLE_PASSWORD`, `ORACLE_DSN` in `.env`. Use a read-only database account.
3. Define `checks` (`row_count` or `sum` of a column) and expected values, either inline (`expected:`)
   or in `config/reference.csv` / `.xlsx` (columns `check, expected, tolerance, tolerance_pct`).
4. Set `email.enabled: true` and fill in SMTP details; `SMTP_USER` / `SMTP_PASSWORD` go in `.env`.
5. Set the schedule in `job.cron` and press **Start** in the portal.

## Portal buttons

| Button | Effect |
|---|---|
| Start | Enables the cron schedule (survives restarts) |
| Stop | Disables the schedule; a run in progress finishes |
| Kill | Terminates the run in progress immediately |
| Run now | Triggers a manual run (refused if one is already running) |

## Layout

- `app/main.py` portal and API; `app/scheduler.py` start/stop/kill (each run is a subprocess)
- `app/runner.py` pipeline; `sources.py` Oracle/SQLite reader; `compare.py` checks; `excel.py` workbooks
- `app/llm.py` Claude summary and chat; `emailer.py` SMTP; `auth.py` admin login
- App database (users, run history) is separate from Oracle: SQLite by default, or set `APP_DB_URL` (e.g. PostgreSQL)

## Notes

- Oracle is only read. Queries must start with SELECT/WITH and the session is set `READ ONLY`.
- The whole result set is held in memory before writing Excel; `source.max_rows` caps it (Excel limit is about 1M rows per sheet).
- If the LLM is disabled or fails, the report and email still go out with a plain-text summary.
- Raw data workbooks contain whatever your queries return; attach them to email only if appropriate (`attach_raw_data`).
- Behind HTTPS set `HTTPS_ONLY=true`. Run one uvicorn worker, otherwise each worker would schedule the job.
- Login is throttled after 5 failures per IP in 5 minutes. For production put the portal behind your reverse proxy / VPN.
