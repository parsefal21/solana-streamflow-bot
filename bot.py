# -*- coding: utf-8 -*-
import os
import aiohttp
import asyncio
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# --------------------------------------------
# Настройки логирования
# --------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --------------------------------------------
# Загрузка .env и переменных окружения
# --------------------------------------------
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not TELEGRAM_TOKEN:
    raise ValueError("Не найден TELEGRAM_TOKEN в .env")

# --------------------------------------------
# Константы
# --------------------------------------------
STREAMFLOW_API = "https://public-api.streamflow.finance/v1/solana/mainnet/streams"
GMGN_TERMINAL = "https://gmgn.ai/sol/token/"
CHECK_INTERVAL = 60  # каждые 60 секунд проверка новых стримов

# Чтобы не дублировать сообщения
seen_streams = set()

# --------------------------------------------
# Команды Telegram
# --------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Я бот, отслеживающий заблокированные токены на Streamflow.")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Вы написали: {update.message.text}")

# --------------------------------------------
# Streamflow функции
# --------------------------------------------
async def fetch_streamflow_streams():
    """Получает все активные стримы со Streamflow API"""
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(STREAMFLOW_API) as resp:
                if resp.status != 200:
                    logger.error(f"Ошибка Streamflow API: {resp.status}")
                    return []
                data = await resp.json()
                return data.get("streams", [])
        except Exception as e:
            logger.error(f"Ошибка при запросе Streamflow API: {e}")
            return []

async def process_stream(stream, bot):
    """Обрабатывает новый найденный стрим"""
    stream_id = stream.get("id")
    if not stream_id or stream_id in seen_streams:
        return

    seen_streams.add(stream_id)

    token_mint = stream.get("mint")
    sender = stream.get("sender")
    recipient = stream.get("recipient")
    total_amount = int(stream.get("amount", 0)) / (10 ** int(stream.get("mint_decimals", 9)))
    start_time = datetime.fromtimestamp(int(stream.get("start_time", 0)), tz=timezone.utc)
    now = datetime.now(timezone.utc)
    age_days = (now - start_time).days

    # Процент заблокированного супплая
    locked_percent = None
    if stream.get("total_supply"):
        total_supply = int(stream.get("total_supply"))
        if total_supply > 0:
            locked_percent = round((int(stream.get("amount", 0)) / total_supply) * 100, 2)

    token_name = stream.get("mint_symbol") or "Unknown"
    token_symbol = stream.get("mint_symbol") or "???"

    gmgn_link = f"{GMGN_TERMINAL}{token_mint}"

    message_lines = [
        "Новый заблокированный токен через Streamflow:",
        f"• Название: {token_name}",
        f"• Тикер: {token_symbol}",
        f"• Адрес токена: {token_mint}",
        f"• Отправитель: {sender}",
        f"• Получатель: {recipient}",
        f"• Количество: {total_amount:,.2f}",
        f"• Возраст токена: {age_days} дн.",
    ]

    if locked_percent is not None:
        message_lines.append(f"• Заблокировано от супплая: {locked_percent}%")

    message_lines.append(f"\nСсылка: {gmgn_link}")

    text = "\n".join(message_lines)

    try:
        await bot.send_message(chat_id=CHAT_ID, text=text)
        logger.info(f"Отправлено уведомление о новом стриме: {stream_id}")
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения: {e}")

async def monitor_streamflow(bot):
    """Основной цикл мониторинга"""
    logger.info("Мониторинг Streamflow запущен")
    while True:
        streams = await fetch_streamflow_streams()
        for s in streams:
            await process_stream(s, bot)
        await asyncio.sleep(CHECK_INTERVAL)

# --------------------------------------------
# Основная функция
# --------------------------------------------
async def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Команды Telegram
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    # Запускаем мониторинг параллельно
    asyncio.create_task(monitor_streamflow(app.bot))

    logger.info("Telegram бот запущен.")
    await app.run_polling()

# --------------------------------------------
# Точка входа
# --------------------------------------------
if __name__ == "__main__":
    asyncio.run(main())