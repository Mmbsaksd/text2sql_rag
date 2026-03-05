from fastapi import FastAPI
from app.config import settings
from app.logging_config import setup_logging

from app.services.service_registry import registry
from app.services.database_service import DatabaseService
from app.services.pinecone_service import PineconeService
from app.services.redis_service import RedisService
from app.services.storage_service import StorageService
from app.services.embedding_service import EmbeddingService
from app.services.document_service import DocumentService   
from app.services.chunking_service import ChunkingService

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

    #Chunking
    chunking = ChunkingService(chunk_size=512, chunk_overlap=50)
    registry.documents = DocumentService(
        chunking_service=chunking,
        embedding_service=registry.embeddings,
        vector_service=registry.vector_db
    )
    logger.info("Document service ready")

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

@app.get("/test/chunking")
async def test_chunking():
    from app.services.chunking_service import ChunkingService
    chunker = ChunkingService(chunk_size=50, chunk_overlap=10)

    sample_text = """
    Artificial intelligence is transforming how businesses operate.
    Companies are leveraging machine learning models to automate repetitive tasks,
    analyze large datasets, and generate insights that were previously impossible.
    Natural language processing allows computers to understand human language,
    enabling applications like chatbots, document analysis, and automated reporting.
    The future of AI in business looks promising, with new tools emerging every year
    that make it easier for non-technical users to benefit from these technologies.
    Organizations that invest in AI capabilities today will have a significant
    competitive advantage over those that delay adoption.
    """ * 3

    chunks = chunker.chunk_text(sample_text, metadata={"filename": "test.pdf", "page_number": 1})
  
    return {
      "total_chunks": len(chunks),
      "chunk_size_setting": 50,
      "overlap_setting": 10,
      "chunks_preview": [
          {
              "chunk_index": c["chunk_index"],
              "word_count": c["word_count"],
              "text_preview": c["text"][:80] + "..."
              }
              for c in chunks
      ]
  }
@app.post("/test/document")
async def test_document_upload():
    """Test document processing with a synthetic text document."""
    sample_content = (
        "Q3 Financial Report Summary. "
        "Total revenue for Q3 reached 4.2 million dollars, "
        "representing a 15 percent increase over Q2. "
        "The sales team closed 142 new enterprise deals. "
        "Customer retention rate improved to 94 percent. "
        "Operating expenses were reduced by 8 percent through process automation. "
        "The product team shipped 3 major feature releases. "
        "Net promoter score increased from 42 to 67. "
        "Headcount grew from 85 to 112 employees. "
        "Cash reserves stand at 8.1 million dollars. "
        "Q4 forecast projects 4.8 million in revenue. "
    ) * 5 
    file_bytes = sample_content.encode("utf-8")

    result = await registry.documents.process_upload(
        file_bytes=file_bytes,
        filename ="q3_report.txt",
        content_type="text/plain"
    )
    return result