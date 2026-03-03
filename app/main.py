from fastapi import FastAPI
from app.config import settings
from app.logging_config import setup_logging

from app.services.service_registry import registry
from app.services.database_service import DatabaseService
from app.services.pinecone_service import PineconeService
from app.services.redis_service import RedisService
from app.services.storage_service import StorageService
from app.services.embedding_service import EmbeddingService

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

    #Embeddings
    registry.embeddings = EmbeddingService(redis_service=registry.cache)
    logger.info("Embedding service ready")

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

@app.get("/test/embeddings")
async def test_embedding():
    text = "Hello, this is a test sentence."
    embedding = await registry.embeddings.get_embedding(text)
    return{
        "test": text,
        "embedding_length": len(embedding),
        "first_5_values": embedding[:5],
        "cached":False
    }

@app.get("/test/pinecone")
async def test_pinecone():
    stats_before = registry.vector_db.get_stats()

    test_text = "This is a test document chunk about sales revenue."
    embedding = await registry.embeddings.get_embedding(test_text)

    test_vector = [{
        "id": "test-vector-001",
        "values":embedding,
        "metadata": {
            "text": test_text,
            "document_id": "test-vector-001",
            "filename": "test.pdf",
            "chunk_index":0
        }
    }]

    upserted = registry.vector_db.upsert(test_vector)
    matches = registry.vector_db.query(embedding, top_k=1)
    registry.vector_db.deleted_by_document_id("test-vector-001")
    return{
        "stats_before":stats_before,
        "vectors_upserted": upserted,
        "query_matches": len(matches),
        "top_match_score": matches[0]["score"] if matches else None,
        "top_match_text": matches[0]["metadata"]["text"] if matches else None,
        "cleanup": "test vector deleted"
    }