import uuid
import hashlib
import logging
import io
from pathlib import Path

logger = logging.getLogger("app")

SUPPORTED_TYPES = {
    "application/pdf": "pdf",
    "text/plain": "txt",
    "text/csv": "csv",
    "application/json": "json",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}
MAX_FILE_SIZE_MB = 50

class DocumentService:
    def __init__(self, chunking_service, embedding_service, vector_service):
        self.chunker = chunking_service
        self.embedder = embedding_service
        self.vector = vector_service
    # ------------------------------------------------------------------
    # MAIN METHOD — called by the /upload endpoint
    # ------------------------------------------------------------------

    async def process_upload(
            self, file_bytes: bytes, filename: str, content_type: str
    )-> dict:
        """
        Full pipeline: file bytes → chunks → embeddings → Pinecone.

        Returns a summary dict with document_id, chunk count, etc.
        """
        self._validate_file(file_bytes, filename, content_type)
        document_id = self._generate_document_id(file_bytes)
        logger.info(f"Processing document: {filename} (id={document_id[:12]}...)")


        file_ext = SUPPORTED_TYPES.get(content_type,"txt")
        pages = self._extract_text(file_bytes, filename, file_ext)

        if not pages:
            raise ValueError(f"No text could be extracted from {filename}")
        
        total_text_length = sum(len(p["text"]) for p in pages)
        logger.info(
            f"Extracted text from {len(pages)} page(s), "
            f"{total_text_length} total characters"
        )

        chunks = self.chunker.chunk_document(pages)
        logger.info(f"Created {len(chunks)} chunks from {filename}")

        texts =[c["text"] for c in chunks]
        embeddings = await self.embedder.get_embeddings_batch(texts)

        vectors = []
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            vector_id = f"{document_id}chunk{i}"
            vectors.append({
                "id": vector_id,
                "values": embedding,
                "metadata":{
                    "document_id": document_id,
                    "filename": filename,
                    "text": chunk["text"],
                    "chunk_index": chunk["chunk_index"],
                    "word_count": chunk["word_count"],
                    "page_number": chunk["metadata"].get("page_number", 1),
                }
            })
        
        upserted = self._upsert_in_batches(vectors, batch_size=100)
        logger.info(
            f"Document '{filename}' processed: "
            f"{len(chunks)} chunks upserted to Pinecone"
        )
        return {
            "document_id": document_id,
            "filename": filename,
            "pages_processed": len(pages),
            "chunks_created": len(chunks),
            "vectors_upserted": upserted,
            "file_size_kb": round(len(file_bytes) / 1024, 2),
        }


    # ------------------------------------------------------------------
    # TEXT EXTRACTION — per file type
    # ------------------------------------------------------------------
    def _extract_text(
            self, file_bytes: bytes, filename: str, file_ext: str
    )-> list[dict]:
        """
        Extract text from file bytes.
        Returns list of page dicts: [{text, page_number, filename}]
        """
        try:
            if file_ext == "pdf":
                return self._extract_pdf(file_bytes, filename)
            elif file_ext == "txt":
                return self._extract_txt(file_bytes, filename)
            elif file_ext == "csv":
                return self._extract_csv(file_bytes, filename)
            elif file_ext == "json":
                return self._extract_json(file_bytes, filename)
            elif file_ext == "docx":
                return self._extract_docx(file_bytes, filename)
            else:
                text = file_bytes.decode("utf-8", errors="ignore")
                return [{"text": text, "page_number": 1, "filename": filename}]
        except Exception as e:
            logger.error(f"Text extraction failed for {filename}: {e}")
            raise ValueError(f"Could not extract text from {filename}: {str(e)}")
        

    def _extract_pdf(self, file_bytes: bytes, filename: str)-> list[dict]:
        """Extract text from PDF — one dict per page."""
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            pages = []
            for i, page in enumerate(reader.pages):
                text = page.extract_text() or ""
                if text.strip():
                    pages.append(
                        {
                            "text":text,
                            "page_number": i+1,
                            "filename": filename
                        }
                    )
            return pages
        
        except ImportError:
            logger.warning("pypdf not installed, treating PDF as binary text")
            text = file_bytes.decode("utf-8", errors="ignore")
            return [{ "text": text, "page_number": 1, "filename": filename}]
        
    def _extract_txt(self, file_bytes: bytes, filename: str, file_ext) -> list[dict]:
        """Extract text from plain text file."""
        text = file_bytes.decode("utf-8", errors="ignore")
        return [{"text": text, "page_number": 1, "filename": filename}]
    
    def _extract_csv(self, file_bytes: bytes, filename: str) -> list[dict]:
        """
        Extract text from CSV — convert each row into a readable sentence.
        e.g. "Name: John | Age: 30 | City: London"
        """
        import csv
        text_lines = []
        try:
            content = file_bytes.decode("utf-8", errors="ignore")
            reader = csv.DictReader(io.StringIO(content))
            for row in reader:
                row_text = " | ".join(
                    f"{k}: {v}" for k,v in row.items() if v
                )
                text_lines.append(row_text)
            full_text = "\n".join(text_lines)
        except Exception as e:
            logger.warning(f"CSV parsing failed, using raw text: {e}")
            full_text = file_bytes.decode("utf-8", errors="ignore")
        return [{"text":full_text, "page_number": 1, "filename": filename}]
    
    def _extract_json(self, file_bytes: bytes, filename: str):
        """Extract text from JSON — flatten to readable key: value pairs."""
        import json
        try:
            data = json.loads(file_bytes.decode("utf-8", errors="ignore"))
            text = self._flatten_json(data)
            return [{"text": text, "page_number": 1, "filename": filename}]
        except Exception as e:
            logger.warning(f"JSON parsing failed, using raw text: {e}")
            text = file_bytes.decode("utf-8", errors="ignore")

    def _extract_docx(self, file_bytes: bytes, filename: str) -> list[dict]:
        """Extract text from Word document."""
        try:
            from docx import Document
            doc = Document(io.BytesIO(file_bytes))
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            text = "\n".join(paragraphs)
            return [{"text": text, "page_number": 1, "filename": filename}]
        except Exception as e:
            logger.warning("python-docx not installed")
            text = file_bytes.decode("utf-8", errors="ignore")
            return [{"text": text, "page_number": 1, "filename": filename}]


    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------
    def _validate_file(
            self, file_bytes: bytes, filename: str, content_type: str
    ):
      """Raise ValueError if file is invalid."""
      size_mb = len(file_bytes) / (1024 * 1024)
      if size_mb > MAX_FILE_SIZE_MB:
          raise ValueError(
              f"File too large: {size_mb:.1f}MB (max {MAX_FILE_SIZE_MB}MB)"
          )
      if content_type not in SUPPORTED_TYPES:
          raise ValueError(
                f"Unsupported file type: {content_type}. "
                f"Supported: {list(SUPPORTED_TYPES.keys())}"
                )
      if len(file_bytes)==0:
          raise ValueError("File is empty")

    def _generate_document_id(self, file_bytes: bytes) -> str:
        """SHA-256 hash of file content = same file always gets same ID."""
        return hashlib.sha256(file_bytes).hexdigest()  
    
    def _flatten_json(self, data, prefix="")-> str:
        """Recursively flatten a JSON object to readable text."""
        lines = []
        if isinstance(data, dict):
            for key, value in data.items():
                full_key = f"{prefix}.{key}" if prefix else key
                lines.append(self._flatten_json(value, full_key))
        elif isinstance(data, list):
            for i, item in enumerate(data):
                lines.append(self._flatten_json(item, f"{prefix}[{i}]"))
        else:
            lines.append(f"{prefix}: {data}")
        
        return "\n".join(lines)
    
    def _upsert_in_batches(self, vectors: list, batch_size: int = 100)-> int:
        """
        Pinecone recommends batches of 100 vectors max.
        This prevents timeouts on large documents.
        """
        total_upserted = 0
        for i, in range(0, len(vectors), batch_size):
            batch = vectors[i:i+batch_size]
            count = self.vector.upsert(batch)
            total_upserted +=count
            logger.info(
                f"Upserted batch {i // batch_size + 1}: {count} vectors"
            )
        return total_upserted