import asyncio
import logging
from telegram import Bot
from telegram.constants import ParseMode
from dotenv import load_dotenv
import os
from streamflow_watcher import get_new_locks

load_dotenv()
logging.basicConfig(level=logging.INFO)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

bot = Bot(token=TELEGRAM_TOKEN)

async def send_telegram_message(text):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode=ParseMode.HTML)
    except Exception as e:
        logging.error(f"Ошибка при отправке сообщения: {e}")

async def monitor_streamflow():
    logging.info("🚀 Бот запущен и мониторит Streamflow...")
    while True:
        try:
            new_locks = await get_new_locks()
            if new_locks:
                for lock in new_locks:
                    msg = f"""
🚀 <b>Новый токен с Pump.fun заблокировал ликвидность!</b>

💎 <b>{lock.get('name', 'Unknown')}</b> ({lock.get('symbol', '')})
🕒 Создан: {lock.get('created_ago')}
🔗 <a href="https://solscan.io/tx/{lock.get('tx_hash')}">Открыть в Solscan</a>
"""
                    await send_telegram_message(msg)
            await asyncio.sleep(30)
        except Exception as e:
            logging.error(f"Ошибка в цикле мониторинга: {e}")
            await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(monitor_streamflow())
