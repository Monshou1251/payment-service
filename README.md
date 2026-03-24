# Async Payment Processing Service

Микросервис асинхронной обработки платежей на FastAPI + PostgreSQL + RabbitMQ.

## Архитектура

```
POST /api/v1/payments
        │
        ▼
   [API Service]
   Создаёт Payment (pending) + OutboxEvent
   в одной транзакции (Outbox Pattern)
        │
        ▼
  [Outbox Worker]
  Читает OutboxEvent WHERE published_at IS NULL
  Публикует в RabbitMQ → payments.exchange → payments.new
        │
        ▼
  [Consumer]
  Получает сообщение из payments.new
  Эмулирует обработку (2-5с, 90% успех / 10% ошибка)
  Обновляет статус платежа в БД
  Отправляет webhook (3 попытки, exponential backoff)
        │
   on failure (3x)
        ▼
  [DLQ] payments.dead
```

### Гарантии доставки

- **Outbox Pattern** — событие сохраняется в одной транзакции с платежом, не теряется при падении сервиса
- **Idempotency Key** — повторный запрос с тем же ключом возвращает существующий платёж
- **DLQ** — сообщения, не обработанные после 3 попыток, попадают в `payments.dead`
- **Webhook retry** — 3 попытки с задержками 1s → 2s → 4s

## Стек

| Компонент | Технология |
|---|---|
| API | FastAPI + Pydantic v2 |
| ORM | SQLAlchemy 2.0 (async) |
| БД | PostgreSQL 16 |
| Брокер | RabbitMQ 3.13 |
| Миграции | Alembic |
| HTTP-клиент | httpx |

## Запуск

### Требования

- Docker + Docker Compose

### 1. Клонировать репозиторий

```bash
git clone https://github.com/Monshou1251/payment-service.git
cd payment-service
```

### 2. Настроить переменные окружения

```bash
cp .env.example .env
```

Значения по умолчанию работают из коробки — ничего менять не нужно.

### 3. Запустить

```bash
docker compose up --build
```

Сервисы поднимутся в правильном порядке:
1. `postgres` и `rabbitmq` (с healthcheck)
2. `migrator` — применяет миграции и завершается
3. `api`, `consumer`, `outbox` — стартуют после успешных миграций

### 4. Проверить

- API: http://localhost:8000
- Swagger UI: http://localhost:8000/docs
- RabbitMQ Management: http://localhost:15672 (guest / guest)

## API

Все эндпоинты требуют заголовок `X-API-Key: secret-api-key`.

### POST /api/v1/payments — Создать платёж

**Заголовки:**
```
X-API-Key: secret-api-key
Idempotency-Key: <уникальный ключ>
Content-Type: application/json
```

**Тело запроса:**
```json
{
  "amount": "100.00",
  "currency": "RUB",
  "description": "Оплата заказа #123",
  "metadata": {"order_id": "123"},
  "webhook_url": "https://example.com/webhook"
}
```

**Ответ 202 Accepted:**
```json
{
  "payment_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "status": "pending",
  "created_at": "2026-03-24T12:00:00Z"
}
```

### GET /api/v1/payments/{payment_id} — Получить платёж

**Заголовки:**
```
X-API-Key: secret-api-key
```

**Ответ 200 OK:**
```json
{
  "id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "amount": "100.00",
  "currency": "RUB",
  "description": "Оплата заказа #123",
  "metadata": {"order_id": "123"},
  "status": "succeeded",
  "webhook_url": "https://example.com/webhook",
  "created_at": "2026-03-24T12:00:00Z",
  "processed_at": "2026-03-24T12:00:05Z"
}
```

### Примеры через curl

```bash
# Создать платёж
curl -X POST http://localhost:8000/api/v1/payments \
  -H "X-API-Key: secret-api-key" \
  -H "Idempotency-Key: order-123-attempt-1" \
  -H "Content-Type: application/json" \
  -d '{
    "amount": "100.00",
    "currency": "RUB",
    "description": "Оплата заказа #123",
    "metadata": {"order_id": "123"},
    "webhook_url": "https://webhook.site/your-id"
  }'

# Получить статус платежа
curl http://localhost:8000/api/v1/payments/f47ac10b-58cc-4372-a567-0e02b2c3d479 \
  -H "X-API-Key: secret-api-key"

# Повторный запрос с тем же Idempotency-Key вернёт тот же платёж
curl -X POST http://localhost:8000/api/v1/payments \
  -H "X-API-Key: secret-api-key" \
  -H "Idempotency-Key: order-123-attempt-1" \
  -H "Content-Type: application/json" \
  -d '{
    "amount": "100.00",
    "currency": "RUB",
    "description": "Оплата заказа #123",
    "metadata": {"order_id": "123"},
    "webhook_url": "https://webhook.site/your-id"
  }'
```

> Для тестирования webhook можно использовать https://webhook.site

## Остановка

```bash
docker compose down

# Удалить также данные БД
docker compose down -v
```
