from pydantic import BaseModel
from typing import List

class FileUpload(BaseModel):
    filename: str

class FileList(BaseModel):
    files: List[str]