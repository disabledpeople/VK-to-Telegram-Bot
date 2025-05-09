# VK to Telegram Bot. we are planning to add the cobalt api (video forwarding)

Этот бот автоматически переносит новые посты из сообщества VK в Telegram-чат.

## 🚀 Функции
✅ Переносит **текст и фото** из VK в Telegram.  
✅ Пропускает **закреплённые посты**.  
✅ Проверяет новые посты каждые **10-15 минут**.  
✅ **Запоминает** последний отправленный пост и не дублирует его.  
✅ Ведёт **лог ошибок и отправленных постов**.  

---
## 🔧 Установка и настройка

### 1️⃣ Установите зависимости
```sh
pip install vk_api pyTelegramBotAPI
```

### 2️⃣ Получите API-токены

#### 🔹 VK API Token
1. Перейдите в [VK API](https://vk.com/dev) и создайте токен доступа.
2. Выдайте права `wall` для работы с постами.
3. Скопируйте полученный токен.

#### 🔹 Telegram Bot Token
1. Создайте бота в [BotFather](https://t.me/BotFather) и получите токен.
2. Добавьте бота в нужный чат и выдайте права администратора.

#### 🔹 Узнайте ID Telegram-чата
1. Напишите любому боту `@userinfobot` в Telegram и получите свой ID.

---
## ⚙️ Конфигурация
Откройте `main.py` и замените переменные своими значениями:
```python
VK_TOKEN = "your_vk_token"  # Токен VK
VK_GROUP_ID = "your_vk_group_id"  # ID группы VK (без "-")
TG_BOT_TOKEN = "your_telegram_bot_token"  # Токен Telegram-бота
TG_CHAT_ID = "your_telegram_chat_id"  # ID чата Telegram
```

---
## ▶️ Запуск бота
```sh
python main.py
```

Бот начнёт работать и проверять новые посты каждые **10 минут**.

---
## 🛠 Возможные ошибки
| Ошибка | Решение |
|--------|---------|
| `Bad Request: message caption is too long` | Текст слишком длинный (>1024 символов), он будет отправлен отдельным сообщением. |
| `Error: Too Many Requests` | VK или Telegram ограничили API, попробуйте позже. |
| `VK API error: access denied` | Убедитесь, что токен VK правильный и у него есть доступ к стене группы. |
| `Telegram API error 400` | Проверьте корректность `TG_BOT_TOKEN` и `TG_CHAT_ID`. |

---

