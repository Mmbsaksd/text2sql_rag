from app.config import settings

class StorageService:
    def __init__(self):
        self.backend = settings.STORAGE_BACKEND

    def health_check(self):
        return True