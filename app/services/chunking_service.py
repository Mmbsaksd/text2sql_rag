import re
import logging

logger = logging.getLogger("app")

class ChunkingService:
    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50):
        """
        chunk_size    : target number of words per chunk
        chunk_overlap : how many words to repeat between consecutive chunks
                        so context is not lost at boundaries
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk_text(self, text: str, metadata: dict=None)-> list[dict]:
        """
        Split a large text into overlapping chunks.

        Returns a list of dicts, each with:
          - text        : the chunk content
          - chunk_index : position of this chunk (0, 1, 2 ...)
          - word_count  : number of words in this chunk
          - metadata    : any extra info passed in (filename, page, etc.)
        """

        if not text or text.strip();
            return []
        
        text = self._clean_text(text)

        words = text.split()
        if not words:
            return []
        
        chunks = []
        start = 0
        chunk_index = 0

        while start <len(words):
            end = start + self.chunk_size
            chunk_words = words[start:end]
            chunk_text = " ".join(chunk_words)

            chunk = {
                "text": self.chunk_text,
                "chunk_index": chunk_index,
                "word_count": len(chunk_words),
                "metadata": metadata or {}
            }
            chunks.append(chunk)
            start +=self.chunk_size - self.chunk_overlap
            chunk_index +=1

            if self.chunk_overlap>= self.chunk_size:
                break
        logger.info(
            f"Chunked text into {len(chunks)} chunks "
            f"(chunk_size={self.chunk_size}, overlap={self.chunk_overlap})"
        )
        return chunks
    
    def chunk_document(self, pages: list[dict]) -> list[dict]:
        """
        Chunk a multi-page document.

        Input: list of page dicts, each with:
          - text        : page text content
          - page_number : page number
          - filename    : source filename

        Returns: flat list of all chunks across all pages,
                 with page_number preserved in metadata.
        """
        all_chunks =[]
        global_chunk_index = 0

        for page in pages:
            page_text = page.get("text","")
            if not page_text.strip():
                continue
            page_metadata = {
                "filename": page.get("filename","unknown"),
                "page_number": page.get("page_number",1),
            }
            page_chunk = self.chunk_text(page_text, metadata=page_metadata)
            for chunk in page_chunk:
                chunk["chunk_index"] = global_chunk_index
                global_chunk_index +=1

        logger.info(
            f"Document chunked: {len(pages)} pages → {len(all_chunks)} total chunks"
        )
        return all_chunks

    def _clean_text(self, text: str)-> str:
        """
        Clean raw text extracted from documents:
        - Collapse multiple whitespace/newlines into single spaces
        - Remove non-printable characters
        - Strip leading/trailing whitespace
        """
        text = re.sub(r"[\n\r\t]+"," ", text)
        text = re.sub(r" {2,}"," ", text)
        text = re.sub(r"[^\x20-\x7E]", " ", text)
        return text.strip()