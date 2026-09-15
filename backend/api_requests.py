from re import fullmatch, match
from fastapi import HTTPException
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum

# ============ ENUMS ============

class UserRole(str, Enum):
    """User role enumeration for access control"""
    USER = 'user'
    ADMIN = 'admin'

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
    parsing_time_seconds: Optional[float] = Field(
        None,
        description="Time taken to parse the document in seconds"
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
    template_id: Optional[int] = Field(
        None,
        description="Template ID used for extraction (optional)"
    )
    folder_id: Optional[int] = Field(
        None,
        description="Folder ID, or null for the root"
    )
    status: str = Field(
        ...,
        description="Current document processing status"
    )
    processing_error: Optional[str] = Field(
        None,
        description="Human-readable processing error, if any"
    )
    has_metadata: bool = Field(
        False,
        description="Whether metadata has been extracted"
    )
    has_file: bool = Field(
        False,
        description="Whether the original file is available"
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


class DocumentPageResponse(BaseModel):
    """A readable page of parsed document text for source verification."""
    number: int
    text: str


class DocumentContentResponse(BaseModel):
    """Parsed document content grouped by logical or physical pages."""
    source_format: Optional[str] = None
    page_count: int
    pages: List[DocumentPageResponse]

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

class MetadataExtractResponse(BaseModel):
    """
    Response model for metadata extraction
    """
    success: bool = Field(
        ...,
        description="Whether metadata extraction was successful"
    )
    message: str = Field(
        ...,
        description="Metadata extraction status message"
    )
    metadata_id: Optional[int] = Field(
        None,
        description="ID of the extracted metadata"
    )
    metadata: Optional['MetadataResponse'] = Field(
        None,
        description="Extracted metadata information"
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

# ============ ADMIN TYPES ============

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
        description="Total number of registered users (always 1 for user stats)"
    )
    total_parsed_documents: int = Field(
        ...,
        description="Total number of parsed documents"
    )
    total_metadata_extractions: int = Field(
        ...,
        description="Total number of metadata extractions performed"
    )
    total_tokens_used: int = Field(
        ...,
        description="Total tokens used across all documents"
    )
    average_parsing_time: float = Field(
        ...,
        description="Average document parsing time in seconds"
    )
    average_extraction_time: float = Field(
        ...,
        description="Average metadata extraction time in seconds"
    )
    period_start: datetime = Field(
        ...,
        description="Start of statistics period"
    )
    period_end: datetime = Field(
        ...,
        description="End of statistics period"
    )
    documents_per_day: Dict[str, int] = Field(
        ...,
        description="Number of documents processed per day"
    )

class FolderCreateRequest(BaseModel):
    """Create a document folder."""
    name: str = Field(..., min_length=1, max_length=120)

class FolderUpdateRequest(BaseModel):
    """Rename a document folder."""
    name: str = Field(..., min_length=1, max_length=120)

class FolderResponse(BaseModel):
    """Document folder response."""
    id: int
    owner: int
    name: str
    document_count: int = 0
    created_at: datetime

class FolderListResponse(BaseModel):
    """List of folders for the current user."""
    folders: List[FolderResponse]

class DocumentUpdateRequest(BaseModel):
    """Update document placement."""
    folder_id: Optional[int] = None

class MetadataUpdateRequest(BaseModel):
    """Manually edited document metadata."""
    fields: Dict[str, Any] = Field(..., description="Complete editable metadata object")
