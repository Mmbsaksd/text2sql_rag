"""
Vector Service
Handles vector storage and retrieval using Pinecone.
"""

from typing import List, Dict, Any
import logging
from pinecone.grpc import PineconeGRPC
from pinecone import ServerlessSpec
from app.config import settings

logger = logging.getLogger("rag_app.vector_service")

class VectorService:
    """Service for vector operations using Pinecone."""

    def __init__(self, api_key: str | None = None):
        """
        Initialize the vector service with Pinecone.

        Args:
            api_key: Pinecone API key (optional, uses settings if not provided)
        """
        self.api_key = api_key or settings.PINECONE_API_KEY
        if not self.api_key:
            raise ValueError("Pinecone API key is required. Set PINECONE_API_KEY in .env file.")
        
        self.environment = settings.PINECONE_ENVIRONMENT
        self.index_name = settings.PINECONE_INDEX_NAME