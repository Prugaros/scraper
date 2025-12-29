import httpx
import asyncio
import time

async def send_discord_message(webhook_url, embed):
    """Sends a message to a Discord channel using a webhook."""
    headers = {
        "Content-Type": "application/json"
    }
    data = {"embeds": [embed]}
    async with httpx.AsyncClient() as client:
        try:
            print(f"Sending request to Discord at {time.time()}")
            response = await client.post(webhook_url, json=data, headers=headers)
            response.raise_for_status()
            await asyncio.sleep(1.5)
        except Exception as e:
            print(f"Failed to send message to Discord: {e}")
