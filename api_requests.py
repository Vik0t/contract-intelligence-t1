from pydantic import BaseModel, EmailStr, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum

class UserRole(str, Enum):
    USER = 'user'
    ADMIN = 'admin'

class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=6)

class UserLogin(BaseModel):
    username: str
    password: str

class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    role: str
    created_at: datetime

class DocumentUpload(BaseModel):
    filename: str
    template_id: int

class DocumentResponse(BaseModel):
    id: int
    owner: Optional[int]
    filename: Optional[str]
    template_id: int
    path: str
    created_at: datetime

class MetadataResponse(BaseModel):
    id: int
    document_id: int
    fields: Dict[str, Any]
    created_at: datetime

class SessionResponse(BaseModel):
    id: int
    user_id: int
    session_token: str
    created_at: datetime
    expires_at: datetime

class LoginResponse(BaseModel):
    user: UserResponse
    session_token: str
    expires_at: datetime

class LogoutRequest(BaseModel):
    session_token: str

class APIResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Any] = None