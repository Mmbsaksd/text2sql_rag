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
    file_extension = Path(file_path).suffix.lower()
    if file_extension in ['.txt', '.md', '.csv', '.log', '.json']:
        try:
            logger.info(f"Using fast text read for {file_extension} file")
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except UnicodeDecodeError:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    return f.read()
            except Exception as e:
                logger.warning(f"Fast text read failed: {e}, falling back to unstructured")
        except Exception as e:
            logger.warning(f"Fast text read failed: {e}, falling back to unstructured")

    try:
        logger.info(f"Using unstructured library for {file_extension} file")
        elements = partition(
            filename=file_path,
            strategy="fast"
        )
        text = "\n\n".join([str(el) for el in elements])

        return text
    
    except Exception as e:
        raise Exception(f"Failed to parse document {file_path}: {str(e)}")

def chunk_text(
        text: str,
        chunk_size: int = 512,
        overlap: int = 50,
        encoding_name: str = "cl100k_base"
)-> List[Dict[str, Any]]:

    """
    Split text into overlapping chunks based on token count.

    Args:
        text: The text to chunk
        chunk_size: Maximum tokens per chunk (default: 512)
        overlap: Number of overlapping tokens between chunks (default: 50)
        encoding_name: Tokenizer encoding to use (default: cl100k_base for GPT-4)

    Returns:
        List of dictionaries containing:
            - text: The chunk text
            - chunk_index: Index of the chunk
            - token_count: Number of tokens in the chunk
            - start_char: Starting character position
            - end_char: Ending character position
    """
    try:
        tokenizer = tiktoken.get_encoding(encoding_name)
    except Exception:
        tokenizer = tiktoken.encoding_for_model("gpt-4")

    tokens = tokenizer.encode(text)

    chunk = []
    start_index = 0

    while start_index < len(tokens):
        end_index = min(start_index + chunk_size, len(tokens))
        chunk_token = tokens[start_index: end_index]

        chunk_text = tokenizer.decode(chunk_token)
