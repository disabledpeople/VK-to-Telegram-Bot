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

# Переопределяем стандартный вывод для поддержки UTF-8 (необходимо для Windows)
sys.stdout.reconfigure(encoding='utf-8')

##################################
# Чтение конфигурации из файла
##################################
CONFIG_FILE = "config.ini"

def load_config(config_file=CONFIG_FILE):
    config = configparser.ConfigParser()
    if not os.path.exists(config_file):
        raise FileNotFoundError(f"Конфигурационный файл {config_file} не найден.")
    config.read(config_file, encoding="utf-8")
    return config

config = load_config()

# Из секций конфигурации
VK_TOKEN = config.get("VK", "token")
VK_GROUP_ID = config.get("VK", "group_id")
TG_BOT_TOKEN = config.get("TELEGRAM", "bot_token").strip()
print("Читаемый токен:", repr(TG_BOT_TOKEN))
TG_CHAT_ID = config.get("TELEGRAM", "chat_id")
CHECK_INTERVAL = config.getint("SETTINGS", "check_interval", fallback=600)

# Словарь замен ссылок, если задан в секции [VK_LINKS]
VK_LINKS = dict(config.items("VK_LINKS")) if config.has_section("VK_LINKS") else {}

##################################
# Настройка логирования с ротацией
##################################
logger = logging.getLogger("vk_tg_bot")
logger.setLevel(logging.INFO)
handler = RotatingFileHandler("bot.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Файл для хранения последнего ID поста
LAST_POST_FILE = "last_post.json"

##################################
# Декоратор для повторных попыток (retry)
##################################
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

##################################
# Инициализация API: VK и Telegram
##################################
vk_session = vk_api.VkApi(token=VK_TOKEN)
vk = vk_session.get_api()
bot = telebot.TeleBot(TG_BOT_TOKEN)

##################################
# Функции для работы с файлом последнего поста
##################################
def load_last_post_id():
    if os.path.exists(LAST_POST_FILE):
        try:
            with open(LAST_POST_FILE, "r", encoding="utf-8") as file:
                data = json.load(file)
                return data.get("last_post_id")
        except json.JSONDecodeError:
            logger.error("Ошибка декодирования JSON в файле последнего поста.")
            return None
    return None

def save_last_post_id(post_id):
    try:
        with open(LAST_POST_FILE, "w", encoding="utf-8") as file:
            json.dump({"last_post_id": post_id}, file)
    except Exception as e:
        logger.error("Ошибка сохранения последнего поста: %s", e)

##################################
# Функция форматирования текста VK
##################################
def format_vk_text(text: str) -> str:
    # Используем raw-строку для регулярного выражения
    pattern = r"\[club(\d+)\|(.*?)\]"
    
    def repl(match):
        club_id, name = match.groups()
        url = VK_LINKS.get(f"club{club_id}", f"https://vk.com/club{club_id}")
        return f'<a href="{url}">{name}</a>'
    
    return re.sub(pattern, repl, text)

##################################
# Обработка вложений поста VK
##################################
def process_attachments(attachments):
    """
    Разбиваем вложения поста по типам:
      - photos: список URL фотографий (изображение максимального качества)
      - videos: список URL видео (из поля 'player')
      - docs: список URL документов
    """
    photos = []
    videos = []
    docs = []
    for att in attachments:
        att_type = att.get("type")
        if att_type == "photo":
            sizes = att["photo"].get("sizes", [])
            if sizes:
                best_photo = max(sizes, key=lambda s: s.get("width", 0) * s.get("height", 0))
                photos.append(best_photo.get("url"))
        elif att_type == "video":
            video = att.get("video", {})
            video_url = video.get("player")
            if video_url:
                videos.append(video_url)
        elif att_type == "doc":
            doc = att.get("doc", {})
            doc_url = doc.get("url")
            if doc_url:
                docs.append(doc_url)
        # Можно добавить обработку других типов вложений
    return photos, videos, docs

##################################
# Получение последнего поста VK (без закрепленных)
##################################
@retry(max_attempts=3, delay=3)
def get_latest_post():
    response = vk.wall.get(owner_id=-int(VK_GROUP_ID), count=5)
    posts = response.get("items", [])
    for post in posts:
        if post.get("is_pinned"):
            continue  # Пропускаем закреплённый пост
        post_id = post.get("id")
        text = format_vk_text(post.get("text", ""))
        attachments = post.get("attachments", [])
        photos, videos, docs = process_attachments(attachments)
        return post_id, text, photos, videos, docs
    return None, None, [], [], []

##################################
# Отправка сообщения в Telegram
##################################
def send_to_telegram():
    last_post_id = load_last_post_id()
    post_id, text, photos, videos, docs = get_latest_post()
    
    if not post_id or post_id == last_post_id:
        logger.info("Новых постов нет.")
        return
    
    try:
        # Отправляем фотографии медиагруппой, если имеются
        if photos:
            media_group = []
            for i, photo in enumerate(photos):
                # К первому фото добавляем подпись (если есть текст)
                caption = text if (i == 0 and text) else ""
                media_group.append(telebot.types.InputMediaPhoto(photo, caption=caption))
            bot.send_media_group(TG_CHAT_ID, media_group)
            logger.info("✅ Фотографии (и, возможно, текст) отправлены медиагруппой.")
        elif text:
            # Если фотографий нет – отправляем текст отдельным сообщением
            bot.send_message(TG_CHAT_ID, text, parse_mode="HTML")
            logger.info("✅ Текст отправлен отдельно.")
        
        # Отправляем видео, если они есть
        for video_url in videos:
            try:
                bot.send_video(TG_CHAT_ID, video=video_url,
                               caption=text if not photos else "", parse_mode="HTML")
                logger.info("✅ Видео отправлено: %s", video_url)
            except Exception as e:
                logger.warning("Не удалось отправить видео %s: %s", video_url, e)
        
        # Отправляем документы, если имеются (в виде ссылок)
        for doc_url in docs:
            try:
                message = f"Документ: <a href='{doc_url}'>Ссылка</a>"
                bot.send_message(TG_CHAT_ID, message, parse_mode="HTML")
                logger.info("✅ Документ отправлен: %s", doc_url)
            except Exception as e:
                logger.warning("Не удалось отправить документ %s: %s", doc_url, e)
    except Exception as exc:
        logger.exception("❌ Фатальная ошибка при отправке сообщения: %s", exc)
    
    save_last_post_id(post_id)

##################################
# Основной цикл работы бота
##################################
def main():
    logger.info("🚀 Бот запущен!")
    while True:
        try:
            send_to_telegram()
        except Exception as err:
            logger.exception("Ошибка в основном цикле: %s", err)
        logger.info("⌛ Ожидание %d минут...", CHECK_INTERVAL // 60)
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
