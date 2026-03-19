"""
Docling Service
Provides context-aware document parsing and chunking using Docling's HybridChunker.
Preserves document structure and hierarchical heading context for better RAG quality.
"""

import logging
from typing import List, Dict, Any
from pathlib import Path

logger = logging.getLogger("rag_app.docling_service")

try:
    from docling.document_converter import DocumentConverter
    from docling.chunking import HybridChunker
    from docling_core.transforms.chunker.tokenizer.openai import OpenAITokenizer
    DOCLING_AVAILABLE = True
except Exception as e:
    logger.warning(f"Docling not available: {e}")
    DOCLING_AVAILABLE = False


def convert_document(file_path: str):
    """
    Convert document using Docling's advanced layout analysis.

    Args:
        file_path: Path to the document file

    Returns:
        DoclingDocument: Structured document with hierarchy preserved

    Raises:
        ImportError: If Docling is not installed
        Exception: If conversion fails
    """
    if not DOCLING_AVAILABLE:
        raise ImportError("Docling is not installed. Run: pip install docling docling-core")
    
    if not Path(file_path).exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    
    try:
        logger.info(f"Converting document with Docling: {Path(file_path).name}")
        converter = DocumentConverter()
        result = converter.convert(file_path)
        doc = result.document

        logger.info(f"Document converted successfully: {len(doc.texts)} text elements")
        return doc
    
    except Exception as e:
        logger.error(f"Docling conversion failed: {str(e)}")
        raise Exception(f"Failed to convert document with Docling: {str(e)}")
    

    
def chunk_with_hybrid(doc, max_tokens: int =512, min_tokens: int =256) -> List[Dict[str, Any]]:
    """
    Chunk document using HybridChunker with context awareness.

    Uses OpenAI tokenizer (tiktoken) for consistency with existing embeddings.
    Preserves hierarchical heading context and semantic boundaries.
    Post-processes to merge small chunks for better RAG context.

    Args:
        doc: DoclingDocument from convert_document()
        max_tokens: Maximum tokens per chunk (default: 512)
        min_tokens: Minimum tokens per chunk - smaller chunks will be merged (default: 256)

    Returns:
        List of chunk dictionaries with rich metadata:
            - text: The chunk text
            - chunk_index: Sequential index
            - token_count: Actual token count
            - start_char: Starting character position
            - end_char: Ending character position
            - headings: List of hierarchical headings (e.g., ["Chapter 1", "Section 1.2"])
            - page_numbers: List of page numbers this chunk spans
            - doc_items: References to original document items
            - captions: Table/figure captions if applicable
    """
    if not DOCLING_AVAILABLE:
        raise ImportError(
            "Docling is not installed. Run: pip install docling docling-core"
        )
    try:
        import tiktoken
        tiktoken_encoder = tiktoken.get_encoding("cl100k_base")

        tokenizer = OpenAITokenizer(
            tokenizer=tiktoken_encoder,
            max_tokens=max_tokens
        )

        chunker = HybridChunker(
            tokenizer=tokenizer,
            max_tokens=max_tokens,
            merge_peers=True
        )

        logger.info(f"Chunking with HybridChunker (max_tokens={max_tokens}, merge_peers=True)")
    except Exception as e:
        logger.error(f"HybridChunker failed: {str(e)}")
        raise Exception(f"Failed to chunk document with HybridChunker: {str(e)}")