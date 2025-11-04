# -*- coding: utf-8 -*-
import asyncio
import aiohttp
import nest_asyncio
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from dotenv import load_dotenv
import os

# Разрешаем повторное использование event loop (нужно для Python 3.14)
nest_asyncio.apply()

# Настройка логов
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Загружаем токены из .env
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not TELEGRAM_TOKEN:
    raise ValueError("Отсутствует TELEGRAM_TOKEN в .env")

# Функция для отправки сообщений в Telegram
async def send_telegram_message(text: str):
    try:
        from telegram import Bot
        bot = Bot(token=TELEGRAM_TOKEN)
        await bot.send_message(chat_id=CHAT_ID, text=text)
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения: {e}")

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Бот запущен и готов к работе.")

# Основной цикл мониторинга
async def monitor_streamflow():
    url = "https://api.mainnet-beta.solana.com"
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getEpochInfo"
    }

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.post(url, json=payload, timeout=15) as response:
                    if response.status == 200:
                        data = await response.json()
                        epoch = data.get("result", {}).get("epoch")
                        logger.info(f"Текущий epoch: {epoch}")
                    else:
                        logger.warning(f"Ошибка API Solana: {response.status}")
                await asyncio.sleep(30)
            except Exception as e:
                logger.error(f"Ошибка в цикле мониторинга: {e}")
                await asyncio.sleep(60)

# Главная функция
async def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))

    logger.info("Telegram бот запущен.")
    await send_telegram_message("Бот запущен и мониторит Streamflow.")
    
    # Запуск мониторинга и Telegram-бота параллельно
    await asyncio.gather(
        monitor_streamflow(),
        app.run_polling()
    )

if __name__ == "__main__":
    asyncio.run(main())