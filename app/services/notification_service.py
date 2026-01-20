import httpx
from app.core.config import settings

class NotificationService:
    async def send_discord_alert(self, message: str):
        if not settings.DISCORD_WEBHOOK_URL:
            print("Discord Webhook URL not configured. Skipping notification.")
            return

        payload = {
            "content": message
        }
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(settings.DISCORD_WEBHOOK_URL, json=payload)
                response.raise_for_status()
            except Exception as e:
                print(f"Failed to send Discord notification: {e}")

notification_service = NotificationService()
