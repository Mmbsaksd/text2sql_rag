from pinecone import Pinecone
from app.config import settings
import logging
logger = logging.getLogger("app")

class PineconeService:
    def __init__(self):
        self.client = None
        self.index = None

    def connect(self):
        self.client = Pinecone(
            api_key=settings.PINECONE_API_KEY
        )
        self.index = self.client.Index(
            settings.PINECONE_INDEX_NAME
        )
    def health_check(self)-> bool:
        return self.index is not None
    
    def upsert(self, vectors: list[dict]) -> int:
        """
        Store vectors in Pinecone.

        Each vector dict must have:
          - id: unique string identifier
          - values: list of floats (the embedding)
          - metadata: dict with chunk text and source info

        Returns count of vectors upserted.
        """
        if not vectors:
            return 0
        
        response = self.index.upsert(vectors=vectors)
        count = response.get("upserted_count",len(vectors))
        logger.info(f"Upserted{count} vector to Pinecone")
        return count
    
    def query(self, embedding: list[float], top_k: int=5) -> list[dict]:
        """
        Find the most similar vectors to a given embedding.

        Returns list of matches, each with:
          - id: vector id
          - score: similarity score (0-1, higher = more similar)
          - metadata: the stored metadata (text, filename, etc.)
        """

        response = self.index.query(
            vector=embedding,
            top_k=top_k,
            include_metadata=True,
        )
        matches = response.get("matches",[])
        logger.info(f"Pinecone query returned {len(matches)} matches")
        return matches
    
    def deleted_by_document_id(self, document_id: str) -> bool:
        """
        Delete all vectors belonging to a specific document.
        We find them using metadata filter on document_id.
        """
        try:
            self.index.delete(
                filter={"document_id": {"$eq": document_id}}
            )
            logger.info(f"Deleted vectors for document_id: {document_id}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to delete vectors for {document_id}: {e}")
            return False
        
    def delete_all(self)-> bool:
        """
        Delete ALL vectors from the index (used for full reset).
        """
        try:
            self.index.delete(delete_all=True)
            logger.info("Deleted ALL vectors from Pinecone index")
            return True
        
        except Exception as e:
            logger.error(f"Failed to delete all vectors: {e}")
            return False
        
    def get_stats(self)-> dict:
        """
        Get index statistics — total vector count, dimensions, etc.
        """
        try:
            stats = self.index.describe_index_stats()
            return{
                "total_vectors": stats.get("total_vector_count", 0),
                "dimension": stats.get("dimension", 0),
                "index_name": settings.PINECONE_INDEX_NAME
            }
        except Exception as e:
            logger.error(f"Failed to get Pinecone stats: {e}")
            return {}