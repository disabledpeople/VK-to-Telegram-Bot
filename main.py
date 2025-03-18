import vk_api
import telebot
import time
import json
import os
import re

# 🔧 Настройки
VK_TOKEN = "your_vk_token"  # Токен VK
VK_GROUP_ID = "your_vk_group_id"  # ID группы без "-"
TG_BOT_TOKEN = "your_telegram_bot_token"  # Токен бота Telegram
TG_CHAT_ID = "your_telegram_chat_id"  # ID чата Telegram

LOG_FILE = "log.txt"  # Файл логов
LAST_POST_FILE = "last_post.json"  # Файл хранения ID последнего поста

# Интервал проверки (10 минут)
CHECK_INTERVAL = 10 * 60  

# Словарь ссылок для замены
VK_LINKS = {
    "club30602036": "https://vk.com/igm"
}

# Инициализация API
vk_session = vk_api.VkApi(token=VK_TOKEN)
vk = vk_session.get_api()
bot = telebot.TeleBot(TG_BOT_TOKEN)

def log_message(message):
    """Записывает сообщение в лог-файл."""
    with open(LOG_FILE, "a", encoding="utf-8") as log_file:
        log_file.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")
    print(message)

def load_last_post_id():
    """Загружает ID последнего отправленного поста."""
    if os.path.exists(LAST_POST_FILE):
        with open(LAST_POST_FILE, "r") as file:
            try:
                return json.load(file).get("last_post_id")
            except json.JSONDecodeError:
                return None
    return None

def save_last_post_id(post_id):
    """Сохраняет ID последнего отправленного поста."""
    with open(LAST_POST_FILE, "w") as file:
        json.dump({"last_post_id": post_id}, file)

def format_vk_text(text):
    """Заменяет [clubID|Название] на HTML-гиперссылку."""
    pattern = r"\[club(\d+)\|(.*?)\]"
    
    def replace_match(match):
        club_id, name = match.groups()
        url = VK_LINKS.get(f"club{club_id}", f"https://vk.com/club{club_id}")
        return f'<a href="{url}">{name}</a>'

    formatted_text = re.sub(pattern, replace_match, text)

    return formatted_text


def get_latest_post():
    """Получает последний пост из VK, пропуская закрепленные."""
    try:
        posts = vk.wall.get(owner_id=-int(VK_GROUP_ID), count=5)["items"]
        for post in posts:
            if post.get("is_pinned"):  # Пропускаем закрепленный пост
                continue

            post_id = post["id"]
            text = post.get("text", "")
            text = format_vk_text(text)  # Форматируем ссылки VK

            # Собираем фото
            photos = []
            attachments = post.get("attachments", [])
            for att in attachments:
                if att["type"] == "photo":
                    photos.append(att["photo"]["sizes"][-1]["url"])

            return post_id, text, photos
    except Exception as e:
        log_message(f"Ошибка получения поста: {e}")
    return None, None, None

def send_to_telegram():
    """Отправляет новый пост в Telegram."""
    last_post_id = load_last_post_id()
    post_id, text, photos = get_latest_post()

    if not post_id or post_id == last_post_id:
        log_message("Новых постов нет.")
        return

    try:
        # 1️⃣ Пробуем отправить текст + фото в одном сообщении
        if text and photos:
            media_group = [telebot.types.InputMediaPhoto(photo, caption=text if i == 0 else "") for i, photo in enumerate(photos)]
            bot.send_media_group(TG_CHAT_ID, media_group)
            log_message("✅ Текст и фото отправлены вместе")
        
        else:
            raise ValueError("Текст или фото отсутствуют")  # Принудительный переход к раздельной отправке

    except Exception as e:
        log_message(f"⚠️ Ошибка при отправке текста + фото вместе: {e}")

        # 2️⃣ Если не получилось, отправляем текст отдельно
        try:
            if text:
                bot.send_message(TG_CHAT_ID, text, parse_mode="Markdown")
                log_message("✅ Текст отправлен отдельно")

            # 3️⃣ Затем отправляем фото отдельно
            if photos:
                media_group = [telebot.types.InputMediaPhoto(photo) for photo in photos]
                bot.send_media_group(TG_CHAT_ID, media_group)
                log_message("✅ Фото отправлены отдельно")

        except Exception as e:
            log_message(f"❌ Ошибка при раздельной отправке: {e}")

    save_last_post_id(post_id)

if __name__ == "__main__":
    log_message("🚀 Бот запущен!")
    while True:
        send_to_telegram()
        log_message(f"⌛ Ожидание {CHECK_INTERVAL // 60} минут...")
        time.sleep(CHECK_INTERVAL)