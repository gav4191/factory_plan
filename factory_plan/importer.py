from dataclasses import dataclass
import csv
import io


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


@dataclass(frozen=True)
class ImportPreview:
    row_count: int
    columns: list[str]
    warnings: list[str]
    sample: list[dict[str, str]]


def parse_door_file(content: bytes, filename: str) -> ImportPreview:
    text = content.decode("utf-8-sig")
    delimiter = _detect_delimiter(text, filename)
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    columns = list(reader.fieldnames or [])
    rows = list(reader)
    warnings = _build_warnings(columns)

    return ImportPreview(
        row_count=len(rows),
        columns=columns,
        warnings=warnings,
        sample=[_clean_row(row) for row in rows[:10]],
    )


def _detect_delimiter(text: str, filename: str) -> str:
    if filename.lower().endswith(".tsv") or "\t" in text.splitlines()[0]:
        return "\t"
    return ","


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

