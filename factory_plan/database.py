from pathlib import Path
import sqlite3


DATA_DIR = Path("data")
DATABASE_PATH = DATA_DIR / "factory_plan.sqlite3"


SCHEMA = """
CREATE TABLE IF NOT EXISTS doors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    serial TEXT NOT NULL UNIQUE,
    order_date TEXT,
    planned_date TEXT,
    counterparty TEXT,
    order_number TEXT,
    door_type TEXT,
    model TEXT,
    size TEXT,
    leaf_count INTEGER,
    is_custom INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    door_id INTEGER NOT NULL,
    operation TEXT NOT NULL,
    line TEXT NOT NULL,
    sequence_index INTEGER NOT NULL,
    is_done INTEGER NOT NULL,
    hours REAL,
    is_required INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (door_id) REFERENCES doors(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS work_calendar (
    date TEXT PRIMARY KEY,
    is_working_day INTEGER NOT NULL,
    hours REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS priority_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_type TEXT NOT NULL,
    rule_value TEXT NOT NULL,
    priority INTEGER NOT NULL,
    comment TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plan_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_date TEXT NOT NULL,
    operation TEXT NOT NULL,
    line TEXT NOT NULL,
    door_id INTEGER NOT NULL,
    hours REAL NOT NULL,
    queue_priority INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (door_id) REFERENCES doors(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS plan_daily_load (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_date TEXT NOT NULL,
    operation TEXT NOT NULL,
    capacity_hours REAL NOT NULL,
    planned_hours REAL NOT NULL,
    overflow_hours REAL NOT NULL,
    door_count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database() -> None:
    connection = get_connection()
    try:
        connection.executescript(SCHEMA)
        connection.commit()
    finally:
        connection.close()
