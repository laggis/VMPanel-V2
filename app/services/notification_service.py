import httpx
from datetime import datetime
from app.core.config import settings

class NotificationService:
    async def send_discord_alert(self, title: str, description: str, color: int = 3447003, fields: list = None, webhook_url: str = None, thumbnail_url: str = None, image_url: str = None, author: dict = None, footer: dict = None):
        """
        Sends a Discord notification.
        If webhook_url is provided, sends to that URL.
        Otherwise, sends to the global admin webhook (if configured).
        """
        target_url = webhook_url or settings.DISCORD_WEBHOOK_URL
        
        if not target_url:
            # Only log if we expected to send one but couldn't
            if webhook_url:
                print("Provided Webhook URL is empty. Skipping.")
            return

        embed = {
            "title": title,
            "description": description,
            "color": color,
            "timestamp": datetime.now().isoformat()
        }
        
        # Default footer if not provided
        if footer:
             embed["footer"] = footer
        else:
             embed["footer"] = {"text": "VM Control Panel Notification"}

        if fields:
            embed["fields"] = fields
            
        if thumbnail_url:
            embed["thumbnail"] = {"url": thumbnail_url}
            
        if image_url:
            embed["image"] = {"url": image_url}
            
        if author:
            embed["author"] = author

        payload = {
            "embeds": [embed]
        }
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(target_url, json=payload)
                response.raise_for_status()
            except Exception as e:
                print(f"Failed to send Discord notification to {target_url}: {e}")

notification_service = NotificationService()
