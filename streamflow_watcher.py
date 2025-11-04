import asyncio
import aiohttp
import logging

logger = logging.getLogger(__name__)

async def monitor_streamflow(app, chat_id):
    url = "https://api.streamflow.finance/health"
    error_notified = False

    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        logger.info("✅ Streamflow API работает.")
                        if error_notified:
                            await app.bot.send_message(chat_id, "✅ Streamflow API снова в порядке.")
                            error_notified = False
                    else:
                        logger.warning(f"⚠️ Ошибка Streamflow API: {resp.status}")
                        if not error_notified:
                            await app.bot.send_message(chat_id, f"⚠️ Streamflow API ошибка: {resp.status}")
                            error_notified = True
        except Exception as e:
            logger.error(f"Ошибка при мониторинге: {e}")
            if not error_notified:
                await app.bot.send_message(chat_id, f"❌ Ошибка при подключении к Streamflow: {e}")
                error_notified = True

        await asyncio.sleep(30)