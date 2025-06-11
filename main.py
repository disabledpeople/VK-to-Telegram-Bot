
import os
import re
import json
import time
import logging
import configparser
import vk_api
import telebot
import sys
from logging.handlers import RotatingFileHandler
from functools import wraps

sys.stdout.reconfigure(encoding='utf-8')

CONFIG_FILE = "config.ini"
LAST_POST_FILE = "sent_posts.json"

def load_config(config_file=CONFIG_FILE):
    config = configparser.ConfigParser()
    if not os.path.exists(config_file):
        raise FileNotFoundError(f"Конфигурационный файл {config_file} не найден.")
    config.read(config_file, encoding="utf-8")
    return config

config = load_config()
POST_STATUS_FILE = "post_status.json"

def load_post_status():
    if os.path.exists(POST_STATUS_FILE):
        try:
            with open(POST_STATUS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            logger.error("Ошибка загрузки post_status.json")
    return {}

def save_post_status(post_id, success):
    status = load_post_status()
    status[str(post_id)] = {"sent": success, "timestamp": time.time()}
    try:
        with open(POST_STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(status, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения статуса поста {post_id}: {e}")

VK_TOKEN = config.get("VK", "token")
VK_GROUP_ID = config.get("VK", "group_id")
TG_BOT_TOKEN = config.get("TELEGRAM", "bot_token").strip()
TG_CHAT_ID = config.get("TELEGRAM", "chat_id")
CHECK_INTERVAL = config.getint("SETTINGS", "check_interval", fallback=600)
DRY_RUN = config.getboolean("SETTINGS", "dry_run", fallback=False)
ADMIN_CHAT_ID = config.get("TELEGRAM", "admin_chat_id")
BOT_NAME = config.get("TELEGRMA", "bot_name")
VK_LINKS = dict(config.items("VK_LINKS")) if config.has_section("VK_LINKS") else {}

# Логирование
logger = logging.getLogger("vk_tg_bot")
logger.setLevel(logging.INFO)
handler = RotatingFileHandler("bot.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Инициализация API
vk_session = vk_api.VkApi(token=VK_TOKEN)
vk = vk_session.get_api()
bot = telebot.TeleBot(TG_BOT_TOKEN, parse_mode="HTML")

# Retry-декоратор
def retry(max_attempts=3, delay=5):
    def decorator(func):
        @wraps(func)
        def wrapped(*args, **kwargs):
            attempts = 0
            while attempts < max_attempts:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    attempts += 1
                    logger.warning("Ошибка в функции %s. Попытка %d/%d. Ошибка: %s",
                                   func.__name__, attempts, max_attempts, e)
                    time.sleep(delay)
            raise Exception(f"{func.__name__} не смогла выполниться после {max_attempts} попыток.")
        return wrapped
    return decorator

# Обработка текста с гиперссылками
def format_vk_text(text: str) -> str:
    pattern = r"\[club(\d+)\|(.*?)\]"
    def repl(match):
        club_id, name = match.groups()
        url = VK_LINKS.get(f"club{club_id}", f"https://vk.com/club{club_id}")
        return f'<a href="{url}">{name}</a>'
    return re.sub(pattern, repl, text)

# Обработка вложений
def process_attachments(attachments):
    photos, videos, docs = [], [], []
    for att in attachments:
        att_type = att.get("type")
        if att_type == "photo":
            sizes = att["photo"].get("sizes", [])
            if sizes:
                best_photo = max(sizes, key=lambda s: s.get("width", 0) * s.get("height", 0))
                photos.append(best_photo.get("url"))
        elif att_type == "video":
            player = att.get("video", {}).get("player")
            if player:
                videos.append(player)
        elif att_type == "doc":
            url = att.get("doc", {}).get("url")
            if url:
                docs.append(url)
    return photos, videos, docs

# Хранение отправленных постов
SENT_POSTS = set()
if os.path.exists(LAST_POST_FILE):
    try:
        with open(LAST_POST_FILE, "r", encoding="utf-8") as file:
            SENT_POSTS = set(json.load(file))
    except Exception as e:
        logger.warning("Не удалось загрузить файл отправленных постов: %s", e)

def save_sent_posts():
    try:
        with open(LAST_POST_FILE, "w", encoding="utf-8") as file:
            json.dump(list(SENT_POSTS), file, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("Не удалось сохранить отправленные посты: %s", e)

# Уведомление в Telegram об ошибке
def notify_admin(text: str):
    try:
        bot.send_message(TG_CHAT_ID, text, parse_mode="HTML")
    except Exception as e:
        logger.error("Не удалось отправить сообщение об ошибке в Telegram: %s", e)

@retry(max_attempts=3, delay=3)
def get_latest_post():
    response = vk.wall.get(owner_id=-int(VK_GROUP_ID), count=5)
    posts = response.get("items", [])
    for post in posts:
        if post.get("is_pinned"):
            continue  # пропускаем закреплённый
        post_id = post.get("id")
        text = format_vk_text(post.get("text", ""))
        photos, videos, docs = process_attachments(post.get("attachments", []))
        return {
            "id": post_id,
            "text": text,
            "photos": photos,
            "videos": videos,
            "docs": docs
        }
    return None

@bot.message_handler(commands=['force_check'])
def handle_force_check(message):
    if message.text and f'{BOT_NAME}' in message.text:
        logger.info(f"Принудительный запрос поста от пользователя {message.from_user.id}")
        try:
            post = get_latest_post()
            if not post:
                bot.reply_to(message, "Нет новых постов для отправки.")
                return

            # Загрузка статусов постов
            status = load_post_status()
            post_id_str = str(post["id"])

            if status.get(post_id_str, {}).get("sent"):
                bot.reply_to(message, f"Пост ID {post['id']} уже был отправлен ранее.")
                return

            sent = check_and_send_post(post)
            if sent:
                save_post_status(post["id"], True)
                bot.reply_to(message, f"Пост ID {post['id']} успешно отправлен.")
            else:
                save_post_status(post["id"], False)
                bot.reply_to(message, f"Пост ID {post['id']} не был отправлен.")
        except Exception as e:
            logger.exception(f"Ошибка при обработке /force_check: {e}")
            bot.reply_to(message, f"Произошла ошибка: {e}")
    else:
        bot.reply_to(message, "Пожалуйста, используйте команду с полным упоминанием бота /force_check@имя_бота).")


# Получение новых постов
@retry()
def get_all_new_posts():
    response = vk.wall.get(owner_id=-int(VK_GROUP_ID), count=5)
    posts = response.get("items", [])
    new_posts = []
    for post in reversed(posts):  # от старого к новому
        if post.get("is_pinned"):
            continue
        post_id = post.get("id")
        if post_id in SENT_POSTS:
            continue
        text = format_vk_text(post.get("text", ""))
        attachments = post.get("attachments", [])
        photos, videos, docs = process_attachments(attachments)
        new_posts.append({
            "id": post_id,
            "text": text,
            "photos": photos,
            "videos": videos,
            "docs": docs
        })
    return new_posts

def check_and_send_post(post):
    post_id = post["id"]
    text = post["text"]
    photos = post.get("photos", [])
    videos = post.get("videos", [])
    docs = post.get("docs", [])

    logger.info(f"Обработка поста ID {post_id}")

    if DRY_RUN:
        logger.info(f"[dry-run] Пост ID {post_id} будет отправлен с текстом длиной {len(text)} символов, "
                    f"{len(photos)} фото, {len(videos)} видео, {len(docs)} документов.")
        return True

    try:
        # Отправка фотографий медиагруппой
        if photos:
            media_group = []
            for i, photo_url in enumerate(photos):
                # Ограничиваем длину подписи (caption) до 1024 символов (лимит Telegram)
                caption = text[:1024] if i == 0 and text else ""
                media_group.append(telebot.types.InputMediaPhoto(media=photo_url, caption=caption))
            bot.send_media_group(TG_CHAT_ID, media_group)
            logger.info(f"✅ Пост ID {post_id}: фотографии отправлены медиагруппой с подписью.")
        elif text:
            # Если нет фото, отправляем только текст
            bot.send_message(TG_CHAT_ID, text, parse_mode="HTML")
            logger.info(f"✅ Пост ID {post_id}: текст отправлен.")

        # Отправка видео по отдельности, если есть
        for video_url in videos:
            try:
                bot.send_video(TG_CHAT_ID, video=video_url, caption="", parse_mode="HTML")
                logger.info(f"✅ Пост ID {post_id}: видео отправлено {video_url}")
            except Exception as e:
                logger.warning(f"Не удалось отправить видео {video_url} поста {post_id}: {e}")

        # Отправка документов как ссылки
        for doc_url in docs:
            try:
                message = f"Документ: <a href='{doc_url}'>ссылка</a>"
                bot.send_message(TG_CHAT_ID, message, parse_mode="HTML")
                logger.info(f"✅ Пост ID {post_id}: документ отправлен {doc_url}")
            except Exception as e:
                logger.warning(f"Не удалось отправить документ {doc_url} поста {post_id}: {e}")

        return True
    except Exception as exc:
        logger.error(f"❌ Ошибка при отправке поста ID {post_id}: {exc}")
        # Отправить уведомление в Telegram об ошибке
        try:
            bot.send_message(
                ADMIN_CHAT_ID,
                f"❌ Ошибка при отправке поста ID {post_id}:\n{exc}",
                parse_mode="HTML"
            )
        except:
            logger.error("Не удалось отправить уведомление об ошибке в Telegram.")
        return False

# Основной цикл, где вызывается check_and_send_post
def main():
    logger.info(f"🚀 Бот запущен. Dry-run: {DRY_RUN}")
    while True:
        try:
            latest_post = get_latest_post()  # функция получает последний пост из VK (надо реализовать)
            if latest_post:
                sent = check_and_send_post(latest_post)
                if sent:
                    save_post_status(latest_post["id"], True)
                else:
                    save_post_status(latest_post["id"], False)
            else:
                logger.info("Нет новых постов.")
        except Exception as e:
            logger.exception(f"Ошибка в основном цикле: {e}")
            try:
                bot.send_message(ADMIN_CHAT_ID, f"❌ Фатальная ошибка бота:\n{e}", parse_mode="HTML")
            except:
                logger.error("Не удалось отправить уведомление об ошибке в Telegram.")
        logger.info(f"⌛ Ожидание {CHECK_INTERVAL} секунд...")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    bot.polling(none_stop=True)
    main()
