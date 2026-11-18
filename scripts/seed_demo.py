"""Create a small demo source database so the app runs without Oracle."""
import sqlite3
from pathlib import Path

path = Path(__file__).resolve().parent.parent / "data" / "demo_source.db"
path.parent.mkdir(exist_ok=True)
path.unlink(missing_ok=True)
c = sqlite3.connect(path)
c.executescript("""
CREATE TABLE orders (order_id INTEGER, customer TEXT, amount REAL, order_date TEXT);
CREATE TABLE payments (payment_id INTEGER, order_id INTEGER, amount REAL, paid_on TEXT);
""")
c.executemany("INSERT INTO orders VALUES (?,?,?,?)", [
    (1, "Acme", 100, "2026-11-17"), (2, "Globex", 250, "2026-11-17"), (3, "Initech", 300, "2026-11-17"),
    (4, "Umbrella", 150, "2026-11-17"), (5, "Hooli", 200, "2026-11-17"), (6, "Stark", 300, "2026-11-17")])
c.executemany("INSERT INTO payments VALUES (?,?,?,?)", [
    (1, 1, 100, "2026-11-17"), (2, 2, 250, "2026-11-17"), (3, 3, 300, "2026-11-17"),
    (4, 4, 150, "2026-11-17"), (5, 5, 195, "2026-11-17")])
c.commit()
print("Demo DB written to", path)
