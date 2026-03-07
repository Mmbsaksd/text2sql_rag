import logging
logger = logging.getLogger("app")
from urllib.parse import quote
import httpx
import json
from app.config import settings

class RedisService:
    def __init__(self):
        self.url = settings.UPSTASH_REDIS_REST_URL
        self.token = settings.UPSTASH_REDIS_REST_TOKEN

    async def get(self, key: str):
        async with httpx.AsyncClient(timeout=5.0) as client:
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
            result =  json.loads(value)
            if isinstance(result, str):
                result = json.loads(result)
            
            return result
        
    async def set(self, key: str, value, ttl: int = None):
        try:
            serialized = quote(json.dumps(value))
            headers= {
            "Authorization": f"Bearer {self.token}"
        }
            async with httpx.AsyncClient(timeout=5.0) as client:
                if ttl:
                    response = await client.get(
                        f"{self.url}/set/{key}?value={serialized}&ex={ttl}",
                        headers=headers,
                    )
                else:
                    response = await client.get(
                        f"{self.url}/set/{key}?value={serialized}",
                        headers=headers,
                    )
                return response.status_code == 200
        except Exception as e:
            logger.error(f"Redis SET failed for key {key}: {e}")
            return False

    async def health_check(self):
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"{self.url}/ping",
                headers={"Authorization": f"Bearer {self.token}"}
            )
            return response.status_code==200