"""Read-only data source access. Oracle in production; SQLite for the demo/testing."""
import os
import re
import sqlite3

from .config import resolve

_READONLY_SQL = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)


def _clean_sql(sql: str) -> str:
    sql = sql.strip().rstrip(";").strip()
    if not _READONLY_SQL.match(sql):
        raise ValueError("Only SELECT / WITH queries are allowed")
    return sql


def run_query(source_cfg: dict, sql: str):
    """Return (columns, rows) for a read-only query."""
    sql = _clean_sql(sql)
    stype = (source_cfg.get("type") or "oracle").lower()
    max_rows = int(source_cfg.get("max_rows", 1_000_000))
    if stype == "oracle":
        return _run_oracle(source_cfg, sql, max_rows)
    if stype == "sqlite":
        return _run_sqlite(source_cfg, sql, max_rows)
    raise ValueError(f"Unknown source type: {stype}")


def _run_oracle(cfg: dict, sql: str, max_rows: int):
    import oracledb

    missing = [k for k in ("ORACLE_USER", "ORACLE_PASSWORD", "ORACLE_DSN") if not os.getenv(k)]
    if missing:
        raise RuntimeError(f"Missing environment variable(s): {', '.join(missing)} (set them in .env)")
    oracledb.defaults.fetch_lobs = False  # return LOBs as str/bytes
    conn = oracledb.connect(
        user=os.environ["ORACLE_USER"],
        password=os.environ["ORACLE_PASSWORD"],
        dsn=os.environ["ORACLE_DSN"],
    )
    try:
        conn.call_timeout = int(cfg.get("query_timeout_seconds", 300)) * 1000
        cur = conn.cursor()
        cur.arraysize = 5000
        try:
            cur.execute("SET TRANSACTION READ ONLY")  # belt and braces
        except Exception:
            pass
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = []
        while True:
            batch = cur.fetchmany(5000)
            if not batch:
                break
            rows.extend(batch)
            if len(rows) > max_rows:
                raise RuntimeError(f"Query returned more than max_rows ({max_rows})")
        return cols, rows
    finally:
        conn.close()


def _run_sqlite(cfg: dict, sql: str, max_rows: int):
    path = resolve(cfg.get("sqlite_path", "data/demo_source.db"))
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        cur = conn.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchmany(max_rows + 1)
        if len(rows) > max_rows:
            raise RuntimeError(f"Query returned more than max_rows ({max_rows})")
        return cols, rows
    finally:
        conn.close()
