import aiohttp
import asyncio
from datetime import datetime, timezone

RPC_URL = "https://api.mainnet-beta.solana.com"

STREAMFLOW_PROGRAM = "7AnS5vRWuNNAh4bKf7ZLfXoZKvK2ekBvZqH6hZkz3xRi"
PUMPFUN_PROGRAM = "pumpfun1m8jLZsXMuF8qLbUy1hE7bMYDqSEnFtV3Eo2P"

LAST_SEEN = set()

async def rpc_request(session, method, params):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    async with session.post(RPC_URL, json=payload) as resp:
        return await resp.json()

async def get_confirmed_signatures(session, before=None):
    res = await rpc_request(session, "getSignaturesForAddress", [
        STREAMFLOW_PROGRAM, {"limit": 50, "before": before}
    ])
    return res.get("result", [])

async def get_parsed_transaction(session, signature):
    res = await rpc_request(session, "getTransaction", [
        signature, {"encoding": "json", "maxSupportedTransactionVersion": 0}
    ])
    return res.get("result")

async def get_token_metadata(session, mint):
    """
    Получаем метаданные токена (symbol, name, decimals) через getAccountInfo.
    """
    res = await rpc_request(session, "getAccountInfo", [
        mint, {"encoding": "jsonParsed"}
    ])
    info = res.get("result", {}).get("value", {})
    if not info:
        return None

    data = info.get("data", {}).get("parsed", {}).get("info", {})
    decimals = data.get("decimals", 0)
    symbol = data.get("symbol", "???")
    name = data.get("name", "Unknown Token")

    return {"symbol": symbol, "name": name, "decimals": decimals}

def extract_mint_account(tx):
    """
    Пытаемся извлечь адрес mint-токена из инструкции.
    """
    try:
        message = tx.get("transaction", {}).get("message", {})
        accounts = message.get("accountKeys", [])
        for acc in accounts:
            if acc.get("signer") is False and acc.get("writable") is True:
                # Вероятный mint токен
                return acc.get("pubkey")
    except Exception:
        pass
    return None

def extract_lock_info(tx):
    if not tx or "meta" not in tx or not tx["meta"]:
        return None

    accounts = tx.get("transaction", {}).get("message", {}).get("accountKeys", [])
    if not any(PUMPFUN_PROGRAM in a.get("pubkey", "") for a in accounts):
        return None  # не pumpfun

    block_time = tx.get("blockTime")
    created_ago = "н/д"
    if block_time:
        dt = datetime.fromtimestamp(block_time, tz=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        created_ago = f"{delta.seconds // 60} мин назад"

    return {
        "tx_hash": tx.get("transaction", {}).get("signatures", [""])[0],
        "created_ago": created_ago,
        "mint": extract_mint_account(tx)
    }

async def get_new_locks():
    results = []
    async with aiohttp.ClientSession() as session:
        signatures = await get_confirmed_signatures(session)

        for sig_info in signatures:
            sig = sig_info["signature"]
            if sig in LAST_SEEN:
                continue
            LAST_SEEN.add(sig)

            tx = await get_parsed_transaction(session, sig)
            info = extract_lock_info(tx)
            if not info:
                continue

            if info["mint"]:
                meta = await get_token_metadata(session, info["mint"])
                if meta:
                    info.update(meta)

            results.append(info)
    return results

if __name__ == "__main__":
    async def main():
        locks = await get_new_locks()
        for lock in locks:
            print(f"""
🚀 Новый Pump.fun токен заблокировал ликвидность на Streamflow!

💎 {lock.get('name', 'Unknown')} ({lock.get('symbol', '')})
🕒 Создан: {lock.get('created_ago')}
🔗 Транзакция: https://solscan.io/tx/{lock.get('tx_hash')}
            """)
    asyncio.run(main())