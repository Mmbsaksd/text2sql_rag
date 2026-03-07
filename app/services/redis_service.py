import logging
logger = logging.getLogger("app")

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
            serialized = json.dumps(value)
            headers= {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
            async with httpx.AsyncClient(timeout=5.0) as client:
                if ttl:
                    response = await client.post(
                        f"{self.url}/set/{key}/ex/{ttl}",
                        headers=headers,
                        content=serialized 
                    )
                else:
                    response = await client.post(
                        f"{self.url}/set/{key}",
                        headers=headers,
                        content=serialized 
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