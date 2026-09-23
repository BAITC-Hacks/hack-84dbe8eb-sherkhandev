# EKT AI — часть участника 1

Реализованы общие контракты, настройки, in-memory сессии, единая авторизация, API сессий/health/chat и настоящий LLM-агент на OpenAI Responses API. Агент использует только восемь разрешённых read/prepare-инструментов; `confirm_action` никогда не передаётся модели. Подтверждение выполняется сервером по точной фразе и `confirmation_action_id`.

## Запуск

Запускать из `ekt-ai/backend` одним worker:

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
export OPENAI_API_KEY='ключ вводит человек в окружение'
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

Затем открыть <http://127.0.0.1:8000/>. `.env.example` содержит только имена и безопасные примеры: приложение намеренно не загружает `.env` автоматически. Ключ и остальные параметры должны быть переданы окружением процесса.

## Режимы и интеграция

По договору команды по умолчанию используется `CATALOG_MODE=fixture`, но канонические fixture-данные, `CatalogService`, `ConditionsService`, `CartService`, web-интерфейс и их роутеры принадлежат участникам 2/3 и в этой рабочей копии ещё не подключены. `main.py` не подменяет их fake-сервисами: до импорта соседних модулей доступные endpoints работают, а chat честно возвращает ошибку зависимости/LLM.

Настоящий LLM-путь требует установленного `openai` и `OPENAI_API_KEY`. Если ключ отсутствует, сервер запускается, но `/api/v1/chat` возвращает `LLM_UNAVAILABLE`. Fixture-режим относится только к данным магазина и не превращает ответы в заготовленные реплики.

## Контрактные примеры

Успешный `ChatResponse` после поиска содержит реальные `products` из `CatalogPort`, а не цифры из текста модели:

```json
{
  "message": "Нашёл подходящий товар.",
  "products": [],
  "pending_action": null,
  "cart": null,
  "warnings": []
}
```

`PendingAction` — предложение, которое ещё ничего не добавляет:

```json
{
  "action_id": "action-1",
  "product_id": "demo-001",
  "warehouse_id": "demo-warehouse",
  "product_name": "Учебный автомат A",
  "quantity_to_add": 2,
  "unit_price": "1200.00",
  "added_amount": "2400.00",
  "currency": "KZT",
  "unit": "pcs",
  "quantity_step": "1",
  "stock_quantity": "5",
  "checked_at": "2026-09-23T10:00:00Z",
  "expires_at": "2026-09-23T10:05:00Z",
  "status": "pending",
  "source_kind": "synthetic"
}
```

Успешный `ConfirmResult` возвращает `already_applied` и актуальную `cart` с `cart_url`; ссылка добавляется backend после подтверждения и не отправляется модели. Ошибка имеет единственный формат:

```json
{"error":{"code":"LLM_UNAVAILABLE","message":"LLM is not configured or unavailable","retryable":true}}
```

## Проверки

```bash
python -m pytest tests/agent tests/api
```

Фактический результат в текущей копии: `13 passed`. В выводе остаются предупреждения совместимости `asyncio.iscoroutinefunction` от установленного Python 3.14/pytest-asyncio 0.24; падений нет.

Настоящая модель OpenAI и live-источник EKT в этой среде не проверялись: ключ и соседние сервисы не подключены. Браузерный smoke и полный набор команды требуют импорта файлов участников 2/3. Импорт Excel/Word/PDF/JPEG, настоящий заказ, оплата, резерв EKT и изменение настоящей корзины не входят в этот прототип.
