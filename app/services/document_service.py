"""
Document Processing Service
Handles parsing and chunking of various document formats (PDF, DOCX, CSV, JSON).

Now supports context-aware chunking with Docling for improved RAG quality.
"""
from typing import List, Dict, Any
import tiktoken
import logging
from unstructured.partition.auto import partition
from pathlib import Path
from app.config import settings

logger = logging.getLogger("rag_app.document_service")

def parse_document(file_path: str)-> str:
    """
    Parse any document type and return extracted text.
    Uses fast direct read for simple text files (.txt, .md, .csv).
    Uses Unstructured.io for complex formats (PDF, DOCX, JSON, etc.).

    Args:
        file_path: Path to the document file

    Returns:
        str: Extracted text content from the document

    Raises:
        FileNotFoundError: If the file doesn't exist
        Exception: If parsing fails
    """
    if not Path(file_path).exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    file_extention = Path(file_path).suffix