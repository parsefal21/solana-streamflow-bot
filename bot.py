# -*- coding: utf-8 -*-
import os
import aiohttp
import asyncio
import logging
from datetime import datetime, timezone
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)
from dotenv import load_dotenv

# === Настройка ===
load_dotenv()  # локально, для Railway переменные через Environment Variables

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not TELEGRAM_TOKEN:
    raise ValueError("❌ TELEGRAM_TOKEN не задан! Задайте через Environment Variables на Railway.")
if not TELEGRAM_CHAT_ID:
    raise ValueError("❌ TELEGRAM_CHAT_ID не задан! Задайте через Environment Variables на Railway.")

RPC_URL = "https://api.mainnet-beta.solana.com"
STREAMFLOW_PROGRAM = "7AnS5vRWuNNAh4bKf7ZLfXoZKvK2ekBvZqH6hZkz3xRi"
PUMPFUN_PROGRAM = "pumpfun1m8jLZsXMuF8qLbUy1hE7bMYDqSEnFtV3Eo2P"
PUMPFUN_API = "https://api.pump.fun/v1/tokens/"

LAST_SEEN = set()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pumpfun_bot")

# === Telegram функции ===
async def send_message(bot, text):
    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text, parse_mode="HTML")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Бот активен! Мониторинг PumpFun токенов запущен.")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    text = update.message.text
    await update.message.reply_text(f"Привет, {user.first_name}! Я получил твоё сообщение:\n{text}")

# === Solana RPC ===
async def rpc_request(session, method, params):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    async with session.post(RPC_URL, json=payload) as resp:
        return await resp.json()

async def get_signatures(session):
    res = await rpc_request(session, "getSignaturesForAddress", [STREAMFLOW_PROGRAM, {"limit": 50}])
    return res.get("result", [])

async def get_transaction(session, signature):
    res = await rpc_request(session, "getTransaction", [signature, {"encoding": "json", "maxSupportedTransactionVersion": 0}])
    return res.get("result")

def extract_mint(tx):
    try:
        accounts = tx.get("transaction", {}).get("message", {}).get("accountKeys", [])
        for acc in accounts:
            if not acc.get("signer") and acc.get("writable"):
                return acc.get("pubkey")
    except Exception:
        return None

def is_pumpfun_tx(tx):
    accounts = tx.get("transaction", {}).get("message", {}).get("accountKeys", [])
    return any(PUMPFUN_PROGRAM in acc.get("pubkey", "") for acc in accounts)

# === Token info & supply ===
async def get_token_info(session, mint):
    res = await rpc_request(session, "getAccountInfo", [mint, {"encoding": "jsonParsed"}])
    val = res.get("result", {}).get("value", {})
    data = val.get("data", {}).get("parsed", {}).get("info", {})
    return {
        "symbol": data.get("symbol", "???"),
        "name": data.get("name", "Unknown Token"),
        "decimals": data.get("decimals", 0),
    }

async def get_token_supply(session, mint):
    res = await rpc_request(session, "getTokenSupply", [mint])
    val = res.get("result", {}).get("value", {})
    return float(val.get("uiAmount", 0))

# === Market Cap ===
async def get_market_cap_pumpfun(session, symbol):
    try:
        url = f"{PUMPFUN_API}{symbol.lower()}"
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.json()
                return float(data.get("market_cap", 0))
    except Exception as e:
        logger.warning(f"PumpFun API ошибка: {e}")
    return 0

async def get_market_cap_coingecko(session, symbol):
    try:
        url = f"https://api.coingecko.com/api/v3/coins/solana/contract/{symbol.lower()}"
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.json()
                return float(data.get("market_data", {}).get("market_cap", {}).get("usd", 0))
    except Exception as e:
        logger.warning(f"CoinGecko ошибка: {e}")
    return 0

# === Format message ===
async def format_lock_message(lock):
    market_cap = lock.get("market_cap", 0)
    locked = lock.get("locked_amount", 0)
    total = lock.get("total_supply", 1)
    percent = (locked / total * 100) if total else 0
    msg = (
        f"🚀 <b>Новый PumpFun токен на Streamflow!</b>\n\n"
        f"💎 <b>{lock.get('name')}</b> ({lock.get('symbol')})\n"
        f"💰 Market Cap: ${market_cap:,.0f}\n"
        f"🔒 Заблокировано: {locked:,.0f} токенов ({percent:.2f}% от supply)\n"
        f"⏱️ Создан: {lock.get('created_ago')}\n"
        f"🔗 <a href='https://solscan.io/tx/{lock.get('tx_hash')}'>Solscan</a>"
    )
    return msg

# === Monitoring ===
async def monitor_streamflow(session, bot):
    signatures = await get_signatures(session)
    for sig_info in signatures:
        sig = sig_info["signature"]
        if sig in LAST_SEEN:
            continue
        LAST_SEEN.add(sig)

        tx = await get_transaction(session, sig)
        if not tx or not is_pumpfun_tx(tx):
            continue

        mint = extract_mint(tx)
        if not mint:
            continue

        meta = await get_token_info(session, mint)
        supply = await get_token_supply(session, mint)
        locked = supply * 0.25  # пример, замените реальными данными

        market_cap = await get_market_cap_pumpfun(session, meta.get("symbol"))
        if market_cap == 0:
            market_cap = await get_market_cap_coingecko(session, meta.get("symbol"))

        created_ago = "н/д"
        if tx.get("blockTime"):
            dt = datetime.fromtimestamp(tx["blockTime"], tz=timezone.utc)
            delta = datetime.now(timezone.utc) - dt
            created_ago = f"{delta.seconds // 60} мин назад"

        info = {
            "name": meta.get("name"),
            "symbol": meta.get("symbol"),
            "market_cap": market_cap,
            "locked_amount": locked,
            "total_supply": supply,
            "created_ago": created_ago,
            "tx_hash": sig,
        }

        msg = await format_lock_message(info)
        await send_message(bot, msg)
        await asyncio.sleep(2)

async def monitor_streamflow_task(bot, session):
    logger.info("🚀 Запущен мониторинг Streamflow...")
    while True:
        try:
            await monitor_streamflow(session, bot)
        except Exception as e:
            logger.error(f"Ошибка мониторинга: {e}")
        await asyncio.sleep(60)

# === Main ===
async def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    bot = app.bot
    async with aiohttp.ClientSession() as session:
        asyncio.create_task(monitor_streamflow_task(bot, session))
        logger.info("✅ Telegram бот запущен.")
        await app.run_polling(stop_signals=None)

if __name__ == "__main__":
    asyncio.run(main())
