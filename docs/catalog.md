# Каталог, аналоги и условия

Участник 2 передаёт один `CatalogService` для `fixture` и `live` режимов и
`ConditionsService` для трёх тем условий. Сервисы возвращают общие
`ToolResult`/DTO из `backend/app/contracts.py`; собственных копий общих моделей
нет.

## Создано

- `backend/app/catalog/` — нормализация, SQLite-хранилище, fixture-провайдер,
  консервативный live-провайдер и `CatalogService`.
- `backend/app/conditions/` — изолированное чтение условий по режиму.
- `backend/app/api/catalog.py` — `GET /api/v1/warehouses` с общей bearer-
  авторизацией.
- `backend/data/catalog/fixture.json` — канонические `DEMO-001`…`DEMO-003`.
- `backend/data/conditions/fixture/` и `backend/data/conditions/live/` —
  отдельные демонстрационные и неподтверждённые live-записи.
- `backend/data/certificates/DEMO-CERT-001.html` — явно учебный документ,
  не сертификат EKT.
- `backend/scripts/import_catalog.py` — ограниченный импорт максимум 20
  указанных product id; интерактивного режима нет.

## Примеры вызова

```python
from app.catalog import CatalogService
from app.conditions import ConditionsService

catalog = CatalogService(settings.catalog_db_path, settings)
await catalog.initialize()
warehouses = await catalog.list_warehouses()
products = await catalog.search_products(
    "DEMO", SearchFilters(category="demo_breaker"), limit=5
)
snapshot = await catalog.get_snapshot("demo-002", "demo-warehouse")
analogs = await catalog.find_analogs("demo-002", "demo-warehouse")
certificate = await catalog.get_certificate("demo-001")
await catalog.close()

conditions = ConditionsService(settings.conditions_path, settings.catalog_mode)
await conditions.initialize()
payment = await conditions.get_conditions("payment")
```

Скрипт live-импорта запускается из `backend` только при явном режиме:

```text
CATALOG_MODE=live python -m scripts.import_catalog --product-id 123
```

Он вызывает только `https://ekt.kz/api/products/detail?id=...`, сохраняет
исходный JSON и нормализованные записи в live-базу. В runtime-коде fixture не
делает сетевых запросов. `initialize()` live создаёт HTTP-клиент, но не
импортирует товары автоматически.

## Правила аналогов

Поддержанная категория — `demo_breaker`. Обязательные параметры:
`poles`, `rated_current_a`, `trip_curve`, `breaking_capacity_ka`. Кандидат
должен иметь ту же категорию, все обязательные параметры без конфликтов,
подходящий (`eligible=true`) выбранный склад и известный положительный остаток.
Исходный товар, нулевой/неизвестный остаток, конфликтные и неполные записи
исключаются. `DEMO-003` является допустимым учебным аналогом `DEMO-002`;
это не утверждение о реальной взаимозаменяемости.

Ответ содержит `matched_specs`, различия в цене/единице и ограничения,
извлечённые из данных и этих правил. При отсутствии кандидатов возвращается
успешный пустой `AnalogResult` с предупреждением об ограничении выборки.

## Live-доказательства и ограничения

Проверяемый live-источник в адаптере — detail endpoint
`https://ekt.kz/api/products/detail?id=ID`. Поддерживаются только поля,
которые реально присутствуют в одном detail-ответе: идентификатор, артикул,
название, цена, единица, кратность, характеристики и складские остатки.
Неизвестные числа остаются `null`; ноль сохраняется как ноль; технические
склады без `eligible=true` не считаются доступными. Старый снимок не выдаётся
при ошибке свежего live-запроса: результатом является `SOURCE_UNAVAILABLE`.

Фактический live smoke-test EKT не подтверждён: заявленные URL
`/api/products?page=1` и `/api/products/detail?id=1` оказались недоступны
через доступный внешний web-инструмент. Python runtime для pytest в среде
сдачи также не предоставлен. MockTransport-тесты не являются доказательством
доступности EKT.

## Проверки и интеграция

Команда проверки из договора:

```text
cd ekt-ai/backend
python -m pytest tests/catalog tests/conditions
```

Участнику 1 нужно подключить `app.api.catalog.router` (полный путь уже
задан), lifecycle `CatalogService`/`ConditionsService` и раздачу
`backend/data/certificates` на `/demo-certificates`. Участнику 3 доступны
канонические товары, склад `demo-warehouse`, нулевой остаток `DEMO-002` и
положительный остаток `DEMO-003`; перед добавлением использовать
`get_snapshot(..., refresh=True)`.
