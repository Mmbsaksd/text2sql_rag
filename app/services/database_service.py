import asyncpg
from app.config import settings

class DatabaseService:
    def __init__(self):
        self.pool = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(
            settings.DATABASE_URL
        )
    async def disconnect(self):
        if self.pool:
            await self.pool.close()
    
    async def health_check(self):
        async with self.pool.acquire() as conn:
            result = await conn.fetchval("SELECT 1")
            return result==1