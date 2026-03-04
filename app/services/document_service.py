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
        self_embedder = embedding_service
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
        pages = self._










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
                return self._extract_text(file_bytes, filename)
            
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
        
    def _extract_txt(self, file_bytes: bytes, filename: str) -> list[dict]:
        """Extract text from plain text file."""
        text = file_bytes.decode("utf-8", errors="ignore")
        return [{"text": text, "page_number":1, "filename": filename}]
        



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