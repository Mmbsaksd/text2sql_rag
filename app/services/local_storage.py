"""
Local filesystem storage backend (for development).

This module provides local file-based storage for document cache.
Use this during development for fast iteration without S3 costs.
"""

import json
import shutil
import logging
from pathlib import Path
from typing import Dict, List
import numpy as np
from app.services.storage_backend import StorageBackend
from app.config import settings

logger = logging.getLogger(__name__)

class LocalStorageBackground(StorageBackend):
    """
    Filesystem-based storage for local development.

    Stores files in: data/cached_chunks/{document_id}/
    Each document gets a folder with 4 files:
    - document.{ext} (original file)
    - chunks.json
    - embeddings.npy
    - metadata.json

    For local development, we don't organize by document type (simpler).
    """

    def __init__(self, cache_dir: Path = None):
        """
        Initialize local storage with cache directory.

        Args:
            cache_dir: Path to cache directory (defaults to settings.CACHE_DIR)
        """
        self.cache_dir = cache_dir or Path(settings.CACHE_DIR)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"LocalStorage initialized with cache_dir: {self.cache_dir}")

    def _get_document_path(self, document_id: str)->Path:
        """
        Get the folder path for a document.

        Args:
            document_id: SHA-256 hash of document

        Returns:
            Path to document folder
        """
        return self.cache_dir / document_id
    
    def exists(self, document_id: str, file_extention: str)->bool:
        """
        Check if all cache files exist for this document.

        Note: We check for chunks, embeddings, and metadata.
        Original document is optional (backward compatibility with existing cache).

        Args:
            document_id: SHA-256 hash of document
            file_extension: File extension (not used in local storage, but kept for interface compatibility)

        Returns:
            True if all required cache files exist
        """
        doc_path = self._get_document_path(document_id)

        required_files = [
            doc_path / "chunks.json",
            doc_path / "embeddings.npy",
            doc_path / "metadata.json"
        ]
        exists = all(f.exists() for f in required_files)

        if self.exists:
            logger.debug(f"Cache hit for document {document_id}")
        else:
            logger.debug(f"Cache miss for document {document_id}")
        
        return exists
    
    def save_document(self, document_id: str, file_path: Path, file_extension: str)-> None:
        """
        Save original document to local storage.

        Args:
            document_id: SHA-256 hash of document
            file_path: Path to the uploaded file
            file_extension: File extension (pdf, txt, md, etc.)
        """
        doc_path = self._get_document_path(document_id)
        doc_path.mkdir(parents=True, exist_ok=True)

        destination = doc_path / f"document.{file_extension}"
        shutil.copy2(file_path, destination)

        logger.info(f"Saved original document to {destination}")

    def save_chunks(self, document_id: str, file_extension: str, chunks: List[Dict])-> None:
        """
        Save chunks.json to local storage.

        Args:
            document_id: SHA-256 hash of document
            file_extension: File extension (not used, kept for interface)
            chunks: List of document chunks
        """
        doc_path = self._get_document_path(document_id)
        doc_path.mkdir(parents=True, exist_ok=True)

        chunks_file = doc_path / "chunks.json"

        with open(chunks_file, "w") as f:
            json.dump(chunks, f, indent=2)
        
        logger.debug(f"Saved {len(chunks)} chunks to {chunks_file}")