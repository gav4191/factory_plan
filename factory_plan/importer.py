import csv
from dataclasses import asdict, dataclass
from datetime import datetime
import io
import json
from pathlib import Path
import shutil
import sqlite3
from typing import Any

from factory_plan.database import DATA_DIR, get_connection


EXPECTED_COLUMNS = [
    "Серія",
    "Дата заказа",
    "Планована дата виготовлення",
    "Заготовка готово",
    "Час заготовка",
    "Зварка готово",
    "Час зварка",
    "Фарбування готово",
    "Час фарба",
    "МДФГотово",
    "Час МДФ",
    "Зборка готово",
    "Час зборка",
    "Упаковка готово",
    "Час упаковка",
    "Тип",
    "Модель",
    "Розмір",
    "Кількість створок",
]

OPTIONAL_COLUMNS = [
    "Контрагент",
    "Номер замовлення",
    "Нестандарт",
]

TSV_OPERATION_COLUMNS = [
    ("Заготовка", "A", 1, "Заготовка готово", "Час заготовка"),
    ("Зварка", "A", 2, "Зварка готово", "Час зварка"),
    ("Фарбування", "A", 3, "Фарбування готово", "Час фарба"),
    ("МДФ", "B", 1, "МДФГотово", "Час МДФ"),
    ("Зборка", "C", 1, "Зборка готово", "Час зборка"),
    ("Упаковка", "C", 2, "Упаковка готово", "Час упаковка"),
]

JSON_OPERATION_COLUMNS = {
    "blank": ("Заготовка", "A", 1),
    "welding": ("Зварка", "A", 2),
    "painting": ("Фарбування", "A", 3),
    "mdf": ("МДФ", "B", 1),
    "assembly": ("Зборка", "C", 1),
    "packing": ("Упаковка", "C", 2),
}

REQUIRED_DOOR_FIELDS = [
    "serial",
    "order_date",
    "planned_date",
    "counterparty",
    "order_number",
    "door_type",
    "model",
    "size",
    "leaf_count",
    "operations",
]

IMPORT_INBOX = DATA_DIR / "import" / "inbox"
IMPORT_ARCHIVE = DATA_DIR / "import" / "archive"
IMPORT_ERROR = DATA_DIR / "import" / "error"


@dataclass(frozen=True)
class ImportPreview:
    row_count: int
    columns: list[str]
    warnings: list[str]
    sample: list[dict[str, str]]


@dataclass(frozen=True)
class ImportResult:
    success: bool
    created_doors: int
    updated_doors: int
    operations_written: int
    warnings: list[str]
    errors: list[str]


@dataclass(frozen=True)
class FolderFileResult:
    filename: str
    success: bool
    created_doors: int
    updated_doors: int
    operations_written: int
    warnings: list[str]
    errors: list[str]


@dataclass(frozen=True)
class FolderImportResult:
    success: bool
    processed_files: int
    imported_files: int
    failed_files: int
    created_doors: int
    updated_doors: int
    operations_written: int
    files: list[FolderFileResult]


def result_to_dict(result: ImportResult | FolderImportResult | FolderFileResult) -> dict[str, Any]:
    return asdict(result)


def parse_door_file(content: bytes, filename: str) -> ImportPreview:
    rows, columns = _read_rows(content, filename)
    return ImportPreview(
        row_count=len(rows),
        columns=columns,
        warnings=_build_warnings(columns),
        sample=rows[:10],
    )


def import_door_file(connection: sqlite3.Connection, content: bytes, filename: str) -> ImportResult:
    rows, columns = _read_rows(content, filename)
    warnings = _build_warnings(columns)
    created_doors = 0
    updated_doors = 0
    operations_written = 0

    for index, row in enumerate(rows, start=2):
        serial = row.get("Серія", "").strip()
        if not serial:
            warnings.append(f"Рядок {index}: пропущено, бо немає серії.")
            continue

        existed = _door_exists(connection, serial)
        door_id = _upsert_door_values(
            connection,
            {
                "serial": serial,
                "order_date": _parse_date(row.get("Дата заказа", "")),
                "planned_date": _parse_date(row.get("Планована дата виготовлення", "")),
                "counterparty": row.get("Контрагент", ""),
                "order_number": row.get("Номер замовлення", ""),
                "door_type": row.get("Тип", ""),
                "model": row.get("Модель", ""),
                "size": row.get("Розмір", ""),
                "leaf_count": _parse_int(row.get("Кількість створок", "")),
                "is_custom": int(_parse_bool(row.get("Нестандарт", ""))),
            },
        )
        connection.execute("DELETE FROM operations WHERE door_id = ?", (door_id,))
        created_doors += int(not existed)
        updated_doors += int(existed)

        for operation, line, sequence_index, done_column, hours_column in TSV_OPERATION_COLUMNS:
            is_done = _parse_bool(row.get(done_column, ""))
            hours = _parse_float(row.get(hours_column, ""))
            if operation == "МДФ" and not is_done and not hours:
                continue
            if is_done or hours is not None:
                _insert_operation(connection, door_id, operation, line, sequence_index, is_done, hours or 0.0)
                operations_written += 1

    return ImportResult(True, created_doors, updated_doors, operations_written, warnings, [])


def validate_import_payload(payload: Any) -> ImportResult:
    warnings: list[str] = []
    errors: list[str] = []

    if not isinstance(payload, dict):
        return ImportResult(False, 0, 0, 0, [], ["body: JSON має бути об'єктом"])

    if payload.get("format") != "factory_plan_doors":
        errors.append("format: очікується factory_plan_doors")
    if payload.get("version") != 1:
        errors.append("version: очікується 1")

    doors = payload.get("doors")
    if not isinstance(doors, list):
        errors.append("doors: має бути масивом")
        return ImportResult(False, 0, 0, 0, warnings, errors)

    seen_serials: set[str] = set()
    for index, door in enumerate(doors):
        path = f"doors[{index}]"
        if not isinstance(door, dict):
            errors.append(f"{path}: має бути об'єктом")
            continue
        missing = [field for field in REQUIRED_DOOR_FIELDS if field not in door]
        if missing:
            errors.append(f"{path}: відсутні обов'язкові поля: {', '.join(missing)}")
            continue

        serial = _clean_text(door.get("serial"))
        if not serial:
            errors.append(f"{path}.serial: обов'язкове поле порожнє")
        elif serial in seen_serials:
            errors.append(f"{path}.serial: повтор серії {serial}")
        else:
            seen_serials.add(serial)

        for field in ("order_date", "planned_date"):
            if not _is_iso_date(door.get(field)):
                errors.append(f"{path}.{field}: дата має бути у форматі YYYY-MM-DD")

        leaf_count = door.get("leaf_count")
        if not isinstance(leaf_count, int) or isinstance(leaf_count, bool) or leaf_count <= 0:
            errors.append(f"{path}.leaf_count: має бути цілим числом більше 0")

        for field in ("counterparty", "order_number", "door_type", "model", "size"):
            if _clean_text(door.get(field)) == "":
                warnings.append(f"{path}.{field}: текстове поле порожнє")

        if "is_custom" in door and not isinstance(door["is_custom"], bool):
            errors.append(f"{path}.is_custom: має бути boolean")

        operations = door.get("operations")
        if not isinstance(operations, dict):
            errors.append(f"{path}.operations: має бути об'єктом")
            continue

        for operation_key in operations:
            if operation_key not in JSON_OPERATION_COLUMNS:
                errors.append(f"{path}.operations.{operation_key}: невідомий ключ операції")
                continue
            operation = operations[operation_key]
            if not isinstance(operation, dict):
                errors.append(f"{path}.operations.{operation_key}: має бути об'єктом")
                continue
            done = operation.get("done")
            hours = operation.get("hours")
            if not isinstance(done, bool):
                errors.append(f"{path}.operations.{operation_key}.done: має бути boolean")
            hours_is_number = isinstance(hours, (int, float)) and not isinstance(hours, bool)
            if hours is not None and not hours_is_number:
                errors.append(f"{path}.operations.{operation_key}.hours: має бути числом або null")
            if done is True and hours is None:
                warnings.append(f"{path}.operations.{operation_key}: виконана операція має hours = null")
            if done is False and operation_key != "mdf" and (hours is None or (hours_is_number and hours <= 0)):
                warnings.append(f"{path}.operations.{operation_key}: невиконана операція має порожні або нульові години")

    return ImportResult(not errors, 0, 0, 0, warnings, errors)


def import_payload(payload: dict[str, Any], connection: sqlite3.Connection | None = None) -> ImportResult:
    validation = validate_import_payload(payload)
    if validation.errors:
        return validation

    owns_connection = connection is None
    connection = connection or get_connection()
    created_doors = 0
    updated_doors = 0
    operations_written = 0
    try:
        connection.execute("BEGIN")
        for door in payload["doors"]:
            serial = _clean_text(door["serial"])
            existed = _door_exists(connection, serial)
            door_id = _upsert_door_values(
                connection,
                {
                    "serial": serial,
                    "order_date": door["order_date"],
                    "planned_date": door["planned_date"],
                    "counterparty": _clean_text(door["counterparty"]),
                    "order_number": _clean_text(door["order_number"]),
                    "door_type": _clean_text(door["door_type"]),
                    "model": _clean_text(door["model"]),
                    "size": _clean_text(door["size"]),
                    "leaf_count": door["leaf_count"],
                    "is_custom": int(bool(door.get("is_custom", False))),
                },
            )
            connection.execute("DELETE FROM operations WHERE door_id = ?", (door_id,))
            created_doors += int(not existed)
            updated_doors += int(existed)
            operations_written += _write_json_operations(connection, door_id, door["operations"])
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        if owns_connection:
            connection.close()

    return ImportResult(True, created_doors, updated_doors, operations_written, validation.warnings, [])


def import_json_file(path: Path) -> ImportResult:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        return ImportResult(False, 0, 0, 0, [], [f"{path.name}: JSON parse error: {exc.msg}"])
    return import_payload(payload)


def import_from_folder() -> FolderImportResult:
    _ensure_import_dirs()
    files: list[FolderFileResult] = []
    for path in sorted(IMPORT_INBOX.glob("*.json")):
        result = import_json_file(path)
        files.append(FolderFileResult(path.name, **asdict(result)))
        _move_import_file(path, IMPORT_ARCHIVE if result.success else IMPORT_ERROR)

    return FolderImportResult(
        success=all(file.success for file in files),
        processed_files=len(files),
        imported_files=sum(1 for file in files if file.success),
        failed_files=sum(1 for file in files if not file.success),
        created_doors=sum(file.created_doors for file in files),
        updated_doors=sum(file.updated_doors for file in files),
        operations_written=sum(file.operations_written for file in files),
        files=files,
    )


def _write_json_operations(connection: sqlite3.Connection, door_id: int, operations: dict[str, Any]) -> int:
    operations_written = 0
    for key, (operation, line, sequence_index) in JSON_OPERATION_COLUMNS.items():
        if key not in operations:
            continue
        source = operations[key]
        is_done = bool(source["done"])
        hours = source["hours"]
        if key == "mdf" and not is_done and not hours:
            continue
        if is_done or hours:
            _insert_operation(connection, door_id, operation, line, sequence_index, is_done, float(hours or 0.0))
            operations_written += 1
    return operations_written


def _insert_operation(
    connection: sqlite3.Connection,
    door_id: int,
    operation: str,
    line: str,
    sequence_index: int,
    is_done: bool,
    hours: float,
) -> None:
    connection.execute(
        """
        INSERT INTO operations
            (door_id, operation, line, sequence_index, is_done, hours, is_required)
        VALUES (?, ?, ?, ?, ?, ?, 1)
        """,
        (door_id, operation, line, sequence_index, int(is_done), hours),
    )


def _read_rows(content: bytes, filename: str) -> tuple[list[dict[str, str]], list[str]]:
    text = content.decode("utf-8-sig")
    delimiter = _detect_delimiter(text, filename)
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    columns = list(reader.fieldnames or [])
    return [_clean_row(row) for row in reader], columns


def _detect_delimiter(text: str, filename: str) -> str:
    first_line = text.splitlines()[0] if text.splitlines() else ""
    if filename.lower().endswith((".tsv", ".txt")) or "\t" in first_line:
        return "\t"
    return ","


def _door_exists(connection: sqlite3.Connection, serial: str) -> bool:
    row = connection.execute("SELECT 1 FROM doors WHERE serial = ?", (serial,)).fetchone()
    return row is not None


def _upsert_door_values(connection: sqlite3.Connection, values: dict[str, Any]) -> int:
    connection.execute(
        """
        INSERT INTO doors (
            serial, order_date, planned_date, counterparty, order_number,
            door_type, model, size, leaf_count, is_custom
        )
        VALUES (
            :serial, :order_date, :planned_date, :counterparty, :order_number,
            :door_type, :model, :size, :leaf_count, :is_custom
        )
        ON CONFLICT(serial) DO UPDATE SET
            order_date = excluded.order_date,
            planned_date = excluded.planned_date,
            counterparty = excluded.counterparty,
            order_number = excluded.order_number,
            door_type = excluded.door_type,
            model = excluded.model,
            size = excluded.size,
            leaf_count = excluded.leaf_count,
            is_custom = excluded.is_custom
        """,
        values,
    )
    row_id = connection.execute("SELECT id FROM doors WHERE serial = ?", (values["serial"],)).fetchone()
    return int(row_id["id"])


def _build_warnings(columns: list[str]) -> list[str]:
    warnings = []
    missing = [column for column in EXPECTED_COLUMNS if column not in columns]
    if missing:
        warnings.append("Відсутні обов'язкові колонки: " + ", ".join(missing))

    missing_optional = [column for column in OPTIONAL_COLUMNS if column not in columns]
    if missing_optional:
        warnings.append("Відсутні додаткові колонки: " + ", ".join(missing_optional))

    return warnings


def _clean_row(row: dict[str, str]) -> dict[str, str]:
    return {key: (value or "").strip() for key, value in row.items()}


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _is_iso_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"так", "yes", "true", "1", "y"}


def _parse_date(value: str) -> str | None:
    value = value.strip()
    if not value:
        return None
    for date_format in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, date_format).date().isoformat()
        except ValueError:
            continue
    return None


def _parse_float(value: str) -> float | None:
    value = value.strip().replace(",", ".")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_int(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    try:
        return int(float(value.replace(",", ".")))
    except ValueError:
        return None


def _ensure_import_dirs() -> None:
    for path in (IMPORT_INBOX, IMPORT_ARCHIVE, IMPORT_ERROR):
        path.mkdir(parents=True, exist_ok=True)


def _move_import_file(path: Path, target_dir: Path) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    target = target_dir / f"{path.stem}_{timestamp}{path.suffix}"
    shutil.move(str(path), str(target))
