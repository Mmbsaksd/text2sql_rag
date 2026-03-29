"""
AWS S3 storage backend for Lambda deployment.

This stores documents in S3 organized by file type:
- s3://bucket/pdf/{hash}/document.pdf
- s3://bucket/pdf/{hash}/chunks.json
- s3://bucket/pdf/{hash}/embeddings.npy
- s3://bucket/pdf/{hash}/metadata.json

Why S3?
- AWS Lambda has ephemeral filesystem (only /tmp is writable)
- S3 provides persistent, durable storage
- Lambda can access S3 via IAM role (no credentials needed)
- ~200ms latency is acceptable for cache operations
"""

import json
import io
import logging
from pathlib import Path
from typing import Dict, List
import numpy as np
import boto3
from botocore.exceptions import ClientError
from botocore.config import Config
from app.services.storage_backend import StorageBackend
from app.config import settings

logger = logging.getLogger(__name__)

class S3StorageBackend(StorageBackend):
    """
    S3-based storage for production Lambda deployment.

    Organizes documents by type in S3:
    - pdf/{doc_id}/document.pdf, chunks.json, embeddings.npy, metadata.json
    - txt/{doc_id}/document.txt, chunks.json, embeddings.npy, metadata.json
    - markdown/{doc_id}/document.md, chunks.json, embeddings.npy, metadata.json

    Each document gets 4 files: original document + cache files.
    """

    def __init__(self, bucket_name: str = None):
        """
        Initialize S3 storage.

        Args:
            bucket_name: S3 bucket name (defaults to settings.S3_CACHE_BUCKET)

        Raises:
            ValueError if bucket doesn't exist
            PermissionError if access denied to bucket
        """
        self.bucket_name = bucket_name or settings.S3_CACHE_BUCKET
        self.region = settings.AWS_REGION

        boto_config = Config(
            region_name=self.region,
            retries={
                'max_attempts': 3,
                'mode': 'adaptive'
            }
        )
        self.s3_client = boto3.client('s3', config=boto_config)
        self._validate_bucket()

        logger.info(f"S3Storage initialized with bucket: {self.bucket_name} (region: {self.region})")

    def _validate_bucket(self)->None:
        """
        Check if S3 bucket exists and is accessible.

        Raises:
            ValueError if bucket doesn't exist
            PermissionError if access denied
        """
        try:
            pass
        except ClientError as e:
            error_code = e.response['Error']['Code']

            if error_code == '404':
                raise ValueError(f"S3 bucket '{self.bucket_name}' does not exist")
            elif error_code == '403':
                raise PermissionError(f"Access denied to S3 bucket '{self.bucket_name}'")
            raise

    def _get_s3_key(self, document_id: str, file_extension: str, filename: str)-> str:
        """
        Generate S3 key with folder structure.

        Pattern: {doc_type}/{doc_id}/{filename}

        Examples:
            pdf/abc123def456/document.pdf
            pdf/abc123def456/chunks.json
            txt/xyz789/document.txt

        Args:
            document_id: SHA-256 hash of document
            file_extension: File extension (pdf, txt, md, etc.)
            filename: File name (document.pdf, chunks.json, etc.)

        Returns:
            S3 key string
        """
        return f"{file_extension}/{document_id}/{filename}"
    
    def _object_exists(self, key: str)-> bool:
        """
        Check if S3 object exists (using HEAD request - doesn't download).

        Args:
            key: S3 object key

        Returns:
            True if object exists, False otherwise
        """
        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=key)
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                return False
            raise

    def exists(self, document_id: str, file_extension: str)->bool:
        """
        Check if ALL 4 files exist in S3 for this document.

        Returns True only if all files present (all-or-nothing).

        Args:
            document_id: SHA-256 hash of document
            file_extension: File extension (pdf, txt, md, etc.)

        Returns:
            True if all 4 files exist
        """
        required_files = [
            f"document.{file_extension}",
            "chunks.json",
            "embeddings.npy",
            "metadata.json"
        ]

        for filename in required_files:
            key = self._get_s3_key(document_id, file_extension, filename)
            if not self._object_exists(key):
                logger.debug(f"S3 cache miss for {document_id} (missing: {filename})")
                return False
            
        logger.debug(f"S3 cache hit for {document_id}")
        return True
    
    def save_document(self, document_id: str, file_path: Path, file_extension: str):
        """
        Upload original document to S3.

        Example: s3://bucket/pdf/{doc_id}/document.pdf

        Args:
            document_id: SHA-256 hash of document
            file_path: Path to the uploaded file
            file_extension: File extension (pdf, txt, md, etc.)

        Raises:
            Exception if upload fails
        """
        key = self._get_s3_key(document_id, file_extension, f"document.{file_extension}")
        try:
            with open(file_path, 'rb') as f:
                self.s3_client.put_object(
                    Bucket=self.bucket_name,
                    Key=key,
                    Body=f.read(),
                    ServerSideEncryption='AES256'
                )
            logger.info(f"Uploaded original document to S3: {key}")
        except Exception as e:
            logger.error(f"Failed to upload document to S3: {e}")
            raise

    def save_chunks(self, document_id: str , file_extension: str, chunks: List[Dict])-> None:
        """
        Save chunks to S3 as JSON.

        Example: s3://bucket/pdf/{doc_id}/chunks.json

        Args:
            document_id: SHA-256 hash of document
            file_extension: File extension
            chunks: List of document chunks

        Raises:
            Exception if upload fails
        """