from datetime import date, datetime, timedelta
import json
from typing import Any

from fastapi import APIRouter, Body, HTTPException, UploadFile
from pydantic import BaseModel

from factory_plan.database import get_connection
from factory_plan.importer import (
    import_door_file,
    import_from_folder,
    import_payload,
    parse_door_file,
    result_to_dict,
)
from factory_plan.scheduler import recalculate_plan


router = APIRouter()

DOOR_DATA_TABLES = ("plan_daily_load", "plan_items", "operations", "doors")


class CalendarDayPayload(BaseModel):
    is_working_day: bool
    hours: float


class CalendarGeneratePayload(BaseModel):
    days: int = 120
    hours: float = 8.0


class CalendarSettingsPayload(BaseModel):
    default_work_hours: int


class CalendarRefillPayload(BaseModel):
    after_date: date
    days: int = 365
    hours: int | None = None


class PriorityRulePayload(BaseModel):
    rule_type: str
    rule_value: str
    priority: int
    comment: str | None = None


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/doors")
def list_doors(
    serial: str | None = None,
    counterparty: str | None = None,
    order_number: str | None = None,
    door_type: str | None = None,
    model: str | None = None,
) -> list[dict]:
    where, params = _door_filters(serial, counterparty, order_number, door_type, model)
    with get_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT
                id, serial, order_date, planned_date, counterparty, order_number,
                door_type, model, size, leaf_count, is_custom
            FROM doors
            {where}
            ORDER BY planned_date, order_date, serial
            LIMIT 500
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


@router.post("/doors/clear")
def clear_doors() -> dict:
    deleted = {}
    connection = get_connection()
    try:
        connection.execute("BEGIN")
        try:
            for table in DOOR_DATA_TABLES:
                deleted[table] = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in DOOR_DATA_TABLES:
                connection.execute(f"DELETE FROM {table}")
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()
    finally:
        connection.close()
    return {"success": True, "deleted": deleted}


@router.post("/import/preview")
async def preview_import(file: UploadFile) -> dict:
    content = await file.read()
    preview = parse_door_file(content, file.filename or "")
    return {
        "filename": file.filename,
        "row_count": preview.row_count,
        "columns": preview.columns,
        "warnings": preview.warnings,
        "sample": preview.sample,
    }


@router.post("/import")
async def import_file(file: UploadFile) -> dict:
    content = await file.read()
    with get_connection() as connection:
        result = import_door_file(connection, content, file.filename or "")
    response = result_to_dict(result)
    response["filename"] = file.filename
    return response


@router.post("/import/json")
def import_json(payload: Any = Body(...)) -> dict:
    result = import_payload(payload)
    return result_to_dict(result)


@router.post("/import/file")
async def import_json_upload(file: UploadFile) -> dict:
    content = await file.read()
    try:
        payload = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {
            "success": False,
            "created_doors": 0,
            "updated_doors": 0,
            "operations_written": 0,
            "warnings": [],
            "errors": [f"{file.filename}: JSON parse error: {exc}"],
        }
    response = result_to_dict(import_payload(payload))
    response["filename"] = file.filename
    return response


@router.post("/import/from-folder")
def import_json_from_folder() -> dict:
    return result_to_dict(import_from_folder())


@router.get("/calendar")
def list_calendar() -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT date, is_working_day, hours
            FROM work_calendar
            ORDER BY date
            LIMIT 180
            """
        ).fetchall()
    return [dict(row) for row in rows]


@router.get("/calendar/settings")
def get_calendar_settings() -> dict:
    return {"default_work_hours": _get_default_work_hours()}


@router.put("/calendar/settings")
def update_calendar_settings(payload: CalendarSettingsPayload) -> dict:
    default_work_hours = max(1, min(int(payload.default_work_hours), 24))
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO app_settings (key, value)
            VALUES ('default_work_hours', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (str(default_work_hours),),
        )
    return {"default_work_hours": default_work_hours}


@router.post("/calendar/refill-after")
def refill_calendar_after(payload: CalendarRefillPayload) -> dict:
    days = max(1, min(payload.days, 730))
    default_work_hours = _get_default_work_hours() if payload.hours is None else max(1, min(int(payload.hours), 24))
    start = payload.after_date + timedelta(days=1)
    changed_days = 0
    with get_connection() as connection:
        for offset in range(days):
            day = start + timedelta(days=offset)
            is_working_day = int(day.weekday() < 5)
            hours = default_work_hours if is_working_day else 0
            connection.execute(
                """
                INSERT INTO work_calendar (date, is_working_day, hours)
                VALUES (?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    is_working_day = excluded.is_working_day,
                    hours = excluded.hours
                """,
                (day.isoformat(), is_working_day, hours),
            )
            changed_days += 1
    return {
        "after_date": payload.after_date.isoformat(),
        "start_date": start.isoformat(),
        "changed_days": changed_days,
        "default_work_hours": default_work_hours,
    }


@router.put("/calendar/{calendar_date}")
def update_calendar_day(calendar_date: date, payload: CalendarDayPayload) -> dict:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO work_calendar (date, is_working_day, hours)
            VALUES (?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                is_working_day = excluded.is_working_day,
                hours = excluded.hours
            """,
            (calendar_date.isoformat(), int(payload.is_working_day), payload.hours),
        )
    return {"date": calendar_date.isoformat(), "is_working_day": int(payload.is_working_day), "hours": payload.hours}


@router.post("/calendar/generate")
def generate_calendar(payload: CalendarGeneratePayload) -> dict:
    days = max(1, min(payload.days, 365))
    start = date.today()
    with get_connection() as connection:
        for offset in range(days):
            day = start + timedelta(days=offset)
            is_working_day = int(day.weekday() < 5)
            hours = payload.hours if is_working_day else 0.0
            connection.execute(
                """
                INSERT OR IGNORE INTO work_calendar (date, is_working_day, hours)
                VALUES (?, ?, ?)
                """,
                (day.isoformat(), is_working_day, hours),
            )
    return {"generated_days": days}


@router.get("/priorities")
def list_priorities() -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, rule_type, rule_value, priority, comment, created_at
            FROM priority_rules
            ORDER BY priority, id
            """
        ).fetchall()
    return [dict(row) for row in rows]


@router.post("/priorities")
def create_priority(payload: PriorityRulePayload) -> dict:
    if payload.rule_type not in {"serial", "order_number", "counterparty"}:
        raise HTTPException(status_code=400, detail="Unknown rule_type")
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO priority_rules (rule_type, rule_value, priority, comment, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                payload.rule_type,
                payload.rule_value.strip(),
                payload.priority,
                payload.comment or "",
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        rule_id = cursor.lastrowid
    return {"id": rule_id}


@router.delete("/priorities/{rule_id}")
def delete_priority(rule_id: int) -> dict:
    with get_connection() as connection:
        cursor = connection.execute("DELETE FROM priority_rules WHERE id = ?", (rule_id,))
    return {"deleted": cursor.rowcount}


@router.post("/plan/recalculate")
def recalculate() -> dict:
    recalculate_plan()
    with get_connection() as connection:
        stats = connection.execute(
            """
            SELECT
                COUNT(*) AS operation_count,
                COUNT(DISTINCT plan_date) AS day_count
            FROM plan_items
            """
        ).fetchone()
        overflow = connection.execute(
            """
            SELECT COUNT(*) AS overflow_count
            FROM plan_daily_load
            WHERE overflow_hours > 0
            """
        ).fetchone()
    return {
        "operation_count": stats["operation_count"],
        "day_count": stats["day_count"],
        "overflow_count": overflow["overflow_count"],
    }


@router.get("/plan")
def list_plan() -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                p.id, p.plan_date, p.operation, p.line, d.serial, d.counterparty,
                d.order_number, d.door_type, d.model, d.size, d.leaf_count,
                p.hours, p.queue_priority
            FROM plan_items p
            JOIN doors d ON d.id = p.door_id
            ORDER BY p.plan_date, p.operation, d.serial
            LIMIT 1000
            """
        ).fetchall()
    return [dict(row) for row in rows]


@router.get("/plan/load")
def list_plan_load() -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                id, plan_date, operation, capacity_hours, planned_hours,
                overflow_hours, door_count
            FROM plan_daily_load
            ORDER BY plan_date, operation
            LIMIT 1000
            """
        ).fetchall()
    return [dict(row) for row in rows]


def _door_filters(*values: str | None) -> tuple[str, dict[str, str]]:
    names = ["serial", "counterparty", "order_number", "door_type", "model"]
    clauses = []
    params = {}
    for name, value in zip(names, values):
        if value:
            clauses.append(f"{name} LIKE :{name}")
            params[name] = f"%{value}%"
    return ("WHERE " + " AND ".join(clauses), params) if clauses else ("", params)


def _get_default_work_hours() -> int:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT value FROM app_settings WHERE key = 'default_work_hours'"
        ).fetchone()
    if not row:
        return 8
    try:
        return max(1, min(int(row["value"]), 24))
    except (TypeError, ValueError):
        return 8
