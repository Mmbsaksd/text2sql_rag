from fastapi import FastAPI
from app.config import settings
from app.logging_config import setup_logging

from app.services.service_registry import registry
from app.services.database_service import DatabaseService
from app.services.pinecone_service import PineconeService
from app.services.redis_service import RedisService
from app.services.storage_service import StorageService

logger = setup_logging()

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0"
)

@app.on_event("startup")
async def startup_event():
    logger.info("Initializing services...")

    #Database
    registry.database = DatabaseService()
    await registry.database.connect()
    logger.info("Database connected")

    #Pinecone
    registry.vector_db = PineconeService()
    registry.vector_db.connect()
    logger.info("Pinecone connected")

    # Redis
    registry.cache = RedisService()
    logger.info("Redis service ready")

    # Storage
    registry.storage = StorageService()
    logger.info(f"Storage backend: {settings.STORAGE_BACKEND}")

    logger.info("Application startup complete")

@app.on_event("shutdown")
async def shutdown_event():
    if registry.database:
        await registry.database.disconnect()
        logger.info("Database disconnected")



@app.get("/health")
async def health_check():
    db_status = await registry.database.health_check()
    redis_status = await registry.cache.health_check()
    pinecone_status = registry.vector_db.health_check()

    return{
        "status":"healthy",
        "database":db_status,
        "pinecone":pinecone_status,
        "redis": redis_status,
        "storage": settings.STORAGE_BACKEND
    }