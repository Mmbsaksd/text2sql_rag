from fastapi import FastAPI
from app.config import settings
from app.logging_config import setup_logging

logger = setup_logging()

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0"
)

@app.on_event("startup")
async def startup_event():
    logger.info(f"Starting {settings.APP_NAME}")
    logger.info(f"Environment: {settings.APP_ENV}")
    logger.info(f"storage backend: {settings.STORAGE_BACKEND}")
    logger.info("Application startup complete")

@app.get("/health")
async def health_check():
    return{
        "status":"healthy",
        "app":settings.APP_NAME,
        "environment":settings.APP_ENV
    }