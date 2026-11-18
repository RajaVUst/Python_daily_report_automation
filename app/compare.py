"""Compare query results (row counts / column totals) with expected values."""
import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path

from openpyxl import load_workbook

from .config import resolve


def load_reference(path: str | None) -> dict[str, dict]:
    """Reference file (.csv or .xlsx): columns check, expected, [tolerance], [tolerance_pct]."""
    if not path:
        return {}
    p = resolve(path)
    if not p.exists():
        raise FileNotFoundError(f"Reference file not found: {p}")
    if p.suffix.lower() in (".xlsx", ".xlsm"):
        ws = load_workbook(p, read_only=True, data_only=True).active
        rows = list(ws.iter_rows(values_only=True))
        headers = [str(h or "").strip().lower() for h in rows[0]]
        records = [dict(zip(headers, r)) for r in rows[1:]]
    else:
        with open(p, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            reader.fieldnames = [h.strip().lower() for h in reader.fieldnames or []]
            records = list(reader)
    ref = {}
    for r in records:
        name = str(r.get("check") or "").strip()
        if name:
            ref[name] = r
    return ref


def _num(v):
    if v is None or v == "":
        return None
    return float(Decimal(str(v)))


def _metric(metric: str, cols, rows, column):
    if metric == "row_count":
        return float(len(rows))
    if metric == "sum":
        idx = {c.lower(): i for i, c in enumerate(cols)}
        if not column or column.lower() not in idx:
            raise ValueError(f"column '{column}' not found in query result")
        i, total = idx[column.lower()], Decimal(0)
        for r in rows:
            if r[i] is not None:
                try:
                    total += Decimal(str(r[i]))
                except InvalidOperation:
                    raise ValueError(f"non-numeric value in column '{column}'")
        return float(total)
    raise ValueError(f"unsupported metric '{metric}' (use row_count or sum)")


def evaluate(checks: list[dict], data: dict, query_errors: dict, reference: dict) -> list[dict]:
    """data: {query_name: (cols, rows)}. Returns one result dict per check."""
    results = []
    for c in checks:
        name, qname, metric = c["name"], c["query"], c.get("metric", "row_count")
        res = {
            "name": name, "query": qname, "metric": metric, "column": c.get("column"),
            "expected": None, "actual": None, "difference": None, "tolerance": 0.0,
            "status": "ERROR", "note": "",
        }
        try:
            if qname in query_errors:
                raise RuntimeError(f"query '{qname}' failed: {query_errors[qname]}")
            if qname not in data:
                raise RuntimeError(f"query '{qname}' is not defined")
            ref = reference.get(name, {})
            expected = _num(c["expected"]) if c.get("expected") is not None else _num(ref.get("expected"))
            if expected is None:
                raise ValueError("no expected value (set 'expected' or add it to the reference file)")
            tol_abs = c.get("tolerance", ref.get("tolerance"))
            tol_pct = c.get("tolerance_pct", ref.get("tolerance_pct"))
            tol_abs, tol_pct = _num(tol_abs) or 0.0, _num(tol_pct) or 0.0
            cols, rows = data[qname]
            actual = _metric(metric, cols, rows, c.get("column"))
            diff = round(actual - expected, 6)
            allowed = max(tol_abs, abs(expected) * tol_pct / 100.0)
            res.update(expected=expected, actual=actual, difference=diff, tolerance=allowed,
                       status="PASS" if abs(diff) <= allowed else "FAIL")
        except Exception as e:  # one bad check must not stop the others
            res["note"] = str(e)
        results.append(res)
    return results


def summarize(results: list[dict]) -> dict:
    n = lambda s: sum(1 for r in results if r["status"] == s)
    passed, failed, errors = n("PASS"), n("FAIL"), n("ERROR")
    return {
        "total": len(results), "passed": passed, "failed": failed, "errors": errors,
        "overall": "PASS" if results and failed == 0 and errors == 0 else "FAIL",
    }
