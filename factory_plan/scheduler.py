from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
import sqlite3

from factory_plan.database import get_connection


DEPENDENCIES = {
    "Заготовка": set(),
    "Зварка": {"Заготовка"},
    "Фарбування": {"Зварка"},
    "МДФ": set(),
    "Зборка": {"Фарбування", "МДФ"},
    "Упаковка": {"Зборка"},
}

SPECIFICITY = {"serial": 0, "order_number": 1, "counterparty": 2}


@dataclass
class OperationState:
    id: int
    door_id: int
    operation: str
    line: str
    sequence_index: int
    hours: float
    completed: bool
    planned: bool = False


def recalculate_plan(start_date: date | None = None) -> None:
    start = start_date or date.today()
    with get_connection() as connection:
        connection.execute("DELETE FROM plan_items")
        connection.execute("DELETE FROM plan_daily_load")
        _ensure_calendar(connection, start, 120)
        doors = _load_doors(connection)
        rules = _load_priority_rules(connection)
        operations_by_door = _load_operations(connection)
        queue_priority = {door["id"]: _queue_priority(door, rules) for door in doors}

        working_days = _load_working_days(connection, start)
        scheduled_by_day: dict[str, set[int]] = defaultdict(set)
        scheduled_rows = []

        for day in working_days:
            capacity_by_operation: dict[str, float] = defaultdict(lambda: float(day["hours"]))
            day_closed_operations: set[str] = set()
            made_progress = True
            while made_progress:
                made_progress = False
                for operation_name in DEPENDENCIES:
                    if operation_name in day_closed_operations:
                        continue
                    candidates = [
                        door for door in doors
                        if door["id"] not in scheduled_by_day[day["date"]]
                        and _is_next_ready_operation(operations_by_door[door["id"]], operation_name)
                    ]
                    candidates.sort(key=lambda door: _sort_key(door, queue_priority[door["id"]]))
                    if not candidates:
                        continue
                    door = candidates[0]
                    operation = _find_operation(operations_by_door[door["id"]], operation_name)
                    if operation is None:
                        continue
                    planned_hours = _planned_hours_for_day(scheduled_rows, day["date"], operation_name)
                    overflows = planned_hours + operation.hours > capacity_by_operation[operation_name]
                    scheduled_rows.append((day["date"], operation, queue_priority[door["id"]]))
                    operation.planned = True
                    scheduled_by_day[day["date"]].add(door["id"])
                    made_progress = True
                    if overflows:
                        day_closed_operations.add(operation_name)

            if _all_planned(operations_by_door):
                break

        _write_plan(connection, scheduled_rows)


def _load_doors(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT id, serial, planned_date, order_date, counterparty, order_number
        FROM doors
        ORDER BY planned_date, order_date, serial
        """
    ).fetchall()


def _load_operations(connection: sqlite3.Connection) -> dict[int, list[OperationState]]:
    rows = connection.execute(
        """
        SELECT id, door_id, operation, line, sequence_index, is_done, hours
        FROM operations
        WHERE is_required = 1 AND hours > 0
        ORDER BY door_id, sequence_index
        """
    ).fetchall()
    operations: dict[int, list[OperationState]] = defaultdict(list)
    for row in rows:
        operations[row["door_id"]].append(
            OperationState(
                id=row["id"],
                door_id=row["door_id"],
                operation=row["operation"],
                line=row["line"],
                sequence_index=row["sequence_index"],
                hours=float(row["hours"] or 0),
                completed=bool(row["is_done"]),
            )
        )
    return operations


def _load_priority_rules(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT rule_type, rule_value, priority
        FROM priority_rules
        ORDER BY priority, id
        """
    ).fetchall()


def _queue_priority(door: sqlite3.Row, rules: list[sqlite3.Row]) -> tuple[int, int]:
    matches = []
    for rule in rules:
        rule_type = rule["rule_type"]
        if str(door[rule_type] or "").strip() == str(rule["rule_value"] or "").strip():
            matches.append((SPECIFICITY[rule_type], int(rule["priority"])))
    if not matches:
        return (1, 0)
    specificity, priority = sorted(matches, key=lambda item: (item[0], item[1]))[0]
    return (0, priority * 10 + specificity)


def _sort_key(door: sqlite3.Row, queue_priority: tuple[int, int]) -> tuple:
    has_no_rule, priority = queue_priority
    return (
        has_no_rule,
        priority,
        door["planned_date"] or "9999-12-31",
        door["order_date"] or "9999-12-31",
        door["serial"],
    )


def _is_next_ready_operation(operations: list[OperationState], operation_name: str) -> bool:
    operation = _find_operation(operations, operation_name)
    if operation is None or operation.completed or operation.planned:
        return False
    existing_operations = {item.operation for item in operations}
    completed = {item.operation for item in operations if item.completed or item.planned}
    dependencies = DEPENDENCIES[operation_name] & existing_operations
    return dependencies <= completed


def _find_operation(operations: list[OperationState], operation_name: str) -> OperationState | None:
    return next((item for item in operations if item.operation == operation_name), None)


def _all_planned(operations_by_door: dict[int, list[OperationState]]) -> bool:
    for operations in operations_by_door.values():
        for operation in operations:
            if not operation.completed and not operation.planned:
                return False
    return True


def _ensure_calendar(connection: sqlite3.Connection, start: date, days: int) -> None:
    for offset in range(days):
        day = start + timedelta(days=offset)
        is_working_day = int(day.weekday() < 5)
        hours = 8.0 if is_working_day else 0.0
        connection.execute(
            """
            INSERT OR IGNORE INTO work_calendar (date, is_working_day, hours)
            VALUES (?, ?, ?)
            """,
            (day.isoformat(), is_working_day, hours),
        )


def _load_working_days(connection: sqlite3.Connection, start: date) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT date, hours
        FROM work_calendar
        WHERE date >= ? AND is_working_day = 1 AND hours > 0
        ORDER BY date
        LIMIT 240
        """,
        (start.isoformat(),),
    ).fetchall()


def _planned_hours_for_day(rows: list[tuple[str, OperationState, tuple[int, int]]], plan_date: str, operation: str) -> float:
    return sum(row[1].hours for row in rows if row[0] == plan_date and row[1].operation == operation)


def _write_plan(connection: sqlite3.Connection, rows: list[tuple[str, OperationState, tuple[int, int]]]) -> None:
    for plan_date, operation, queue_priority in rows:
        connection.execute(
            """
            INSERT INTO plan_items
                (plan_date, operation, line, door_id, hours, queue_priority)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (plan_date, operation.operation, operation.line, operation.door_id, operation.hours, queue_priority[1]),
        )

    loads = {}
    for plan_date, operation, _priority in rows:
        key = (plan_date, operation.operation)
        if key not in loads:
            loads[key] = {"planned_hours": 0.0, "door_ids": set()}
        loads[key]["planned_hours"] += operation.hours
        loads[key]["door_ids"].add(operation.door_id)

    capacity_rows = connection.execute("SELECT date, hours FROM work_calendar").fetchall()
    capacity_by_date = {row["date"]: float(row["hours"]) for row in capacity_rows}
    for (plan_date, operation), load in loads.items():
        capacity = capacity_by_date.get(plan_date, 0.0)
        planned = load["planned_hours"]
        connection.execute(
            """
            INSERT INTO plan_daily_load
                (plan_date, operation, capacity_hours, planned_hours, overflow_hours, door_count)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (plan_date, operation, capacity, planned, max(0.0, planned - capacity), len(load["door_ids"])),
        )
