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

        raw_chunks = list(chunker.chunk(dl_doc=doc))

        logger.info(f"Generated {len(raw_chunks)} raw semantic chunks, merging to target {min_tokens}-{max_tokens} tokens")

        merged_chunks = []
        current_merged = None

        for chunk in raw_chunks:
            token_count = len(tiktoken_encoder.encode(chunk.text))

            if current_merged is None:
                current_merged = chunk
            else:
                current_tokens = len(tiktoken_encoder.encode(current_merged.text))
                combined_tokens = current_tokens + token_count

                if current_tokens < min_tokens and combined_tokens < max_tokens:
                    current_merged.text = current_merged.text + "\n\n"+ chunk.text

                    if chunk.meta and chunk.meta.headings:
                        if not current_merged.meta.headings:
                            current_merged.meta.headings = []
                        
                        for h in chunk.meta.headings:
                            if h not in current_merged.meta.headings:
                                current_merged.meta.headings.append(h)
                    
                    if chunk.meta and chunk.meta.origin and hasattr(chunk.meta.origin, 'page_numbers'):
                        if chunk.meta.origin.page_numbers:
                            if not hasattr(current_merged.meta.origin, 'page_numbers') or not current_merged.meta.origin.page_numbers:
                                if current_merged.meta and current_merged.meta.origin:
                                    current_merged.meta.origin.page_numbers = []
                            
                            if current_merged.meta and current_merged.meta.origin and current_merged.meta.origin.page_numbers is not None:
                                for pn in chunk.meta.origin.page_numbers:
                                    if pn not in current_merged.meta.origin.page_numbers:
                                        current_merged.meta.origin.page_numbers.append(pn)
                else:
                    merged_chunks.append(current_merged)
                    current_merged = chunk
        if current_merged is not None:
            merged_chunks.append(current_merged)

        logger.info(f"After merging: {len(merged_chunks)} chunks (avg {sum(len(tiktoken_encoder.encode(c.text)) for c in merged_chunks) / len(merged_chunks):.1f} tokens)")

        result = []
        char_position = 0

        for idx, chunk in enumerate(merged_chunks):
            headings = []
            if chunk.meta and chunk.meta.headings:
                headings = [h.text for h in chunk.meta.headings if hasattr(h, 'text')]

            page_numbers = []
            if chunk.meta and chunk.meta.origin and hasattr(chunk.meta.origin, 'page_numbers'):
                page_numbers = chunk.meta.origin.page_numbers or []

            captions = []
            if chunk.meta and hasattr(chunk.meta, 'captions') and chunk.meta.captions:
                captions = [str(c) for c in chunk.meta.captions]

            doc_items = []
            if chunk.meta and hasattr(chunk.meta, 'doc_items') and chunk.meta.doc_items:
                doc_items = [str(item)[:100] for item in chunk.meta.doc_items[:3]]

            token_count = len(tiktoken_encoder.encode(chunk.text))

            chunk_text = chunk.text
            start_char = char_position
            end_char = start_char + len(chunk_text)
            char_position = end_char

            chunk_data = {
                'text': chunk_text,
                'chunk_index': idx,
                'token_count':token_count,
                'start_char': start_char,
                'end_char': end_char,
                'headings': headings,
                'page_numbers': page_numbers,
                'doc_items': doc_items,
                'captions': captions,
            }
            result.append(chunk_data)

        if result:
            first_chunk = result[0]
            logger.info(f"Sample chunk metadata - Headings: {first_chunk['headings']}, Pages: {first_chunk['page_numbers']}")

        return result
    except Exception as e:
        logger.error(f"HybridChunker failed: {str(e)}")
        raise Exception(f"Failed to chunk document with HybridChunker: {str(e)}")
    
def parse_and_chunk_document(file_path: str, chunk_size: int = 512, min_chunk_size: int = 256):
    """
    Parse and chunk document using Docling's context-aware approach.

    This is the main entry point that replaces the old parse_document() + chunk_text() flow.

    Args:
        file_path: Path to the document file
        chunk_size: Maximum tokens per chunk (default: 512)
        min_chunk_size: Minimum tokens per chunk - smaller chunks will be merged (default: 256)

    Returns:
        List of chunk dictionaries with rich metadata

    Raises:
        Exception: If both Docling and fallback fail
    """

    if not DOCLING_AVAILABLE:
        logger.warning("Docling not available, cannot use context-aware chunking")
        raise ImportError("Docling is required for context-aware chunking. Run: pip install docling docling-core")
    
    try:
        doc = convert_document(file_path)
        chunks = chunk_with_hybrid(doc, max_tokens=chunk_size, min_tokens=min_chunk_size)
        logger.info(f"Successfully processed {Path(file_path).name}: {len(chunks)} chunks with context")
        return chunks
    
    except Exception as e:
        logger.error(f"Docling processing failed for {Path(file_path).name}: {str(e)}")
        raise Exception(f"Failed to process document with Docling: {str(e)}")
    
def fallback_to_unstructured(file_path: str, chunk_size: int = 512)-> List[Dict[str, Any]]:
    """
    Fallback to Unstructured.io for documents Docling cannot handle.

    This maintains compatibility but without context-aware chunking benefits.

    Args:
        file_path: Path to the document file
        chunk_size: Maximum tokens per chunk

    Returns:
        List of chunk dictionaries (without rich metadata)
    """
