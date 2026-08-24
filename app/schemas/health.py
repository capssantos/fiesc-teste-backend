from pydantic import BaseModel


class HealthResponse(BaseModel):
    api: str
    database: str
    object_storage: str
    similarity_index: str
    document_index: str
    fault_document_map: str
    llm: str
