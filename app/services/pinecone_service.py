from pinecone import Pinecone
from app.config import settings

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
    def health_check(self):
        return self.index is not None