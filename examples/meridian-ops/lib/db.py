"""Shared DB access — parameterized (must NOT trip SEC003)."""
import psycopg2, os
REPORTS = {"daily": "rpt_daily", "weekly": "rpt_weekly"}
def get(uid):
    cur = psycopg2.connect(os.environ["DB_URL"]).cursor()
    cur.execute("SELECT * FROM users WHERE id = %s", (uid,))       # parameterized -> no SEC003
    return cur.fetchone()
def report(period):
    table = REPORTS[period]
    cur = psycopg2.connect(os.environ["DB_URL"]).cursor()
    # stoa: ignore[SEC003] table name comes from the REPORTS enum above
    cur.execute(f"SELECT day, total FROM {table} ORDER BY day")    # SEC003 suppressed inline
    return cur.fetchall()
