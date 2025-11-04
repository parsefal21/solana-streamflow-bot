import asyncio
import aiohttp
import logging
import os
from datetime import datetime
from solana.rpc.async_api import AsyncClient
from solana.publickey import PublicKey
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

load_dotenv()

# --- Настройки ---
STREAMFLOW_API = "https://api.streamflow.finance/v1/locks"
RPC_URL = "https://api.mainnet-beta.solana.com"
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- Логирование ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Получение данных о токене ---
async def get_token_info(mint: str):
    url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                if "pairs" not in data or not data["pairs"]:
                    return None
                pair = data["pairs"][0]
                token_info = {
                    "name": pair["baseToken"]["name"],
                    "symbol": pair["baseToken"]["symbol"],
                    "marketCap": pair.get("marketCap", 0),
                    "pairCreatedAt": pair.get("pairCreatedAt", 0)
                }
                return token_info
    except Exception as e:
        logger.error(f"Ошибка при получении информации о токене: {e}")
        return None


# --- Форматирование сообщения ---
def format_lock_message(mint, amount, percent_locked, token_info):
    try:
        created_at = token_info.get("pairCreatedAt")
        if created_at:
            age_days = (datetime.utcnow() - datetime.utcfromtimestamp(created_at / 1000)).days
            age = f"{age_days} дн."
        else:
            age = "неизвестен"

        message = (
            f"Найден токен с блокировкой на Streamflow\n\n"
            f"Имя: {token_info['name']}\n"
            f"Тикер: {token_info['symbol']}\n"
            f"Заблокировано: {percent_locked:.2f}% от supply\n"
            f"Возраст токена: {age}\n"
            f"Market Cap: ${token_info['marketCap']:,}\n"
            f"Ссылка: https://gmgn.ai/sol/token/{mint}"
        )
        return message
    except Exception as e:
        logger.error(f"Ошибка при форматировании сообщения: {e}")
        return f"Ошибка при обработке токена {mint}"


# --- Проверка токенов в Streamflow ---
async def check_streamflow_locks(app: Application):
    logger.info("Мониторинг Streamflow запущен...")

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(STREAMFLOW_API, timeout=20) as resp:
                    if resp.status != 200:
                        logger.warning(f"Streamflow API вернул {resp.status}")
                        await asyncio.sleep(30)
                        continue

                    locks = await resp.json()

                    for lock in locks:
                        mint = lock.get("mint")
                        if not mint:
                            continue

                        percent_locked = lock.get("percentLocked", 0)
                        amount = lock.get("amount", 0)

                        if percent_locked > 5:
                            token_info = await get_token_info(mint)
                            if token_info:
                                message = format_lock_message(mint, amount, percent_locked, token_info)
                                await app.bot.send_message(chat_id=CHAT_ID, text=message)

                await asyncio.sleep(60)

            except Exception as e:
                logger.error(f"Ошибка в цикле мониторинга: {e}")
                await asyncio.sleep(30)


# --- Команды Telegram ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Бот запущен и отслеживает блокировки Streamflow.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Этот бот уведомляет о новых блокировках токенов в Streamflow.\nКоманды:\n/start — запустить\n/help — помощь")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Вы сказали: {update.message.text}")


# --- Основная функция ---
async def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    asyncio.create_task(check_streamflow_locks(app))

    logger.info("Бот запущен и мониторит Streamflow...")
    await app.run_polling()


if __name__ == "__main__":
    asyncio.run(main())