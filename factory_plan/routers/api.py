from fastapi import APIRouter, UploadFile

from factory_plan.database import get_connection
from factory_plan.importer import parse_door_file


router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/doors")
def list_doors() -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                id,
                serial,
                order_date,
                planned_date,
                counterparty,
                order_number,
                door_type,
                model,
                size,
                leaf_count,
                is_custom
            FROM doors
            ORDER BY planned_date, order_date, serial
            LIMIT 500
            """
        ).fetchall()
    return [dict(row) for row in rows]


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


@router.get("/calendar")
def list_calendar() -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT date, is_working_day, hours
            FROM work_calendar
            ORDER BY date
            LIMIT 120
            """
        ).fetchall()
    return [dict(row) for row in rows]


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


@router.get("/plan")
def list_plan() -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                p.id,
                p.plan_date,
                p.operation,
                p.line,
                d.serial,
                d.counterparty,
                d.order_number,
                d.door_type,
                d.model,
                d.size,
                d.leaf_count,
                p.hours,
                p.queue_priority
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
                id,
                plan_date,
                operation,
                capacity_hours,
                planned_hours,
                overflow_hours,
                door_count
            FROM plan_daily_load
            ORDER BY plan_date, operation
            LIMIT 1000
            """
        ).fetchall()
    return [dict(row) for row in rows]

