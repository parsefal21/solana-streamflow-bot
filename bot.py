# -*- coding: utf-8 -*-
import os
import aiohttp
import asyncio
import logging
from datetime import datetime
from solana.rpc.async_api import AsyncClient
from telegram import Bot
from dotenv import load_dotenv

# =====================================
# CONFIG
# =====================================
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
STREAMFLOW_PROGRAM_ID = "4Nd1mW89xwYruwFjv6Jefzp2h2bxv3FrF7tqk3hECUf1"
RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")

# =====================================
# LOGGING
# =====================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =====================================
# TELEGRAM
# =====================================
bot = Bot(token=TELEGRAM_TOKEN)

async def send_telegram_message(text: str):
    """Отправка сообщения в Telegram"""
    try:
        await bot.send_message(chat_id=CHAT_ID, text=text, disable_web_page_preview=True)
        logger.info("Сообщение отправлено в Telegram")
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения: {e}")

# =====================================
# STREAMFLOW MONITOR
# =====================================
async def fetch_streamflow_transactions(before=None):
    """Получить последние транзакции Streamflow"""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getSignaturesForAddress",
        "params": [
            STREAMFLOW_PROGRAM_ID,
            {"limit": 10, "commitment": "confirmed", **({"before": before} if before else {})}
        ]
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(RPC_URL, json=payload) as response:
            data = await response.json()
            return data.get("result", [])

async def get_transaction_details(signature: str):
    """Получить подробности транзакции"""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [signature, {"encoding": "jsonParsed", "commitment": "confirmed"}]
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(RPC_URL, json=payload) as response:
            data = await response.json()
            return data.get("result", {})

def extract_token_address(tx_data):
    """Извлечь адрес токена"""
    try:
        instructions = tx_data.get("transaction", {}).get("message", {}).get("instructions", [])
        for ix in instructions:
            if isinstance(ix, dict):
                accounts = ix.get("accounts", [])
                for acc in accounts:
                    if isinstance(acc, str) and len(acc) == 44:
                        return acc
    except Exception:
        pass
    return None

async def fetch_token_metadata(mint: str):
    """Получить данные токена через DexScreener"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.dexscreener.com/latest/dex/tokens/{mint}") as resp:
                data = await resp.json()
                if "pairs" in data and data["pairs"]:
                    token = data["pairs"][0]
                    info = {
                        "name": token["baseToken"]["name"],
                        "symbol": token["baseToken"]["symbol"],
                        "mc": token.get("fdv", 0),
                        "created": token.get("pairCreatedAt", 0),
                        "url": f"https://gmgn.ai/sol/token/{mint}"
                    }
                    return info
    except Exception as e:
        logger.error(f"Ошибка при получении метаданных токена {mint}: {e}")
    return None

async def fetch_locked_supply_percentage(mint: str):
    """Получить процент заблокированных токенов через Streamflow API"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.streamflow.finance/v1/locks/{mint}") as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                total_locked = sum(float(lock.get("amount", 0)) for lock in data)
                if not total_locked:
                    return None
                total_supply = sum(float(lock.get("tokenTotalSupply", 0)) for lock in data if lock.get("tokenTotalSupply"))
                if total_supply > 0:
                    percent = (total_locked / total_supply) * 100
                    return round(percent, 2)
    except Exception as e:
        logger.error(f"Ошибка при получении процента блокировки: {e}")
    return None

def calculate_token_age(created_timestamp):
    """Рассчитать возраст токена"""
    if not created_timestamp:
        return "неизвестно"
    created_dt = datetime.fromtimestamp(created_timestamp / 1000)
    delta_days = (datetime.utcnow() - created_dt).days
    return f"{delta_days} дн."

# =====================================
# MAIN MONITOR LOOP
# =====================================
async def monitor_streamflow():
    client = AsyncClient(RPC_URL)
    last_checked = None
    seen_sigs = set()

    logger.info("Бот запущен и мониторит Streamflow")

    while True:
        try:
            txs = await fetch_streamflow_transactions(before=last_checked)
            for tx in txs:
                sig = tx["signature"]
                if sig in seen_sigs:
                    continue
                seen_sigs.add(sig)

                tx_data = await get_transaction_details(sig)
                token_address = extract_token_address(tx_data)
                if not token_address:
                    continue

                token_info = await fetch_token_metadata(token_address)
                if not token_info:
                    continue

                locked_percent = await fetch_locked_supply_percentage(token_address)
                locked_text = f"{locked_percent}%" if locked_percent else "неизвестно"

                message = (
                    f"Обнаружена блокировка токена через Streamflow\n\n"
                    f"Имя: {token_info['name']}\n"
                    f"Тикер: {token_info['symbol']}\n"
                    f"Market Cap: {token_info['mc']:,}\n"
                    f"Заблокировано: {locked_text}\n"
                    f"Возраст токена: {calculate_token_age(token_info['created'])}\n\n"
                    f"Подробнее: {token_info['url']}"
                )

                await send_telegram_message(message)

            if txs:
                last_checked = txs[-1]["signature"]

            await asyncio.sleep(20)

        except Exception as e:
            logger.error(f"Ошибка мониторинга: {e}")
            await asyncio.sleep(10)

# =====================================
# ENTRY POINT
# =====================================
if __name__ == "__main__":
    asyncio.run(monitor_streamflow())