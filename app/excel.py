"""Excel output: raw query data workbook and the summary report workbook."""
import re
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

_FILL = {
    "PASS": PatternFill("solid", fgColor="C6EFCE"),
    "FAIL": PatternFill("solid", fgColor="FFC7CE"),
    "ERROR": PatternFill("solid", fgColor="FFEB9C"),
}
_HEADER = PatternFill("solid", fgColor="D9E1F2")


def _sheet_name(name: str, used: set) -> str:
    base = re.sub(r"[\[\]\*\?/\\:]", "_", name)[:31] or "Sheet"
    out, i = base, 1
    while out in used:
        i += 1
        out = f"{base[:28]}_{i}"
    used.add(out)
    return out


def write_data_workbook(path: Path, data: dict) -> None:
    """One sheet per query. Write-only mode keeps memory low for large results."""
    wb = Workbook(write_only=True)
    used: set = set()
    for qname, (cols, rows) in data.items():
        ws = wb.create_sheet(_sheet_name(qname, used))
        ws.append(list(cols))
        for r in rows:
            ws.append([_cell(v) for v in r])
    if not data:
        wb.create_sheet("empty")
    wb.save(path)


def _cell(v):
    # openpyxl can't store tz-aware datetimes or arbitrary objects
    if hasattr(v, "tzinfo") and v.tzinfo is not None:
        return v.replace(tzinfo=None)
    if isinstance(v, (bytes, bytearray)):
        return v.hex()
    return v


def write_report_workbook(path: Path, meta: dict, results: list[dict], summary: dict, llm_text: str | None) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws["A1"] = f"Daily reconciliation report - {meta['title']}"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = f"Run #{meta['run_id']} ({meta['trigger']}) at {meta['when']}"
    ws["A3"] = (f"Overall: {summary['overall']}   |   {summary['passed']} passed, "
                f"{summary['failed']} failed, {summary['errors']} errors, {summary['total']} checks")
    ws["A3"].font = Font(bold=True)

    headers = ["Check", "Query", "Metric", "Column", "Expected", "Actual", "Difference", "Tolerance", "Status", "Note"]
    hr = 5
    for i, h in enumerate(headers, 1):
        c = ws.cell(row=hr, column=i, value=h)
        c.font, c.fill = Font(bold=True), _HEADER
    for n, r in enumerate(results, hr + 1):
        vals = [r["name"], r["query"], r["metric"], r["column"], r["expected"], r["actual"],
                r["difference"], r["tolerance"], r["status"], r["note"]]
        for i, v in enumerate(vals, 1):
            ws.cell(row=n, column=i, value=v)
        ws.cell(row=n, column=9).fill = _FILL.get(r["status"], PatternFill())
    for col, w in zip("ABCDEFGHIJ", [34, 16, 12, 14, 14, 14, 14, 12, 10, 50]):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = ws.cell(row=hr + 1, column=1)

    if llm_text:
        ws2 = wb.create_sheet("AI summary")
        ws2.column_dimensions["A"].width = 120
        for i, line in enumerate(llm_text.splitlines() or [llm_text], 1):
            c = ws2.cell(row=i, column=1, value=line)
            c.alignment = Alignment(wrap_text=True, vertical="top")
    wb.save(path)
