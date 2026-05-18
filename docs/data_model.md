# Factory Plan: модель даних

## Вхідний файл

Файл має табличний формат TSV або CSV.

Поточний приклад: `для плану виконання.txt`.

Очікувані колонки:

- Серія
- Дата заказа
- Планована дата виготовлення
- Заготовка готово
- Час заготовка
- Зварка готово
- Час зварка
- Фарбування готово
- Час фарба
- МДФГотово
- Час МДФ
- Зборка готово
- Час зборка
- Упаковка готово
- Час упаковка
- Тип
- Модель
- Розмір
- Кількість створок
- Контрагент
- Номер замовлення

Колонки `Контрагент` і `Номер замовлення` мають бути у майбутньому вхідному файлі. Якщо їх немає, перша версія імпорту може залишати ці поля порожніми.

## SQLite таблиці

### `doors`

- `id`
- `serial`
- `order_date`
- `planned_date`
- `counterparty`
- `order_number`
- `door_type`
- `model`
- `size`
- `leaf_count`
- `is_custom`

### `operations`

- `id`
- `door_id`
- `operation`
- `line`
- `sequence_index`
- `is_done`
- `hours`
- `is_required`

### `work_calendar`

- `date`
- `is_working_day`
- `hours`

### `priority_rules`

- `id`
- `rule_type`
- `rule_value`
- `priority`
- `comment`
- `created_at`

`rule_type` може мати значення:

- `serial`
- `order_number`
- `counterparty`

### `plan_items`

- `id`
- `plan_date`
- `operation`
- `line`
- `door_id`
- `hours`
- `queue_priority`

### `plan_daily_load`

- `id`
- `plan_date`
- `operation`
- `capacity_hours`
- `planned_hours`
- `overflow_hours`
- `door_count`

