class ServiceRegistry:
    def __init__(self):
        self.database=None
        self.vector_db=None
        self.cache=None
        self.storage=None

registry=ServiceRegistry()