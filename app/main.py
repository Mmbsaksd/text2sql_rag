"""
Multi-Source RAG + Text-to-SQL API
FastAPI application with document RAG and natural language to SQL capabilities.
"""

from typing import Optional
from fastapi import FastAPI, status, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from datetime import datetime
from pathlib import Path
import sys
import shutil

from app.config import settings
from app.logging_config import setup_logging, get_logger
from app.services.document_service import parse_document, chunk_text
from app.services.embedding_service import EmbeddingService
from app.services.vector_service import VectorService
from app.services.rag_service import RAGService
from app.services.sql_service import TextToSQLService
from app.services.router_service import QueryRouter
from app.services.cache_service import CacheService
from app.services.query_cache_service import QueryCacheService
from app.utils import (
    FileValidator, QueryValidator, ValidationError,
    ErrorResponse, format_file_size, truncate_text
)

logger = setup_logging(log_level="INFO")

try:
    from opik import track
    OPIK_AVAILABLE=True
except ImportError:
    OPIK_AVAILABLE=False
    def track(name=None, **kwargs):
        def decorator(func):
            return func
        return decorator

app = FastAPI(
    title="Multi-Source RAG + Text-to-SQL API",
    description="A system that combines document RAG with natural language to SQL conversion",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    root_path=settings.ROOT_PATH,  # For API Gateway: "/prod", for local: ""
)
embedding_service: EmbeddingService | None = None
vector_service: VectorService | None = None
rag_service: RAGService | None = None
sql_service: TextToSQLService | None = None
cache_service: CacheService | None = None
query_cache_service: QueryCacheService | None = None

UPLOAD_DIR = Path(settings.UPLOAD_DIR)
CACHE_DIR = Path(settings.CACHE_DIR)


@app.get("/health", status_code=status.HTTP_200_OK)
def health_check():
    """
    Health check endpoint to verify the API is running and check service connectivity.

    Returns:
        dict: Status information including timestamp, service state, and connectivity checks
    """
    global embedding_service, vector_service, rag_service, sql_service, query_cache_service

    services_status = {
        "embedding_service": embedding_service is not None,
        "vector_service": vector_service is not None,
        "rag_service": rag_service is not None,
        "sql_service": sql_service is not None,
        "query_cache": query_cache_service is not None
    }
    any_service_available = any(services_status.values())
    health_status = "healthy" if any_service_available else "degraded"

    return {
        "status": health_status,
        "service": "Multi-Source RAG + Text-to-SQL API",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "0.1.0",
        "services": services_status,
        "feature_available":  {
            "azure_openai_configured": (
                settings.USE_AZURE_OPENAI
                and settings.AZURE_OPENAI_API_KEY is not None
                and settings.AZURE_OPENAI_ENDPOINT is not None
                and settings.AZURE_OPENAI_API_VERSION is not None
                and settings.AZURE_OPENAI_DEPLOYMENT_NAME is not None
                and settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME is not None
            ),
            "openai_configured": (
                not settings.USE_AZURE_OPENAI
                and settings.OPENAI_API_KEY is not None
            ),
            "pinecone_configured": settings.PINECONE_API_KEY is not None,
            "database_configured": settings.DATABASE_URL is not None,
            "opik_configured": settings.OPIK_API_KEY is not None if hasattr(settings, 'OPIK_API_KEY') else False,
            "redis_cache_configured": settings.UPSTASH_REDIS_REST_URL is not None and settings.UPSTASH_REDIS_REST_TOKEN is not None,
        },
        "cache": query_cache_service.health_check() if query_cache_service else {"status": "not_initialized"},

    }

@app.get("/info", status_code=status.HTTP_200_OK, tags=["Information"])
async def get_info():
    """
    Get system information and configuration details.

    Returns:
        dict: System information including Python version, environment, and features
    """
    return {
        "application": {
            "name": "Multi-Source RAG + Text-to-SQL",
            "version": "0.1.0",
            "environment": "development",  # Will be loaded from settings once .env exists
        },
        "features": {
            "document_rag": "Available - Phase 1 Complete",
            "text_to_sql": "Available - Phase 2 Complete",
            "query_routing": "Available - Phase 3 Complete",
            "evaluation_monitoring": "Available - Phase 4 Complete",
            "polish_documentation": "Available - Phase 5 Complete",
            "docker_deployment": "Available - Phase 6 Complete",
        },
        "deployment": {
            "docker": "Ready - Use docker-compose up",
            "dockerfile": "Multi-stage build optimized",
            "health_checks": "Enabled",
            "volumes": ["uploads", "vanna_chromadb"]
        },
        "system": {
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        },
                "endpoints": {
            "docs": "/docs",
            "redoc": "/redoc",
            "health": "/health (enhanced with service checks)",
            "info": "/info",
            "stats": "/stats (system statistics)",
            "unified_query": "POST /query (recommended - intelligent routing)",
            "upload_document": "POST /upload (with validation)",
            "query_documents": "POST /query/documents (with validation)",
            "list_documents": "GET /documents",
            "generate_sql": "POST /query/sql/generate",
            "execute_sql": "POST /query/sql/execute",
            "pending_sql_queries": "GET /query/sql/pending",
        },

    }
@app.get("/",tags=["Root"])
async def root():
    """
    Root endpoint with welcome message and quick links.

    Returns:
        dict: Welcome message and navigation links
    """
    return {
        "message": "Welcome to Multi-Source RAG + Text-to-SQL API",
        "version": "0.1.0",
        "status": "Phase 0 Complete - Development Ready",
        "documentation": "/docs",
        "health_check": "/health",
        "system_info": "/info",
    }

@app.post("/upload", status_code=status.HTTP_200_OK, tags=["Documents"])
@track(name="upload_name")
async def upload_documents(file: UploadFile=File(...)):
    """
    Upload and process a document (PDF, DOCX, CSV, JSON, TXT).
    Pipeline: validate → save → [cache check] → parse → chunk → embed → cache → store

    NEW: Implements intelligent caching to avoid re-processing identical documents.

    Args:
        file: The document file to upload (max 50 MB)

    Returns:
        dict: Upload status with filename, chunks created, and cache_hit indicator

    Raises:
        HTTPException: If validation fails or services unavailable
    """
    try:
        FileValidator.validate_file(file)
    except ValidationError as e:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse.validation_error(str(e), field="fie")
        )
    
    if not embedding_service or not vector_service:
        raise HTTPException(
            status_code=503,
            detail=ErrorResponse.service_unavailable(
                "Document RAG services",
                "Please configure Azure_OPENAI_API_KEY and PINECONE_API_KEY in .env"
            )
        )
    try:
        file_path = UPLOAD_DIR / file.filename
        with open(file_path,"wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        file_extention = file_path.suffix.lstrip('.').lower()

        doc_id = None
        cache_hit = False
        chunks = None
        embeddings = None

        if cache_service:
            try:
                doc_id = cache_service.compute_document_id(file_path)
                logger.info(f"Document ID computed: {doc_id}")

                if cache_service.cache_exists(doc_id, file_extention):
                    logger.info(f"Cache HIT for document: {file.filename} (ID: {doc_id[:8]}...)")

                    cache_data = cache_service.load_chunks_and_embeddings(doc_id, file_extention)

                    if cache_data:
                        chunks = cache_data['chunks']
                        embeddings = cache_data['embeddings']
                        cache_hit=True
                        logger.info("Loaded {len(chunks)} chunks from cache, skipping processing")
                    else:
                        logger.warning("Cache load failed, falling back to full processing")
                    
                else:
                    logger.info(f"Cache MISS for document: {file.filename} (ID: {doc_id[:8]}...)")

            except Exception as e:
                logger.warning(f"Cache check failed, proceeding with full processing: {e}")

        if chunks is None or embeddings is None:
            logger.info(f"Parsing and chunking document with context awareness: {file.filename}")
            from app.services.docling_service import parse_and_chunk_document
            chunks = parse_and_chunk_document(
                str(file_path),
                chunk_size=settings.CHUNK_SIZE,
                min_chunk_size=settings.MIN_CHUNK_SIZE
            )
            logger.info(f"Created {len(chunks)} context-aware chunks (target {settings.MIN_CHUNK_SIZE}-{settings.CHUNK_SIZE} tokens)")

            logger.info(f"Generating embeddings for {len(chunks)} chunks...")
            texts = [chunk['text'] for chunk in chunks]

            embeddings, embedding_usage = await embedding_service.generate_embeddings(texts)
            if cache_service and doc_id:
                try:
                    cache_service.save_document(
                        doc_id=doc_id,
                        file_path=file_path,
                        file_extension=file_extention
                    )
                    logger.info(f"Saved original document to storage: {doc_id}")

                    metadata = {
                        "document_id": doc_id,
                        "original_filename": file.filename,
                        "upload_timestamp": datetime.utcnow().isoformat()+"Z",
                        "file_size_bytes": file_path.stat().st_size,
                        "chunk_count": len(chunks),
                        "embedding_model": "text-embedding-3-small",
                        "chunk_size": settings.CHUNK_SIZE,
                        "chunk_overlap": settings.CHUNK_OVERLAP,
                        "file_extention": file_extention
                    }
                    cache_service.save_chunks_and_embeddings(
                        doc_id=doc_id,
                        file_extension=file_extention,
                        chunks=chunks,
                        embeddings=embeddings,
                        metadata=metadata
                    )
                    logger.info(f"Saved cache data (chunks, embeddings, metadata): {doc_id}")

                except Exception as e:
                    logger.warning(f"Failed to save to cache (continuing anyway): {e}")
        logger.info(f"Storing {len(chunks)} vectors in Pinecone...")
        vector_service.add_documents(
            chunks=chunks,
            embeddings=embeddings,
            filename=file.filename,
            namespace="default"
        )
        if not cache_hit and query_cache_service and query_cache_service.enabled:
            try:
                deleted = query_cache_service.delete("rag:*")
                if deleted >0:
                    logger.info(f"✓ Invalidated RAG cache ({deleted} keys) due to new document upload")
                else:
                    logger.debug("No RAG cache keys to invalidate")
            except Exception as e:
                logger.warning(f"Failed to invalidate RAG cache (continuing anyway): {e}")
        file_size = file_path.stat().st_size
        total_token = sum(chunk['token_count'] for chunk in chunks)
 
        if OPIK_AVAILABLE:
            try:
                from opik.opik_context import update_current_span
                update_current_span(
                    tags=[
                        "document_upload",
                        f"extension_{file_extention}",
                        "cache_hit" if cache_hit else "cache_miss"
                    ],
                    metadata={
                        "filename": file.filename,
                        "file_size_bytes": file_size,
                        "file_size_human": format_file_size(file_size),
                        "file_extension": file_extention,
                        "chunk_count": len(chunks),
                        "total_tokens": total_token,
                        "cache_hit": cache_hit
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to update OPIK span: {e}")
        storage_backend = "none"
        if cache_service:
            storage_class = type(cache_service.storage).__name__
            if "S3" in storage_class:
                storage_backend = "s3"
            elif "Local" in storage_class:
                storage_backend = "local"
            else:
                storage_backend = storage_class.lower()
 
        return {
            "status": "success",
            "filename": file.filename,
            "document_id": doc_id[:16] + "..." if doc_id else None,  # Show first 16 chars
            "file_size": format_file_size(file_size),
            "file_size_bytes": file_size,
            "chunks_created": len(chunks),
            "total_tokens": total_token,
            "cache_hit": cache_hit,  # NEW: Indicate if cache was used
            "storage_backend": storage_backend,  # NEW: Report storage backend
            "message": (
                f"Document loaded from cache and {len(chunks)} chunks stored in Pinecone"
                if cache_hit
                else f"Document processed and {len(chunks)} chunks stored in Pinecone"
            )
        }
 
    except ValidationError as e:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse.validation_error(str(e))
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse.internal_error("upload document", e)
        )

@app.post("/query/documents", status_code=status.HTTP_200_OK, tags=["Query"])
@track(name="query_documents", type="llm")
async def query_documents(question: str, top_k: int = 3):
    """
    Query documents using RAG (Retrieval-Augmented Generation).
    Retrieves relevant chunks and generates an answer using GPT-4.

    Args:
        question: The question to answer (3-1000 characters)
        top_k: Number of document chunks to retrieve (1-10, default: 3)

    Returns:
        dict: Generated answer with sources and metadata

    Raises:
        HTTPException: If validation fails or service unavailable
    """
    global rag_service

    try:
        question = QueryValidator.validate_question(question)
        top_k = QueryValidator.validate_top_k(top_k)
    except ValidationError as e:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse.validation_error(str(e))
        )
    
    if not rag_service:
        raise HTTPException(
            status_code=503,
            detail=ErrorResponse.service_unavailable(
                "RAG service",
                "Please configure OPENAI_API_KEY and PINECONE_API_KEY in .env"
            )
        )
    
    try:
        result = await rag_service.generate_answer(
            question=question,
            top_k=top_k,
            namespace="default",
            include_sources=True
        )
        if OPIK_AVAILABLE:
            try:
                from opik.opik_context import update_current_span
                usage_data = result.get('usage')

                span_update = {
                    "tags": ["document_query", f"top_k_{top_k}"],
                    "metadata": {
                        "question_length": len(question),
                        "top_k": top_k,
                        "chunks_retrieved": result.get('chunks_used', 0),
                        "model": result.get('model', 'unknown')
                    },
                    "model": "gpt-4-turbo-preview",
                    "provider": "openai"
                }
                if usage_data:
                    span_update["usage"] = {
                        "prompt_tokens": usage_data['embedding_tokens'] + usage_data['llm_prompt_tokens'],
                        "completion_tokens": usage_data['llm_completion_tokens'],
                        "total_tokens": usage_data['total_tokens']
                    }
                
                update_current_span(**span_update)

            except Exception as e:
                logger.warning(f"Failed to update OPIK span: {e}")

        return result
    
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse.internal_error("query documents", e)
        )
    
@app.get("/documents", status_code=status.HTTP_200_OK, tags=["Documents"])
async def list_documents():
    """
    List all uploaded documents.

    Returns:
        dict: List of uploaded documents with metadata
    """
    try:
        documents = []
        for file_path in UPLOAD_DIR.iterdir():
            if file_path.is_file() and not file_path.name.startswith('.'):
                documents.append({
                    "filename": file_path.name,
                    "size_bytes": file_path.stat().st_size,
                    "upload_at": datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()
                })
        return {
            "total_documents": len(documents),
            "documents": documents
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list documents: {str(e)}")

@app.get("/stats", status_code=status.HTTP_200_OK, tags=["Information"])
async def get_stats():
    """
    Get system statistics and usage information.

    NEW: Includes query cache statistics and cost savings estimates.

    Returns:
        dict: Statistics including document count, total size, service status, and cache performance
    """
    global sql_service, query_cache_service

    try:
        total_size = 0
        documents = []
        for file_path in UPLOAD_DIR.iterdir():
            if file_path.is_file() and not file_path.name.startswith('.'):
                file_size = file_path.stat().st_size
                documents.append({
                    "filename": file_path.name,
                    "size_bytes": file_size
                })
                total_size +=file_size

        pending_sql_count = 0
        if sql_service:
            try:
                pending_sql_count = len(sql_service.get_pending_queries())
            except Exception as e:
                pass

        cache_stats = None
        total_cost_saved = 0.0
        if query_cache_service and query_cache_service.enabled:
            try:
                stats = query_cache_service.get_stats()
                cost_estimates = {
                    "rag": 0.05, 
                    "embedding": 0.00002, 
                    "sql_gen": 0.08, 
                    "sql_result": 0.01,
                }

                for cache_type, cache_data in stats["cache_types"].items():
                    if cache_type in cost_estimates:
                        savings = cache_data["hits"] * cost_estimates[cache_type]
                        cache_data["estimated_cost_saved"] = f"${savings:.4f}"
                        total_cost_saved +=savings

                cache_stats = {
                    "enabled": True,
                    "by_type": stats["cache_types"],
                    "total_estimated_savings": f"${total_cost_saved:.4f}",
                    "overall_hit_rate": f"{(sum(c['hits'] for c in stats['cache_types'].values()) / max(sum(c['total_queries'] for c in stats['cache_types'].values()), 1) * 100):.1f}%"
                }
                
            except Exception as e:
                logger.warning(f"Failed to get query cache stats: {e}")
                cache_stats = {"enabled": True, "error": "Failed to retrieve stats"}

        else:
            cache_stats = {
                "enabled": False,
                "message":  "Query cache not configured (set UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN to enable)"
            }

        return {
            "documents": {
                "total_uploaded": len(documents),
                "total_size": format_file_size(total_size),
                "total_size_bytes": total_size,
            },
            "sql": {
                "pending_queries": pending_sql_count,
                "service_available": sql_service is not None,
            },
            "query_cache": cache_stats, 
            "system": {
                "uptime_checked_at": datetime.utcnow().isoformat(),
                "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            },
            "configuration": {
                "chunk_size": settings.CHUNK_SIZE,
                "chunk_overlap": settings.CHUNK_OVERLAP,
                "max_file_size": format_file_size(FileValidator.MAX_FILE_SIZE),
                "cache_ttl": {
                    "rag": f"{settings.CACHE_TTL_RAG}s",
                    "embeddings": f"{settings.CACHE_TTL_EMBEDDINGS}s",
                    "sql_generation": f"{settings.CACHE_TTL_SQL_GEN}s",
                    "sql_results": f"{settings.CACHE_TTL_SQL_RESULT}s"
                } if query_cache_service and query_cache_service.enabled else "disabled"
            }

        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse.internal_error("get statistics", e)
        )
    
@app.get("/cache/stats", status_code=status.HTTP_200_OK, tags=["Cache"])
async def get_cache_stats():
    """
    Get cache statistics (total documents, size, etc.).

    Returns:
        dict: Cache statistics including document count and total size
    """
    global cache_service

    if not cache_service:
        raise HTTPException(
            status_code=503,
            detail=ErrorResponse.service_unavailable(
                "Cache service",
                "Cache service not initialized"
            )
        )
    try:
        stats = cache_service.get_cache_stats()
        return{
            "status": "success",
            "cache_stats": stats,
            "message": f"Cache contains {stats['total_documents']} documents"
        }
    
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse.internal_error("get cache stats", e)
        )
    
@app.delete("/cache/clear", status_code=status.HTTP_200_OK, tags=["Cache"])
async def clear_cache(document_id: Optional[str] = None):
    """
    Clear cache for specific document or entire cache.

    Clears BOTH:
    - S3 document cache (chunks, embeddings, metadata)
    - Redis query cache (RAG responses, SQL queries, embeddings)

    Args:
        document_id: Optional document ID to clear (if not provided, clears all cache)

    Returns:
        dict: Result of cache clearing operation
    """
    global cache_service, query_cache_service

    if not cache_service:
        raise HTTPException(
            status_code=503,
            detail=ErrorResponse.service_unavailable(
                "Cache service",
                "Cache service not initialized"
            )
        )
    
    try:
        s3_result = cache_service.clear_cache(doc_id=document_id)

        redis_cleared = False
        redis_message = "Redis cache not enabled"

        if not document_id and query_cache_service and query_cache_service.enabled:
            try:
                redis_cleared = query_cache_service.flush_all()
                redis_message = "Redis cache cleared successfully" if redis_cleared else "Redis flush failed"
            except Exception as e:
                redis_message = f"Redis flush error: {str(e)}"

        return {
            "status": "success" if s3_result['cleared'] else "failed",
            "s3_cache": s3_result,
            "redis_cache": {
                "cleared": redis_cleared,
                "message": redis_message
            }
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse.internal_error("clear cache", e)
        )
    
@app.get("/cache/query/stats", status_code=status.HTTP_200_OK, tags=["Query Cache"])
async def get_query_cache_stats():
    """
    Get query cache statistics (hit rates, cache effectiveness).

    NEW: Query-level cache statistics showing cache hit rates for:
    - RAG responses (GPT-4 calls)
    - Embeddings (OpenAI embedding API)
    - SQL generation (GPT-4o calls)
    - SQL results (database queries)

    Returns:
        dict: Cache statistics including hit rates and potential cost savings
    """
    global query_cache_service
    if not query_cache_service:
        raise HTTPException(
            status_code=503,
            detail=ErrorResponse.service_unavailable(
                "Query cache service",
                "Query cache service not initialized"
            )
        )
    try:
        stats = query_cache_service.get_stats()
        cost_estimates = {
            "rag": 0.05,  # $0.05 per GPT-4 call
            "embedding": 0.00002,  # $0.00002 per embedding
            "sql_gen": 0.08,  # $0.08 per GPT-4o call
            "sql_result": 0.01,  # $0.01 average database query cost
        }
        total_savings = 0
        if stats["enabled"]:
            for cache_type, cache_stats in stats["cache_types"].items():
                if cache_type in cost_estimates:
                    savings = cache_stats["hits"]*cost_estimates[cache_type]
                    cache_stats["estimated_cost_saved"] = f"${savings:.4f}"
                    total_savings +=savings

        return {
            "status": "success",
            "cache_stats": stats,
            "total_estimated_savings": f"${total_savings:.4f}",
            "message": "Query cache enabled" if stats["enabled"] else "Query cache disabled"
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse.internal_error("get query cache stats", e)
        )
    
@app.delete("/cache/query", status_code=status.HTTP_200_OK, tags=["Query Cache"])
async def clear_query_cache(cache_type: Optional[str]=None):
    """
    Clear query cache (all types or specific type).

    Args:
        cache_type: Optional cache type to clear ("rag", "embedding", "sql_gen", "sql_result")
                   If not provided, clears all query caches

    Returns:
        dict: Result of cache clearing operation

    Examples:
        - DELETE /cache/query → Clear all query caches
        - DELETE /cache/query?cache_type=rag → Clear only RAG response cache
        - DELETE /cache/query?cache_type=sql_gen → Clear only SQL generation cache
    """
    global query_cache_service

    if not query_cache_service:
        raise HTTPException(
            status_code=503,
            detail=ErrorResponse.service_unavailable(
                "Query cache service",
                "Query cache service not initialized"
            )
        )        
    if not query_cache_service.enabled:
        return {
            "status": "disabled",
            "message": "Query cache is not enabled (Redis not configured)"
        }
    
    try:
        if cache_type:
            valid_types = ["rag", "embedding", "sql_gen", "sql_result"]
            if cache_type not in valid_types:
                raise HTTPException(
                    status_code=400,
                    detail=ErrorResponse.validation_error(
                        f"Invalid cache_type. Must be one of: {', '.join(valid_types)}",
                        field="cache_type"
                    )
                )
            pattern = f"{cache_type}:*"
            message =  f"Cleared {cache_type} cache"
        else:
            patterns = ["rag:*", "embedding:*", "sql_gen:*", "sql_result:*"]
            total_deleted = 0
            for pattern in patterns:
                deleted = query_cache_service.delete(pattern)
                total_deleted +=deleted
            query_cache_service.reset_stats()
            return {
                "status": "success",
                "key_deleted": total_deleted,
                "message": f"Cleared all query caches ({total_deleted} keys deleted)"
            }
        deleted = query_cache_service.delete(pattern)
        return {
            "status": "success",
            "cache_type": cache_type,
            "keys_deleted": deleted,
            "message": message
        }

    except HTTPException as e:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse.internal_error("clear query cache", e)
        )
    
@app.delete("/vectors/clear", status_code=status.HTTP_200_OK, tags=["Vectors"])
async def clear_vectors(
    namespace: Optional[str] = "default",
    confirm: Optional[bool] = False
):
    """
    Clear all vectors from the Pinecone vector database.

    WARNING: This operation is irreversible! All document embeddings will be deleted.

    Parameters:
    - namespace: Namespace to clear (default: "default", use "*" for all namespaces)
    - confirm: Must be set to true to proceed (safety confirmation)

    Returns:
    - status: Operation status (success/failed)
    - namespaces_cleared: List of namespaces that were cleared
    - vector_count_before: Total vectors before deletion
    - vector_count_after: Total vectors after deletion
    - vectors_deleted: Number of vectors deleted
    - message: Human-readable status message

    Example:
        DELETE /vectors/clear?namespace=default&confirm=true
    """
    global vector_service

    if not confirm:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Confirmation required",
                "message": "You must set confirm=true to clear vectors. This operation cannot be undone!",
                "example": "/vectors/clear?namespace=default&confirm=true"
            }

        )
    
    if not vector_service:
        raise HTTPException(
            status_code=503,
            detail=ErrorResponse.service_unavailable(
                "Vector database not initialized. Check PINECONE_API_KEY configuration."
            )
        )
    try:
        stats_before = vector_service.get_index_stats()
        total_vectors_before = stats_before.get('total_vector_count', 0)

        logger.warning(
            f"Vector clear requested: namespace={namespace}, "
            f"total_vectors={total_vectors_before}"
        )

        result = vector_service.delete_all_vectors(namespace=namespace)

        stats_after = vector_service.get_index_stats()
        total_vectors_after = stats_after.get('total_vector_count', 0)

        response = {
            "status": result['status'],
            "namespace_cleared": result['namespaces_cleared'],
            "vector_counts_before": total_vectors_before,
            "vector_counts_after": total_vectors_after,
            "vectors_deleted": total_vectors_before - total_vectors_after,
            "message": result['message']
        }
        logger.info(
            f"Vector clear completed: {response['vectors_deleted']} vectors deleted "
            f"from {len(result['namespaces_cleared'])} namespace(s)"
            )
        
        return response
    
    except Exception as e:
        logger.error(f"Vector clear failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse.internal_error("clear_vectors", e)
        )
    
@app.post("/query", status_code=status.HTTP_200_OK, tags=["Query"])
@track(name="unified_query")














def initialize_services():
    """Initialize all services. Called directly on Lambda startup or via FastAPI startup event."""
    global embedding_service, vector_service, rag_service, sql_service, cache_service, query_cache_service

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    logger.info(f"Storage directories initialized: {UPLOAD_DIR}, {CACHE_DIR}")

    logger.info("=" * 60)
    logger.info("Starting Multi-Source RAG + Text-to-SQL API...")
    logger.info("=" * 60)
    logger.info("Phase 0: Foundation Setup - COMPLETE")
    logger.info("Phase 1: Document RAG MVP - COMPLETE")
    logger.info("Phase 2: Text-to-SQL Foundation - COMPLETE")
    logger.info("Phase 3: Query Routing - COMPLETE")
    logger.info("Phase 4: Evaluation & Monitoring - COMPLETE")
    logger.info("Phase 5: Polish & Documentation - COMPLETE")
    logger.info("Phase 6: Docker Deployment - COMPLETE")
    logger.info("=" * 60)
    logger.info("ALL PHASES COMPLETE - PRODUCTION READY!")
    logger.info("=" * 60)

    if OPIK_AVAILABLE:
        try:
            if settings.OPENAI_API_KEY:
                logger.info("Initializing OPIK monitoring...")
                import os
                old_stdin = sys.stdin
                
                try:
                    devnull = open(os.devnull,'r')
                    sys.stdin = devnull
                    from opik import configure
                    configure(api_key=settings.OPENAI_API_KEY)
                    logger.info("✓ OPIK monitoring initialized!")
                finally:
                    sys.stdin = old_stdin
                    try:
                        devnull.close()
                    except:
                        pass
                
            else:
                logger.warning("OPIK available but API key not configured.")
                logger.info("Monitoring will use local tracking only.")
        except Exception as e:
            logger.warning(f"Failed to initialize OPIK: {e}")
    else:
        logger.info("OPIK not available (package not installed).")

    try:
        logger.info("Initializing query cache service (Redis)...")
        query_cache_service = QueryCacheService(
            redis_url=settings.UPSTASH_REDIS_REST_URL,
            redis_token=settings.UPSTASH_REDIS_REST_TOKEN
        )
        if query_cache_service.enabled:
            logger.info("✓ Query cache service initialized and connected!")
            logger.info(f"  Cache TTL: RAG={settings.CACHE_TTL_RAG}s, Embeddings={settings.CACHE_TTL_EMBEDDINGS}s, "
                    f"SQL Gen={settings.CACHE_TTL_SQL_GEN}s, SQL Results={settings.CACHE_TTL_SQL_RESULT}s")
        else:
            logger.info("Query cache service initialized but disabled (credentials not configured).")
            logger.info("App will continue without query caching. Set UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN to enable.")
    except Exception as e:
        logger.error(f"✗ Failed to initialize query cache service: {e}")
        logger.warning("Query caching will be unavailable but app will continue normally.")

    try:
        if settings.AZURE_OPENAI_API_KEY and settings.PINECONE_API_KEY:
            logger.info("Initializing Document RAG services...")

            embedding_service = EmbeddingService(query_cache_service=query_cache_service)
            vector_service = VectorService()
            vector_service.connect_to_index()
            rag_service = RAGService(query_cache_service=query_cache_service)
            logger.info("✓ Document RAG services initialized!")
        else:
            logger.warning("OpenAI/Pinecone API keys not configured.")
            logger.warning("Document RAG features will be unavailable.")

    except Exception as e:
        logger.error(f"Failed to initialize RAG services: {e}", exc_info=True)
        logger.warning("Document RAG features will be unavailable.")

    try:
        if settings.DATABASE_URL and settings.AZURE_OPENAI_API_KEY:
            logger.info("Initializing Text-to-SQL service...")
            sql_service = TextToSQLService(query_cache_service=query_cache_service)
            logger.info("Training Vanna on database schema and examples...")
            sql_service.complete_training()
            logger.info("✓ Text-to-SQL service initialized and trained!")
        else:
            logger.warning("DATABASE_URL not configured.")
            logger.warning("Text-to-SQL features will be unavailable.")
    except Exception as e:
        logger.error(f"Failed to initialize SQL service: {e}", exc_info=True)
        logger.warning("Text-to-SQL features will be unavailable.")

    try:
        logger.info("Initializing document cache service (S3/local)...")
        cache_service = CacheService()
        logger.info("✓ Document cache service initialized!")
    except Exception as e:
        logger.error(f"✗ Failed to initialize document cache service: {e}")
        logger.warning("Document uploads will work but caching will be unavailable.")

    logger.info("=" * 60)
    logger.info("API is ready!")
    logger.info("=" * 60)

@app.on_event("startup")
async def startup_event():
    """Execute tasks on application startup."""
    initialize_services()

app.on_event("shutdown")
async def shutdown_event():
    """Execute cleanup tasks on application shutdown."""
    logger.info("Shutting down Multi-Source RAG + Text-to-SQL API...")