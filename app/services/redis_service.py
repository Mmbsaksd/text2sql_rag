import httpx
from app.config import settings

class RedisService:
    def __init__(self):
        self.url = settings.UPSTASH_REDIS_REST_URL
        self.token = settings.UPSTASH_REDIS_REST_TOKEN

    async def health_check(self):
        async with httpx.AsyncClient as client:
            response = await client.get(
                f"{self.url}/ping",
                headers={"Authorization": f"Bearer {self.token}"}
            )
            return response.status_code==200