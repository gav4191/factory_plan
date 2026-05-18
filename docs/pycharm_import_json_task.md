# Завдання для PyCharm: реалізація JSON-імпорту

## Контекст

Потрібно реалізувати імпорт дверей у Factory Plan з JSON, який формує 1С.

Основний контракт файла описаний у:

- `docs/import_json_contract.md`
- `docs/import_sample.json`

TSV/CSV більше не є основним форматом імпорту. Старий preview можна тимчасово залишити для тестів, але нову логіку робити навколо JSON.

## Канали імпорту

Потрібно підтримати два способи імпорту.

### 1. Прямий API з 1С

Додати endpoint:

```text
POST /api/import/json
```

1С передає JSON у тілі запиту з `Content-Type: application/json`.

Endpoint має:

1. Прийняти JSON-об'єкт.
2. Перевірити структуру згідно з `docs/import_json_contract.md`.
3. Якщо є критичні помилки - не змінювати базу і повернути список помилок.
4. Якщо критичних помилок немає - створити або оновити двері та операції.
5. Повернути короткий результат імпорту.

### 2. Імпорт з каталогу

Додати endpoint:

```text
POST /api/import/from-folder
```

Він читає всі JSON-файли з каталогу:

```text
data/import/inbox
```

Після обробки:

- успішно імпортовані файли переносити в `data/import/archive`
- файли з помилками переносити в `data/import/error`

Автоматичний тригер на появу файла у першій версії не робити. Імпорт з каталогу запускається вручну кнопкою в інтерфейсі або API-викликом.

## Каталоги

Потрібно створювати каталоги автоматично, якщо їх немає:

```text
data/import/inbox
data/import/archive
data/import/error
```

При перенесенні файла бажано додавати timestamp до імені, щоб не перезаписати старий файл.

Приклад:

```text
doors_2026-05-18_153000.json
```

## Модель імпорту

Головний ключ двері:

```text
serial
```

Якщо двері з таким `serial` вже існує:

- оновити поля в `doors`
- видалити старі операції цієї двері з `operations`
- створити операції заново з JSON

Якщо двері не існує:

- створити запис у `doors`
- створити операції в `operations`

Імпорт одного JSON-файла має бути атомарним: або весь файл імпортується, або база не змінюється.

## Відповідність операцій

JSON-ключі операцій:

```text
blank
welding
painting
mdf
assembly
packing
```

Зберігати в таблиці `operations` так:

| JSON key | operation | line | sequence_index |
|---|---|---|---|
| blank | Заготовка | A | 1 |
| welding | Зварка | A | 2 |
| painting | Фарбування | A | 3 |
| mdf | МДФ | B | 1 |
| assembly | Зборка | C | 1 |
| packing | Упаковка | C | 2 |

Правила:

- `done: true` -> `is_done = 1`
- `done: false` -> `is_done = 0`
- `hours` записувати як `REAL`
- якщо `mdf.hours` дорівнює `null` або `0`, операцію МДФ не створювати
- якщо інша невиконана операція має `hours = null` або `0`, додати попередження

## Валідація

Критичні помилки, які блокують імпорт:

- тіло запиту не є JSON-об'єктом
- `format` не дорівнює `factory_plan_doors`
- `version` не дорівнює `1`
- `doors` відсутній або не є масивом
- у файлі є повтори `serial`
- у двері немає обов'язкових полів
- `serial` порожній
- дата не у форматі `YYYY-MM-DD`
- `leaf_count` не є цілим числом більше `0`
- `operations` відсутній або не є об'єктом
- `done` не є boolean
- `hours` не є числом або `null`
- у `operations` є невідомий ключ

Попередження, які не блокують імпорт:

- необов'язкові текстові поля порожні
- виконана операція має `hours = null`
- невиконана немДФ-операція має `hours = null` або `0`

## Відповідь API

Для `POST /api/import/json` повернути:

```json
{
  "success": true,
  "created_doors": 10,
  "updated_doors": 5,
  "operations_written": 72,
  "warnings": [],
  "errors": []
}
```

Якщо є критичні помилки:

```json
{
  "success": false,
  "created_doors": 0,
  "updated_doors": 0,
  "operations_written": 0,
  "warnings": [],
  "errors": [
    "doors[3].serial: обов'язкове поле порожнє"
  ]
}
```

Для `POST /api/import/from-folder` повернути агрегований результат:

```json
{
  "success": true,
  "processed_files": 2,
  "imported_files": 1,
  "failed_files": 1,
  "created_doors": 10,
  "updated_doors": 5,
  "operations_written": 72,
  "files": [
    {
      "filename": "doors_1.json",
      "success": true,
      "created_doors": 10,
      "updated_doors": 5,
      "operations_written": 72,
      "warnings": [],
      "errors": []
    }
  ]
}
```

## Рекомендована структура коду

Доробити або розділити `factory_plan/importer.py`.

Можливі функції:

```python
def validate_import_payload(payload: dict) -> ImportValidationResult:
    ...

def import_payload(payload: dict) -> ImportResult:
    ...

def import_json_file(path: Path) -> ImportResult:
    ...

def import_from_folder() -> FolderImportResult:
    ...
```

Додати dataclass-и для результатів, щоб API не складав словники вручну в багатьох місцях.

## Frontend

На сторінці `/import` додати:

- завантаження JSON-файла через браузер
- кнопку `Імпортувати з каталогу`
- блок результату імпорту
- показ помилок і попереджень

Для завантаження файла через браузер можна зробити endpoint:

```text
POST /api/import/file
```

Він приймає multipart-файл, читає JSON і використовує ту саму функцію `import_payload()`.

## Тести вручну

Перевірити:

1. `docs/import_sample.json` імпортується без критичних помилок.
2. Повторний імпорт цього самого файла не дублює двері, а оновлює їх.
3. Якщо змінити `model` у JSON і повторити імпорт, значення в `doors` оновлюється.
4. Якщо у файлі два однакових `serial`, база не змінюється.
5. Якщо `mdf.hours = null`, операція МДФ не створюється.
6. Якщо файл покладено в `data/import/inbox`, `POST /api/import/from-folder` імпортує його і переносить в `archive`.
7. Якщо файл невалідний, він переноситься в `error`, а API повертає помилки.

## Критерії готовності

Завдання готове, якщо:

- працює `POST /api/import/json`
- працює `POST /api/import/file`
- працює `POST /api/import/from-folder`
- імпорт атомарний для одного файла
- повторний імпорт оновлює двері, а не дублює
- операції створюються за правилами маршруту
- МДФ без годин не планується
- результат імпорту містить кількість створених/оновлених дверей, кількість операцій, warnings і errors
- сторінка `/import` дозволяє запустити імпорт вручну
