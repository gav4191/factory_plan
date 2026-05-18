# Factory Plan

Веб-додаток для поденного планування виробництва дверей по цехах.

## Стек

- Python
- FastAPI
- HTML/CSS/JavaScript
- SQLite

## Запуск

Після встановлення залежностей:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Локально:

```text
http://127.0.0.1:8000
```

У локальній мережі:

```text
http://<IP-адреса-сервера>:8000
```

## Документація проєкту

- [Прийняті рішення](docs/decisions.md)
- [Інтерфейс](docs/interface.md)
- [Модель даних](docs/data_model.md)
- [Алгоритм планування](docs/scheduling.md)

