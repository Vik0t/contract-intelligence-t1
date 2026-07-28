from re import fullmatch, match
from fastapi import HTTPException, Header
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum

# ============ ENUMS ============

class UserRole(str, Enum):
    """User role enumeration for access control"""
    USER = 'user'
    ADMIN = 'admin'

# ============ AUTHENTICATION HEADER ============

class TokenHeader(BaseModel):
    """
    Pydantic model for extracting Bearer token from Authorization header
    """
    authorization: str = Header(
        ...,
        description="Bearer token in format 'Bearer <token>'"
    )
    
    @property
    def token(self) -> str:
        """
        Extract and validate the token from the Authorization header
        """
        if not self.authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication scheme. Expected 'Bearer <token>'"
            )
        return self.authorization.replace("Bearer ", "")

# ============ AUTHENTICATION TYPES ============

class UserCreateRequest(BaseModel):
    """
    Request model for user registration
    """
    username: str = Field(
        ..., 
        min_length=3, 
        max_length=50,
        description="Unique username for the user (3-50 characters)"
    )
    email: EmailStr = Field(
        ...,
        description="Valid email address for user communication"
    )
    password: str = Field(
        ..., 
        min_length=6,
        description="User password (minimum 6 characters)"
    )
    
    @field_validator("username")
    @classmethod
    def username_check(cls, value: str):
        if not value.isalnum():
            raise ValueError("Username can not contain any special characters or spaces")
        return value
    
    @field_validator("email")
    @classmethod
    def email_check(cls, value: str):
        if not bool(fullmatch(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", value)):
            raise ValueError("Email has incorrect format")
        return value
    
    @field_validator("password")
    @classmethod
    def password_check(cls, value: str):
        if not bool(match(r"^[a-zA-Z0-9_-]+$", value)):
            raise ValueError("Password can not contain any special characters aside from hyphen and underscore")
        return value

class UserCreateResponse(BaseModel):
    """
    Response model for user registration
    """
    success: bool = Field(
        ...,
        description="Whether registration was successful"
    )
    message: str = Field(
        ...,
        description="Registration status message"
    )
    user_id: Optional[int] = Field(
        None,
        description="ID of the newly created user"
    )

class UserLoginRequest(BaseModel):
    """
    Request model for user login
    """
    username: str = Field(
        ...,
        description="Username of the user"
    )
    password: str = Field(
        ...,
        description="User password"
    )

class UserLoginResponse(BaseModel):
    """
    Response model for successful login
    """
    user: 'UserResponse' = Field(
        ...,
        description="User information"
    )
    session_token: str = Field(
        ...,
        description="Session token for authentication"
    )
    expires_at: datetime = Field(
        ...,
        description="Token expiration timestamp"
    )

class UserRecoverRequest(BaseModel):
    """
    Request model for account recovery
    """
    username: Optional[str] = Field(
        None,
        description="Username for recovery (alternative to email)"
    )
    email: Optional[EmailStr] = Field(
        None,
        description="Email for recovery (alternative to username)"
    )
    
    @model_validator(mode='before')
    @classmethod
    def username_or_email(cls, values):
        """Ensure at least one recovery method is provided"""
        if "username" in values or "email" in values:
            return values
        raise ValueError("Either username or email must be provided")

class UserRecoverResponse(BaseModel):
    """
    Response model for account recovery
    """
    success: bool = Field(
        ...,
        description="Whether recovery request was successful"
    )
    message: str = Field(
        ...,
        description="Recovery status message"
    )
    recovery_email_sent: bool = Field(
        ...,
        description="Whether recovery email was sent"
    )

class SessionValidateRequest(BaseModel):
    """
    Request model for session validation
    """
    session_token: str = Field(
        ...,
        description="Session token to validate"
    )

class SessionValidateResponse(BaseModel):
    """
    Response model for session validation
    """
    valid: bool = Field(
        ...,
        description="Whether the session is valid"
    )
    user_id: Optional[int] = Field(
        None,
        description="User ID if session is valid"
    )
    expires_at: Optional[datetime] = Field(
        None,
        description="Session expiration time if valid"
    )

class LogoutRequest(BaseModel):
    """
    Request model for logout
    """
    session_token: str = Field(
        ...,
        description="Session token to invalidate"
    )

class LogoutResponse(BaseModel):
    """
    Response model for logout
    """
    success: bool = Field(
        ...,
        description="Whether logout was successful"
    )
    message: str = Field(
        ...,
        description="Logout status message"
    )

# ============ USER TYPES ============

class CurrentUserRequest(BaseModel):
    """
    Request model for getting current user
    """
    token: TokenHeader = Field(
        ...,
        description="Authentication token in Authorization header"
    )

class UserResponse(BaseModel):
    """
    User information response
    """
    id: int = Field(
        ...,
        description="Unique user identifier"
    )
    username: str = Field(
        ...,
        description="User's username"
    )
    email: str = Field(
        ...,
        description="User's email address"
    )
    role: str = Field(
        ...,
        description="User's role (user/admin)"
    )
    created_at: datetime = Field(
        ...,
        description="Account creation timestamp"
    )

class UserUpdateRequest(BaseModel):
    """
    Request model for updating user profile
    """
    token: TokenHeader = Field(
        ...,
        description="Authentication token in Authorization header"
    )
    username: Optional[str] = Field(
        None,
        min_length=3,
        max_length=50,
        description="New username (3-50 characters)"
    )
    email: Optional[EmailStr] = Field(
        None,
        description="New email address"
    )
    password: Optional[str] = Field(
        None,
        min_length=6,
        description="New password (minimum 6 characters)"
    )
    
    @field_validator("username")
    @classmethod
    def username_check(cls, value: str | None):
        if value is not None and not value.isalnum():
            raise ValueError("Username can not contain any special characters or spaces")
        return value
    
    @field_validator("email")
    @classmethod
    def email_check(cls, value: str | None):
        if value is not None and not bool(fullmatch(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", value)):
            raise ValueError("Email has incorrect format")
        return value
    
    @field_validator("password")
    @classmethod
    def password_check(cls, value: str | None):
        if value is not None and not bool(match(r"^[a-zA-Z0-9_-]+$", value)):
            raise ValueError("Password can not contain any special characters aside from hyphen and underscore")
        return value

class UserUpdateResponse(BaseModel):
    """
    Response model for user update
    """
    success: bool = Field(
        ...,
        description="Whether update was successful"
    )
    message: str = Field(
        ...,
        description="Update status message"
    )
    user: Optional[UserResponse] = Field(
        None,
        description="Updated user information"
    )

class UserDeleteRequest(BaseModel):
    """
    Request model for user deletion
    """
    token: TokenHeader = Field(
        ...,
        description="Authentication token in Authorization header"
    )

class UserDeleteResponse(BaseModel):
    """
    Response model for user deletion
    """
    success: bool = Field(
        ...,
        description="Whether deletion was successful"
    )
    message: str = Field(
        ...,
        description="Deletion status message"
    )

# ============ DOCUMENT TYPES ============

class DocumentUploadRequest(BaseModel):
    """
    Request model for document upload
    """
    token: TokenHeader = Field(
        ...,
        description="Authentication token in Authorization header"
    )
    filename: str = Field(
        ...,
        description="Name of the file being uploaded"
    )
    template_id: int = Field(
        ...,
        description="ID of the template to use for extraction"
    )

class DocumentUploadResponse(BaseModel):
    """
    Response model for document upload
    """
    success: bool = Field(
        ...,
        description="Whether upload was successful"
    )
    message: str = Field(
        ...,
        description="Upload status message"
    )
    document_id: Optional[int] = Field(
        None,
        description="ID of the uploaded document"
    )
    document: Optional['DocumentResponse'] = Field(
        None,
        description="Uploaded document information"
    )

class DocumentResponse(BaseModel):
    """
    Document information response
    """
    id: int = Field(
        ...,
        description="Unique document identifier"
    )
    owner: Optional[int] = Field(
        None,
        description="User ID of document owner"
    )
    filename: Optional[str] = Field(
        None,
        description="Original filename"
    )
    template_id: int = Field(
        ...,
        description="Template ID used for extraction"
    )
    path: str = Field(
        ...,
        description="File path in storage"
    )
    created_at: datetime = Field(
        ...,
        description="Document creation timestamp"
    )
    
class DocumentMetadataResponse(DocumentResponse):
    """
    Document information with parsed metadata
    """
    metadata: Optional['MetadataResponse'] = Field(
        None,
        description="Added metadata information"
    )
    

class DocumentListRequest(BaseModel):
    """
    Request model for listing documents
    """
    token: TokenHeader = Field(
        ...,
        description="Authentication token in Authorization header"
    )
    page: Optional[int] = Field(
        1,
        ge=1,
        description="Page number for pagination"
    )
    limit: Optional[int] = Field(
        50,
        ge=1,
        le=100,
        description="Number of items per page"
    )

class DocumentListResponse(BaseModel):
    """
    Response model for document list
    """
    total: int = Field(
        ...,
        description="Total number of documents"
    )
    page: int = Field(
        ...,
        description="Current page number"
    )
    limit: int = Field(
        ...,
        description="Items per page"
    )
    documents: List[DocumentResponse] = Field(
        ...,
        description="List of documents"
    )

class DocumentGetRequest(BaseModel):
    """
    Request model for getting a single document
    """
    token: TokenHeader = Field(
        ...,
        description="Authentication token in Authorization header"
    )
    document_id: int = Field(
        ...,
        description="ID of the document to retrieve"
    )

class DocumentDeleteRequest(BaseModel):
    """
    Request model for document deletion
    """
    token: TokenHeader = Field(
        ...,
        description="Authentication token in Authorization header"
    )
    document_id: int = Field(
        ...,
        description="ID of the document to delete"
    )

class DocumentDeleteResponse(BaseModel):
    """
    Response model for document deletion
    """
    success: bool = Field(
        ...,
        description="Whether deletion was successful"
    )
    message: str = Field(
        ...,
        description="Deletion status message"
    )

# ============ METADATA TYPES ============

class MetadataParseRequest(BaseModel):
    """
    Request model for parsing metadata
    """
    token: TokenHeader = Field(
        ...,
        description="Authentication token in Authorization header"
    )
    document_id: int = Field(
        ...,
        description="ID of the document to parse metadata for"
    )

class MetadataParseResponse(BaseModel):
    """
    Response model for parsing metadata
    """
    success: bool = Field(
        ...,
        description="Whether metadata addition was successful"
    )
    message: str = Field(
        ...,
        description="Metadata addition status message"
    )
    metadata_id: Optional[int] = Field(
        None,
        description="ID of the added metadata"
    )
    metadata: Optional['MetadataResponse'] = Field(
        None,
        description="Added metadata information"
    )

class MetadataResponse(BaseModel):
    """
    Metadata information response
    """
    id: int = Field(
        ...,
        description="Unique metadata identifier"
    )
    document_id: int = Field(
        ...,
        description="Associated document ID"
    )
    fields: Dict[str, Any] = Field(
        ...,
        description="Metadata fields and values"
    )
    created_at: datetime = Field(
        ...,
        description="Metadata creation timestamp"
    )

# ============ SESSION TYPES ============

class SessionResponse(BaseModel):
    """
    Session information response
    """
    id: int = Field(
        ...,
        description="Unique session identifier"
    )
    user_id: int = Field(
        ...,
        description="Associated user ID"
    )
    session_token: str = Field(
        ...,
        description="Session token"
    )
    created_at: datetime = Field(
        ...,
        description="Session creation timestamp"
    )
    expires_at: datetime = Field(
        ...,
        description="Session expiration timestamp"
    )

class SessionListRequest(BaseModel):
    """
    Request model for listing sessions
    """
    token: TokenHeader = Field(
        ...,
        description="Authentication token in Authorization header"
    )

class SessionListResponse(BaseModel):
    """
    Response model for session list
    """
    total: int = Field(
        ...,
        description="Total number of active sessions"
    )
    sessions: List[SessionResponse] = Field(
        ...,
        description="List of active sessions"
    )

class SessionRevokeRequest(BaseModel):
    """
    Request model for session revocation
    """
    token: TokenHeader = Field(
        ...,
        description="Authentication token in Authorization header"
    )

class SessionRevokeResponse(BaseModel):
    """
    Response model for session revocation
    """
    success: bool = Field(
        ...,
        description="Whether revocation was successful"
    )
    message: str = Field(
        ...,
        description="Revocation status message"
    )

# ============ TEMPLATE TYPES ============

class TemplateResponse(BaseModel):
    """
    Template information response
    """
    id: int = Field(
        ...,
        description="Unique template identifier"
    )
    name: str = Field(
        ...,
        description="Template name"
    )
    description: Optional[str] = Field(
        None,
        description="Template description"
    )
    fields_schema: Dict[str, Any] = Field(
        ...,
        description="Template field schema"
    )
    created_at: datetime = Field(
        ...,
        description="Template creation timestamp"
    )

class TemplateListRequest(BaseModel):
    """
    Request model for listing templates
    """
    token: TokenHeader = Field(
        ...,
        description="Authentication token in Authorization header"
    )
    page: Optional[int] = Field(
        1,
        ge=1,
        description="Page number for pagination"
    )
    limit: Optional[int] = Field(
        50,
        ge=1,
        le=100,
        description="Number of items per page (max 100)"
    )

class TemplateListResponse(BaseModel):
    """
    Response model for template list with pagination
    """
    total: int = Field(
        ...,
        description="Total number of templates"
    )
    page: int = Field(
        ...,
        description="Current page number"
    )
    limit: int = Field(
        ...,
        description="Number of items per page"
    )
    templates: List[TemplateResponse] = Field(
        ...,
        description="List of templates"
    )

class TemplateGetRequest(BaseModel):
    """
    Request model for getting a template
    """
    token: TokenHeader = Field(
        ...,
        description="Authentication token in Authorization header"
    )

# ============ ADMIN TYPES ============

class StatsRequest(BaseModel):
    """
    Request model for stats endpoint
    """
    token: TokenHeader = Field(
        ...,
        description="Authentication token in Authorization header"
    )
    period_days: Optional[int] = Field(
        30,
        ge=1,
        le=365,
        description="Number of days to include in stats"
    )

class StatsResponse(BaseModel):
    """
    Response model for extraction statistics
    """
    total_documents: int = Field(
        ...,
        description="Total number of processed documents"
    )
    total_users: int = Field(
        ...,
        description="Total number of registered users"
    )
    total_extractions: int = Field(
        ...,
        description="Total number of extractions performed"
    )
    average_processing_time: float = Field(
        ...,
        description="Average document processing time in seconds"
    )
    total_api_calls: int = Field(
        ...,
        description="Total number of API calls"
    )
    period_start: datetime = Field(
        ...,
        description="Start of statistics period"
    )
    period_end: datetime = Field(
        ...,
        description="End of statistics period"
    )