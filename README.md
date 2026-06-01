# StartRus Bot 📚 v2.0

Telegram бот для продажи книги StartRus — учебник русского языка (A2) для узбекоязычной аудитории.

## Возможности

- 🌐 Двуязычный интерфейс (русский / узбекский)
- 📖 Информация о книге, превью, FAQ
- 💳 Процесс заказа с отслеживанием оплаты
- 📸 Приём скриншотов чеков
- 📚 Автоотправка PDF после подтверждения
- 🎟 Система промокодов / скидок
- 📊 Аналитика пользователей и заказов
- 🔔 Уведомления админу
- 💾 SQLite для хранения данных

## Deploy to Railway

1. Push this repo to GitHub
2. Connect to Railway
3. Add environment variables (see below)

## Переменные окружения

| Переменная | Обязательная | Описание |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | Токен бота от @BotFather |
| `ADMIN_USER_ID` | ⚠️ | Telegram ID админа (для уведомлений) |
| `BOOK_PRICE` | — | Цена книги в сўмах (по умолч. 59000) |
| `PAYMENT_CARD` | — | Номер карты для оплаты |
| `PAYMENT_METHOD` | — | Способ оплаты (Click/Payme/Перевод) |
| `BOOK_PDF_PATH` | — | Путь к PDF файлу книги |
| `SELLER_CONTACT` | — | Ссылка на продавца (по умолч. https://t.me/callmeanv) |

## Админ-команды

```
/stats        — Статистика бота
/confirm <id> — Подтвердить заказ
/reject <id>  — Отклонить заказ
/addpromo CODE DISCOUNT% MAX_USES — Создать промокод
/listpromos   — Список промокодов
```

## Как узнать свой Telegram ID

Отправьте `/start` боту [@userinfobot](https://t.me/userinfobot)
