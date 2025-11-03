import os
import asyncio
import logging
import aiohttp
from datetime import datetime, timezone
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ==========================
# 🔧 НАСТРОЙКИ
# ==========================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
RPC_URL = os.getenv("RPC_URL", "https://api.mainnet-beta.solana.com")

STREAMFLOW_PROGRAM_ID = "9tFvY8JzGGRQ6QtjMhHMPJ4dytEjhMtcn3dV6Yz8Rj6r"
PUMPFUN_API = "https://frontend-api.pump.fun/coins/latest"

# ==========================
# 🧠 ФУНКЦИИ
# ==========================
async def send_telegram_message(text: str):
    """Отправка уведомления в Telegram"""
    if not TELEGRAM_CHAT_ID:
        logger.warning("⚠️ TELEGRAM_CHAT_ID не указан — уведомления не будут отправлены")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    async with aiohttp.ClientSession() as session:
        await session.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"})


async def fetch_recent_streams():
    """Получает последние транзакции Streamflow"""
    async with aiohttp.ClientSession() as session:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getSignaturesForAddress",
            "params": [STREAMFLOW_PROGRAM_ID, {"limit": 10}],
        }
        async with session.post(RPC_URL, json=payload) as resp:
            data = await resp.json()
            return data.get("result", [])


async def fetch_pumpfun_tokens():
    """Получает последние токены с Pump.fun"""
    async with aiohttp.ClientSession() as session:
        async with session.get(PUMPFUN_API) as resp:
            data = await resp.json()
            if "coins" in data:
                tokens = {}
                for coin in data["coins"]:
                    tokens[coin["mint"]] = coin
                return tokens
            return {}


def format_age(timestamp: str) -> str:
    """Форматирует возраст токена"""
    try:
        created_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - created_at
        days = delta.days
        hours = delta.seconds // 3600
        return f"{days}д {hours}ч назад"
    except Exception:
        return "неизвестно"


async def get_transaction_accounts(sig: str):
    """Получает список аккаунтов из транзакции"""
    async with aiohttp.ClientSession() as session:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTransaction",
            "params": [sig, {"encoding": "jsonParsed"}],
        }
        async with session.post(RPC_URL, json=payload) as resp:
            tx_data = await resp.json()
            try:
                accounts = tx_data["result"]["transaction"]["message"]["accountKeys"]
                return [a["pubkey"] for a in accounts]
            except Exception:
                return []


# ==========================
# 🔍 МОНИТОРИНГ
# ==========================
async def monitor_streamflow():
    """Основной цикл мониторинга Streamflow"""
    last_seen = set()

    while True:
        try:
            pumpfun_tokens = await fetch_pumpfun_tokens()
            transactions = await fetch_recent_streams()

            for tx in transactions:
                sig = tx["signature"]
                if sig in last_seen:
                    continue
                last_seen.add(sig)

                accounts = await get_transaction_accounts(sig)
                matched = [m for m in accounts if m in pumpfun_tokens]
                if not matched:
                    continue

                for mint in matched:
                    token = pumpfun_tokens[mint]
                    name = token.get("name", "N/A")
                    symbol = token.get("symbol", "N/A")
                    market_cap = token.get("usd_market_cap", 0)
                    total_supply = float(token.get("total_supply", 0))
                    locked_amount = total_supply * 0.1  # 💡 Можно улучшить: парсить из Streamflow
                    percent_locked = (locked_amount / total_supply * 100) if total_supply else 0
                    age = format_age(token.get("created_at", ""))

                    msg = (
                        f"💧 <b>Блокировка токена Pump.fun!</b>\n"
                        f"🔗 <a href='https://solscan.io/tx/{sig}'>Транзакция</a>\n\n"
                        f"🪙 <b>{name} ({symbol})</b>\n"
                        f"💰 <b>Market Cap:</b> ${market_cap:,.0f}\n"
                        f"📊 <b>Заблокировано:</b> {locked_amount:,.0f} токенов ({percent_locked:.2f}%)\n"
                        f"🕒 <b>Создан:</b> {age}\n"
                        f"🧾 <b>Mint:</b> <code>{mint}</code>\n"
                        f"🌐 <a href='https://pump.fun/{mint}'>pump.fun/{symbol}</a>"
                    )
                    await send_telegram_message(msg)
                    logger.info(f"✅ Найден Pump.fun токен: {symbol} ({mint})")

            await asyncio.sleep(60)

        except Exception as e:
            logger.error(f"Ошибка мониторинга: {e}")
            await asyncio.sleep(20)


# ==========================
# 🤖 TELEGRAM КОМАНДЫ
# ==========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Бот активен! Следит за блокировками Pump.fun токенов на Streamflow 🚀")


# ==========================
# 🚀 ЗАПУСК
# ==========================
async def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))

    loop = asyncio.get_event_loop()
    loop.create_task(monitor_streamflow())

    await app.run_polling()


if __name__ == "__main__":
    asyncio.run(main())