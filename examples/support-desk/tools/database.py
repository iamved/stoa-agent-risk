"""Shared database access: Postgres for records, Redis for session cache.

Queries here are parameterized (the safe pattern). One internally generated
query is suppressed with a reviewed reason — demonstrating Stoa's rule-scoped
suppression.
"""

import os

import psycopg2
import redis

REPORT_TABLES = {"daily": "ticket_stats_daily", "weekly": "ticket_stats_weekly"}

cache = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))


def get_connection(password: str | None = None):
    return psycopg2.connect(
        host=os.environ["SUPPORT_DB_HOST"],
        dbname="support",
        user="support_app",
        password=password or os.environ["SUPPORT_DB_PASSWORD"],
    )


def count_recent_tickets(customer_id: str) -> int:
    cursor = get_connection().cursor()
    cursor.execute(
        "SELECT count(*) FROM tickets WHERE customer_id = %s AND opened_at > now() - interval '30 days'",
        (customer_id,),
    )
    return cursor.fetchone()[0]


def ticket_stats(period: str) -> list:
    table = REPORT_TABLES[period]
    cursor = get_connection().cursor()
    # stoa: ignore[SEC003] table name comes from the REPORT_TABLES enum above
    cursor.execute(f"SELECT day, opened, resolved FROM {table} ORDER BY day DESC")
    return cursor.fetchall()
