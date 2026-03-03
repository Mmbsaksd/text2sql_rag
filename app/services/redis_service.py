import httpx
import json
from app.config import settings

class RedisService:
    def __init__(self):
        self.url = settings.UPSTASH_REDIS_REST_URL
        self.token = settings.UPSTASH_REDIS_REST_TOKEN

    async def get(self, key: str):
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.url}/get/{key}",
                headers={"Authorization": f"Bearer {self.token}"}
            )

            if response.status_code != 200:
                return None
            
            data = response.json()

            value = data.get("result")

            if value is None:
                return None
            return json.load(value)
        
    async def set(self, key: str, value, ttl: int = None):
        pass

    async def health_check(self):
        async with httpx.AsyncClient as client:
            response = await client.get(
                f"{self.url}/ping",
                headers={"Authorization": f"Bearer {self.token}"}
            )
            return response.status_code==200