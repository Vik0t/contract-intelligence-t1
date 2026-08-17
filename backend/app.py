from datetime import datetime, timedelta
import mimetypes
import os
import shutil
import tempfile
import threading
import bcrypt
from pathlib import Path
from typing import Optional
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Depends, Header, UploadFile
from fastapi.responses import FileResponse

import backend.database as database
import backend.api_requests as api_requests

from src.local_extraction import extract_text_from_document, extract_contract_key_data

app = FastAPI(
    title="T1 Contract Intelligence",
    description="Extracting important info from contracts",
    version="1.0.0"
)

engine = database.get_engine(os.getenv(
    'DATABASE_URL',
    'sqlite:///documents.db'
))
database.create_tables(engine)

STORAGE_ROOT = Path(os.getenv('DOCUMENT_STORAGE_DIR', 'uploads'))
STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
PROCESSING_LOCK = threading.Lock()

@app.get("/ping")
async def ping():
    return "pong!"

# ============ HELPER FUNCTIONS ============

def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its hash."""
    return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))

def get_user_from_token(session_token: str):
    """Get user from session token or raise HTTPException."""
    db = database.get_session(engine)
    try:
        session = database.get_session_by_token(db, session_token)
        if not session:
            raise HTTPException(status_code=401, detail="Invalid or expired session token")
        user = database.get_user(db, user_id=session.user_id)
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user, db
    except HTTPException:
        db.close()
        raise

def get_admin_from_token(session_token: str):
    """Get admin user from session token or raise HTTPException."""
    user, db = get_user_from_token(session_token)
    if user.role != 'admin':
        db.close()
        raise HTTPException(status_code=403, detail="Access denied. Admin privileges required")
    return user, db

def verify_document_ownership(user, document):
    """Verify user owns document or is admin."""
    if document.owner != user.id and user.role != 'admin':
        raise HTTPException(status_code=403, detail="Access denied")

def create_user_response(user):
    """Create a UserResponse from a user object."""
    return api_requests.UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        role=user.role,
        created_at=user.created_at
    )

def create_document_response(document):
    """Create a DocumentResponse from a document object."""
    has_metadata = document.document_metadata is not None
    has_parsed_document = document.parsed_text is not None
    if has_metadata:
        status = 'extracted'
    elif has_parsed_document and getattr(document, 'processing_status', None) in (None, 'uploaded'):
        status = 'ready'
    else:
        status = getattr(document, 'processing_status', None) or (
            'ready' if has_parsed_document else 'uploaded'
        )
    return api_requests.DocumentResponse(
        id=document.id,
        owner=document.owner,
        filename=document.filename,
        template_id=document.template_id,
        folder_id=document.folder_id,
        status=status,
        processing_error=getattr(document, 'processing_error', None),
        has_metadata=has_metadata,
        has_file=bool(document.stored_path and Path(document.stored_path).exists()),
        created_at=document.created_at
    )

def create_folder_response(folder, session):
    """Create a folder response with its document count."""
    document_count = session.query(database.Document).filter(
        database.Document.folder_id == folder.id
    ).count()
    return api_requests.FolderResponse(
        id=folder.id,
        owner=folder.owner,
        name=folder.name,
        document_count=document_count,
        created_at=folder.created_at
    )

def get_document_storage_path(user_id, document_id, filename):
    """Build a stable local path for an uploaded document."""
    user_dir = STORAGE_ROOT / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename or 'document').name
    return user_dir / f'{document_id}_{safe_name}'

def try_remove_file(path):
    """Remove a stored file when Windows is not holding it open."""
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except PermissionError:
        # A background parser may still be reading the file.
        pass

def create_metadata_response(metadata):
    """Create a MetadataResponse from a metadata object."""
    return api_requests.MetadataResponse(
        id=metadata.id,
        document_id=metadata.document_id,
        fields=metadata.fields,
        created_at=metadata.created_at
    )

def process_document_parsing(document_id: int):
    """Parse an uploaded file outside the upload request."""
    db = database.get_session(engine)
    try:
        document = database.get_document(db, document_id)
        if not document or not document.stored_path:
            return
        stored_path = document.stored_path

        try:
            with PROCESSING_LOCK:
                started_at = datetime.now()
                parsed_text, document_ir = extract_text_from_document(stored_path)
                parsing_time = (datetime.now() - started_at).total_seconds()

            if database.get_document(db, document_id) is None:
                try_remove_file(stored_path)
                return

            document_ir_dict = document_ir.model_dump() if document_ir else None
            database.update_parsed_document(
                db,
                document_id=document_id,
                text=parsed_text,
                document_ir=document_ir_dict
            )

            existing_stats = database.get_stats(db, document_id=document_id)
            if existing_stats:
                database.update_stats(db, existing_stats[-1].id, parsing_time=parsing_time)
            else:
                database.create_stats(
                    db,
                    document_id=document_id,
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                    parsing_time=parsing_time,
                    extracting_time=None
                )

            database.update_document(
                db,
                document_id,
                processing_status='ready',
                processing_error=None
            )
        except Exception:
            if database.get_document(db, document_id) is not None:
                database.update_document(
                    db,
                    document_id,
                    processing_status='failed',
                    processing_error='Не удалось подготовить документ к анализу.'
                )
            else:
                try_remove_file(stored_path)
    finally:
        db.close()

def process_metadata_extraction(document_id: int):
    """Run the GPU extraction job and persist its result."""
    db = database.get_session(engine)
    try:
        document = database.get_document(db, document_id)
        parsed_doc = database.get_parsed_document(db, document_id)
        if not document or not parsed_doc:
            return

        try:
            document_ir = None
            if parsed_doc.document_ir:
                from src.document_ir import DocumentIR
                document_ir = DocumentIR.model_validate(parsed_doc.document_ir)

            with PROCESSING_LOCK:
                started_at = datetime.now()
                extracted_data = extract_contract_key_data(
                    text=parsed_doc.text,
                    document_ir=document_ir,
                    max_new_tokens=4096
                )
                extraction_time = (datetime.now() - started_at).total_seconds()

            if database.get_document(db, document_id) is None:
                return

            metadata = database.update_metadata(
                db,
                document_id=document_id,
                fields=extracted_data
            )

            existing_stats = database.get_stats(db, document_id=document_id)
            if existing_stats:
                latest_stat = existing_stats[-1]
                completion_tokens = len(str(extracted_data).split())
                database.update_stats(
                    db,
                    latest_stat.id,
                    extracting_time=extraction_time,
                    completion_tokens=(latest_stat.completion_tokens or 0) + completion_tokens,
                    total_tokens=(latest_stat.total_tokens or 0) + completion_tokens
                )

            database.update_document(
                db,
                document_id,
                processing_status='extracted',
                processing_error=None
            )
        except Exception:
            if database.get_document(db, document_id) is not None:
                database.update_document(
                    db,
                    document_id,
                    processing_status='failed',
                    processing_error='Не удалось извлечь реквизиты. Попробуйте запустить анализ ещё раз.'
                )
    finally:
        db.close()

# ============ AUTHENTICATION ENDPOINTS ============

@app.post(
    "/auth/register",
    response_model=api_requests.UserCreateResponse,
    summary="Register a new user",
    description="Create a new user account with username, email, and password"
)
async def register(user_data: api_requests.UserCreateRequest):
    """
    Register a new user
    - username: Unique username (3-50 characters)
    - email: Valid email address
    - password: Password (minimum 6 characters)
    """
    db = database.get_session(engine)
    try:
        if database.get_user(db, username=user_data.username):
            raise HTTPException(status_code=400, detail="Username already exists")
        
        if database.get_user(db, email=user_data.email):
            raise HTTPException(status_code=400, detail="Email already exists")
        
        user = database.create_user(
            db,
            username=user_data.username,
            email=user_data.email,
            password_hash=hash_password(user_data.password)
        )
        
        return api_requests.UserCreateResponse(
            success=True,
            message="User registered successfully",
            user_id=user.id
        )
    finally:
        db.close()


@app.post(
    "/auth/login",
    response_model=api_requests.UserLoginResponse,
    summary="Login user",
    description="Authenticate user and return session token"
)
async def login(login_data: api_requests.UserLoginRequest):
    """
    Login user and return session token
    - username: User's username
    - password: User's password
    """
    db = database.get_session(engine)
    try:
        user = database.get_user(db, username=login_data.username)
        if not user or not verify_password(login_data.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid username or password")
        
        session = database.create_session(db, user.id)
        
        return api_requests.UserLoginResponse(
            user=create_user_response(user),
            session_token=session.session_token,
            expires_at=session.expires_at
        )
    finally:
        db.close()


@app.post(
    "/auth/logout",
    response_model=api_requests.LogoutResponse,
    summary="Logout user",
    description="Invalidate session token"
)
async def logout(logout_data: api_requests.LogoutRequest):
    """
    Logout user and invalidate session
    - session_token: Session token to invalidate
    """
    db = database.get_session(engine)
    try:
        session = database.get_session_by_token(db, logout_data.session_token)
        if not session:
            raise HTTPException(status_code=401, detail="Invalid session token")
        
        db.delete(session)
        db.commit()
        
        return api_requests.LogoutResponse(
            success=True,
            message="Logged out successfully"
        )
    finally:
        db.close()


@app.post(
    "/auth/validate",
    response_model=api_requests.SessionValidateResponse,
    summary="Validate session",
    description="Validate session token"
)
async def validate_session(session_data: api_requests.SessionValidateRequest):
    """
    Validate session token
    - session_token: Session token to validate
    """
    db = database.get_session(engine)
    try:
        session = database.get_session_by_token(db, session_data.session_token)
        
        if not session:
            return api_requests.SessionValidateResponse(
                valid=False,
                user_id=None,
                expires_at=None
            )
        
        return api_requests.SessionValidateResponse(
            valid=True,
            user_id=session.user_id,
            expires_at=session.expires_at
        )
    finally:
        db.close()
        

# !!!! NON-FUNCTIONAL, NEEDS EMAIL SERVICE FOR PROD
# @app.post(
#     "/auth/recover",
#     response_model=api_requests.UserRecoverResponse,
#     summary="Recover account",
#     description="Recover account by username or email"
# )
# async def recover_account(recover_data: api_requests.UserRecoverRequest):
#     """
#     Recover account by username or email
#     - username: Username for recovery (alternative to email)
#     - email: Email for recovery (alternative to username)
#     """
#     db = database.get_session(engine)
#     try:
#         user = None
#         if recover_data.username:
#             user = database.get_user(db, username=recover_data.username)
#         elif recover_data.email:
#             user = database.get_user(db, email=recover_data.email)
        
#         if not user:
#             return api_requests.UserRecoverResponse(
#                 success=True,
#                 message="If the account exists, recovery instructions have been sent",
#                 recovery_email_sent=True
#             )
        
#         # Send recovery email here
# 
#         return api_requests.UserRecoverResponse(
#             success=True,
#             message="Recovery instructions sent to your email",
#             recovery_email_sent=True
#         )
#     finally:
#         db.close()

# ============ USER ENDPOINTS ============

@app.get(
    "/users/me",
    response_model=api_requests.UserResponse,
    summary="Get current user",
    description="Get current authenticated user's profile"
)
async def get_current_user(authorization: str = Header(...)):
    """
    Get current user profile
    Authentication token automatically extracted from Authorization header
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authentication scheme")
    token = authorization.replace("Bearer ", "")
    user, db = get_user_from_token(token)
    try:
        return create_user_response(user)
    finally:
        db.close()


@app.put(
    "/users/me",
    response_model=api_requests.UserUpdateResponse,
    summary="Update current user",
    description="Update current authenticated user's profile"
)
async def update_current_user(
    update_data: api_requests.UserUpdateRequest,
    authorization: str = Header(...)
):
    """
    Update current user profile
    - username: New username (optional)
    - email: New email (optional)
    - password: New password (optional)
    Authentication token automatically extracted from Authorization header
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authentication scheme")
    token = authorization.replace("Bearer ", "")
    user, db = get_user_from_token(token)
    try:
        if update_data.username and update_data.username != user.username:
            if database.get_user(db, username=update_data.username):
                raise HTTPException(status_code=400, detail="Username already exists")
        
        if update_data.email and update_data.email != user.email:
            if database.get_user(db, email=update_data.email):
                raise HTTPException(status_code=400, detail="Email already exists")
        
        update_fields = {}
        if update_data.username:
            update_fields['username'] = update_data.username
        if update_data.email:
            update_fields['email'] = update_data.email
        if update_data.password:
            update_fields['password_hash'] = hash_password(update_data.password)
        
        if update_fields:
            database.update_user(db, user.id, **update_fields)
            user = database.get_user(db, user_id=user.id)
        
        return api_requests.UserUpdateResponse(
            success=True,
            message="Profile updated successfully",
            user=create_user_response(user)
        )
    finally:
        db.close()


@app.delete(
    "/users/me",
    response_model=api_requests.UserDeleteResponse,
    summary="Delete current user",
    description="Delete current authenticated user's account"
)
async def delete_current_user(authorization: str = Header(...)):
    """
    Delete current user account
    Authentication token automatically extracted from Authorization header
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authentication scheme")
    token = authorization.replace("Bearer ", "")
    user, db = get_user_from_token(token)
    try:
        database.delete_user(db, user.id)
        return api_requests.UserDeleteResponse(
            success=True,
            message="Account deleted successfully"
        )
    finally:
        db.close()

# ============ DOCUMENT ENDPOINTS ============

@app.post(
    "/documents",
    response_model=api_requests.DocumentUploadResponse,
    summary="Upload document",
    description="Upload a new document for processing"
)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    template_id: Optional[int] = Form(None),
    folder_id: Optional[int] = Form(None),
    authorization: str = Header(...)
):
    """
    Upload a new document
    - file: PDF or DOCX file to upload
    - template_id: ID of the template to use (optional)
    Authentication token automatically extracted from Authorization header
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authentication scheme")
    token = authorization.replace("Bearer ", "")
    
    user, _ = get_user_from_token(token)
    _.close()
    
    file_extension = os.path.splitext(file.filename)[1].lower()
    if file_extension not in {'.pdf', '.docx'}:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Allowed types: .pdf, .docx"
        )
    
    temp_path = None
    try:
        temp_fd, temp_path = tempfile.mkstemp(suffix=file_extension)
        with os.fdopen(temp_fd, 'wb') as temp_file:
            content = await file.read()
            temp_file.write(content)
        
        db = database.get_session(engine)
        try:
            if template_id is not None:
                template = database.get_template(db, template_id=template_id)
                if not template:
                    raise HTTPException(status_code=400, detail=f"Template with id {template_id} not found")
            if folder_id is not None:
                folder = database.get_folder(db, folder_id)
                if not folder or folder.owner != user.id:
                    raise HTTPException(status_code=404, detail="Folder not found")
            
            document = database.create_document(
                db,
                owner=user.id,
                template_id=template_id,  # Can be None
                filename=file.filename,
                folder_id=folder_id
            )
            stored_path = get_document_storage_path(user.id, document.id, file.filename)
            shutil.copyfile(temp_path, stored_path)
            database.update_document(
                db,
                document.id,
                stored_path=str(stored_path),
                processing_status='processing',
                processing_error=None
            )
            background_tasks.add_task(process_document_parsing, document.id)
            
            return api_requests.DocumentUploadResponse(
                success=True,
                message="Документ загружен. Подготовка к анализу началась.",
                document_id=document.id,
                document=create_document_response(document),
                parsing_time_seconds=None
            )
        finally:
            db.close()
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass
            

@app.get(
    "/documents",
    response_model=api_requests.DocumentListResponse,
    summary="List documents",
    description="Get all documents for current user"
)
async def list_documents(
    page: Optional[int] = 1,
    limit: Optional[int] = 50,
    folder_id: Optional[int] = None,
    search: Optional[str] = None,
    authorization: str = Header(...)
):
    """
    Get all documents for current user
    - page: Page number for pagination
    - limit: Items per page
    Authentication token automatically extracted from Authorization header
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authentication scheme")
    token = authorization.replace("Bearer ", "")
    user, db = get_user_from_token(token)
    try:
        page = page or 1
        limit = limit or 50
        
        documents, total = database.get_documents_by_owner_paginated(
            db, 
            owner_id=user.id,
            page=page,
            limit=limit,
            folder_id=folder_id,
            search=search
        )
        
        return api_requests.DocumentListResponse(
            total=total,
            page=page,
            limit=limit,
            documents=[create_document_response(doc) for doc in documents]
        )
    finally:
        db.close()


@app.get(
    "/documents/{document_id}",
    response_model=api_requests.DocumentMetadataResponse,
    summary="Get document",
    description="Get document by ID with its metadata"
)
async def get_document(
    document_id: int,
    authorization: str = Header(...)
):
    """
    Get document by ID with its metadata
    - document_id: ID of the document to retrieve
    Authentication token automatically extracted from Authorization header
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authentication scheme")
    token = authorization.replace("Bearer ", "")
    user, db = get_user_from_token(token)
    try:
        document = database.get_document(db, document_id=document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        
        verify_document_ownership(user, document)
        
        metadata = None
        doc_metadata = database.get_metadata(db, document.id)
        if doc_metadata:
            metadata = create_metadata_response(doc_metadata)
        
        return api_requests.DocumentMetadataResponse(
            id=document.id,
            owner=document.owner,
            filename=document.filename,
            template_id=document.template_id,
            folder_id=document.folder_id,
            status=create_document_response(document).status,
            processing_error=getattr(document, 'processing_error', None),
            has_metadata=document.document_metadata is not None,
            has_file=bool(document.stored_path and Path(document.stored_path).exists()),
            created_at=document.created_at,
            metadata=metadata
        )
    finally:
        db.close()


@app.delete(
    "/documents/{document_id}",
    response_model=api_requests.DocumentDeleteResponse,
    summary="Delete document",
    description="Delete document by ID"
)
async def delete_document(
    document_id: int,
    authorization: str = Header(...)
):
    """
    Delete document by ID
    - document_id: ID of the document to delete
    Authentication token automatically extracted from Authorization header
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authentication scheme")
    token = authorization.replace("Bearer ", "")
    user, db = get_user_from_token(token)
    try:
        document = database.get_document(db, document_id=document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        
        verify_document_ownership(user, document)
        stored_path = document.stored_path
        database.delete_document(db, document.id)
        try_remove_file(stored_path)
        
        return api_requests.DocumentDeleteResponse(
            success=True,
            message="Document deleted successfully"
        )
    finally:
        db.close()

# ============ METADATA ENDPOINTS ============

@app.post(
    "/documents/{document_id}/analyze",
    response_model=api_requests.DocumentResponse,
    summary="Start metadata analysis",
    description="Start asynchronous metadata extraction for a parsed document"
)
async def analyze_document(
    document_id: int,
    background_tasks: BackgroundTasks,
    authorization: str = Header(...)
):
    """Queue GPU extraction and return immediately with the current status."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authentication scheme")
    token = authorization.replace("Bearer ", "")
    user, db = get_user_from_token(token)
    try:
        document = database.get_document(db, document_id=document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        verify_document_ownership(user, document)

        if document.document_metadata is not None:
            return create_document_response(document)
        if database.get_parsed_document(db, document_id) is None:
            if document.processing_status == 'processing':
                raise HTTPException(status_code=409, detail="Document is still being prepared")
            raise HTTPException(status_code=400, detail="Document is not ready for analysis")
        if document.processing_status == 'processing':
            raise HTTPException(status_code=409, detail="Analysis is already running")

        document = database.update_document(
            db,
            document.id,
            processing_status='processing',
            processing_error=None
        )
        background_tasks.add_task(process_metadata_extraction, document.id)
        return create_document_response(document)
    finally:
        db.close()

@app.patch(
    "/documents/{document_id}/metadata",
    response_model=api_requests.DocumentMetadataResponse,
    summary="Edit metadata",
    description="Save manually edited metadata fields"
)
async def update_document_metadata(
    document_id: int,
    metadata_data: api_requests.MetadataUpdateRequest,
    authorization: str = Header(...)
):
    """Replace the editable metadata object for an owned document."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authentication scheme")
    token = authorization.replace("Bearer ", "")
    user, db = get_user_from_token(token)
    try:
        document = database.get_document(db, document_id=document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        verify_document_ownership(user, document)

        metadata = database.update_metadata(
            db,
            document_id=document.id,
            fields=metadata_data.fields
        )
        database.update_document(
            db,
            document.id,
            processing_status='extracted',
            processing_error=None
        )
        return api_requests.DocumentMetadataResponse(
            id=document.id,
            owner=document.owner,
            filename=document.filename,
            template_id=document.template_id,
            folder_id=document.folder_id,
            status='extracted',
            processing_error=None,
            has_metadata=True,
            has_file=bool(document.stored_path and Path(document.stored_path).exists()),
            created_at=document.created_at,
            metadata=create_metadata_response(metadata)
        )
    finally:
        db.close()

@app.post(
    "/documents/{document_id}/metadata",
    response_model=api_requests.MetadataExtractResponse,
    summary="Extract metadata",
    description="Extract metadata to a document"
)
async def extract_metadata(
    document_id: int,
    authorization: str = Header(...)
):
    """
    Extract metadata from the document
    - document_id: ID of the document
    Authentication token automatically extracted from Authorization header
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authentication scheme")
    token = authorization.replace("Bearer ", "")
    user, db = get_user_from_token(token)
    try:
        document = database.get_document(db, document_id=document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        
        verify_document_ownership(user, document)
        
        parsed_doc = database.get_parsed_document(db, document_id)
        if not parsed_doc:
            raise HTTPException(status_code=400, detail="Document has not been parsed yet")
        
        document_ir = None
        if parsed_doc.document_ir:
            from src.document_ir import DocumentIR
            document_ir = DocumentIR.model_validate(parsed_doc.document_ir)

        start_time = datetime.now()
        try:
            extracted_data = extract_contract_key_data(
                text=parsed_doc.text,
                document_ir=document_ir,
                max_new_tokens=4096  # Increased from default 2048
            )
        except ValueError as e:
            raise HTTPException(
                status_code=422,
                detail=f"Model could not process this document properly. Please try again."
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to extract metadata: {str(e)}"
            )
        
        extraction_time = (datetime.now() - start_time).total_seconds()
        
        metadata = database.create_metadata(db, document_id=document_id, fields=extracted_data)
        database.update_document(
            db,
            document.id,
            processing_status='extracted',
            processing_error=None
        )
        
        existing_stats = database.get_stats(db, document_id=document_id)
        if existing_stats:
            latest_stat = existing_stats[-1] if isinstance(existing_stats, list) else existing_stats
            database.update_stats(
                db,
                latest_stat.id,
                extracting_time=extraction_time,
                completion_tokens=(latest_stat.completion_tokens or 0) + len(str(extracted_data).split()),
                total_tokens=(latest_stat.total_tokens or 0) + len(str(extracted_data).split())
            )
        
        return api_requests.MetadataExtractResponse(
            success=True,
            message="Metadata extracted successfully",
            metadata_id=metadata.id,
            metadata=create_metadata_response(metadata)
        )
    finally:
        db.close()
        
# ============ ADMIN ENDPOINTS ============

@app.get(
    "/stats",
    response_model=api_requests.StatsResponse,
    summary="Get statistics",
    description="Get extraction statistics (admin only)"
)
async def get_stats(
    period_days: Optional[int] = 30,
    authorization: str = Header(...)
):
    """
    Get extraction stats for admins
    - period_days: Number of days to include in stats (default 30)
    Includes token usage, document processing metrics, etc.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authentication scheme")
    token = authorization.replace("Bearer ", "")
    _, db = get_admin_from_token(token)
    try:
        period_days = period_days or 30
        end_date = datetime.now()
        start_date = end_date - timedelta(days=period_days)
        
        documents = database.get_documents_by_period(db, start_date, end_date)
        stats = database.get_stats_by_period(db, start_date, end_date)
        metadata = database.get_metadata_by_period(db, start_date, end_date)
        parsed_docs = database.get_parsed_documents_by_period(db, start_date, end_date)
        
        parsing_times = [s.parsing_time for s in stats if s.parsing_time]
        extraction_times = [s.extracting_time for s in stats if s.extracting_time]
        
        documents_per_day = {}
        for doc in documents:
            day_key = doc.created_at.strftime("%Y-%m-%d")
            documents_per_day[day_key] = documents_per_day.get(day_key, 0) + 1
        
        return api_requests.StatsResponse(
            total_documents=len(documents),
            total_users=len(database.get_all_users(db)),
            total_parsed_documents=len(parsed_docs),
            total_metadata_extractions=len(metadata),
            total_tokens_used=sum(s.total_tokens for s in stats) if stats else 0,
            average_parsing_time=round(sum(parsing_times) / len(parsing_times), 2) if parsing_times else 0.0,
            average_extraction_time=round(sum(extraction_times) / len(extraction_times), 2) if extraction_times else 0.0,
            period_start=start_date,
            period_end=end_date,
            documents_per_day=documents_per_day
        )
    finally:
        db.close()

# ============ LIBRARY ENDPOINTS ============

@app.get(
    "/folders",
    response_model=api_requests.FolderListResponse,
    summary="List folders",
    description="Get folders for the current user"
)
async def list_folders(authorization: str = Header(...)):
    """List the current user's document folders."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authentication scheme")
    token = authorization.replace("Bearer ", "")
    user, db = get_user_from_token(token)
    try:
        folders = database.get_folders_by_owner(db, user.id)
        return api_requests.FolderListResponse(
            folders=[create_folder_response(folder, db) for folder in folders]
        )
    finally:
        db.close()

@app.post(
    "/folders",
    response_model=api_requests.FolderResponse,
    summary="Create folder",
    description="Create a folder for the current user"
)
async def create_folder(
    folder_data: api_requests.FolderCreateRequest,
    authorization: str = Header(...)
):
    """Create a new document folder."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authentication scheme")
    token = authorization.replace("Bearer ", "")
    user, db = get_user_from_token(token)
    try:
        name = folder_data.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="Folder name is required")
        existing = db.query(database.Folder).filter(
            database.Folder.owner == user.id,
            database.Folder.name == name
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="Folder already exists")
        folder = database.create_folder(db, owner=user.id, name=name)
        return create_folder_response(folder, db)
    finally:
        db.close()

@app.patch(
    "/folders/{folder_id}",
    response_model=api_requests.FolderResponse,
    summary="Rename folder",
    description="Rename a folder owned by the current user"
)
async def rename_folder(
    folder_id: int,
    folder_data: api_requests.FolderUpdateRequest,
    authorization: str = Header(...)
):
    """Rename a document folder."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authentication scheme")
    token = authorization.replace("Bearer ", "")
    user, db = get_user_from_token(token)
    try:
        folder = database.get_folder(db, folder_id)
        if not folder or folder.owner != user.id:
            raise HTTPException(status_code=404, detail="Folder not found")
        name = folder_data.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="Folder name is required")
        folder = database.update_folder(db, folder_id, name)
        return create_folder_response(folder, db)
    finally:
        db.close()

@app.delete(
    "/folders/{folder_id}",
    response_model=api_requests.DocumentDeleteResponse,
    summary="Delete folder",
    description="Delete a folder and move its documents to the root"
)
async def remove_folder(folder_id: int, authorization: str = Header(...)):
    """Delete a folder without deleting its documents."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authentication scheme")
    token = authorization.replace("Bearer ", "")
    user, db = get_user_from_token(token)
    try:
        folder = database.get_folder(db, folder_id)
        if not folder or folder.owner != user.id:
            raise HTTPException(status_code=404, detail="Folder not found")
        database.delete_folder(db, folder_id)
        return api_requests.DocumentDeleteResponse(
            success=True,
            message="Folder deleted and documents moved to the root"
        )
    finally:
        db.close()

@app.patch(
    "/documents/{document_id}",
    response_model=api_requests.DocumentResponse,
    summary="Move document",
    description="Move a document to a folder or back to the root"
)
async def update_document(
    document_id: int,
    document_data: api_requests.DocumentUpdateRequest,
    authorization: str = Header(...)
):
    """Move a document between folders."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authentication scheme")
    token = authorization.replace("Bearer ", "")
    user, db = get_user_from_token(token)
    try:
        document = database.get_document(db, document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        verify_document_ownership(user, document)
        if document_data.folder_id is not None:
            folder = database.get_folder(db, document_data.folder_id)
            if not folder or folder.owner != user.id:
                raise HTTPException(status_code=404, detail="Folder not found")
        document = database.update_document(
            db, document_id, folder_id=document_data.folder_id
        )
        return create_document_response(document)
    finally:
        db.close()

@app.get(
    "/documents/{document_id}/file",
    summary="Open document file",
    description="Return the original uploaded document"
)
async def get_document_file(document_id: int, authorization: str = Header(...)):
    """Return the original file for an owned document."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authentication scheme")
    token = authorization.replace("Bearer ", "")
    user, db = get_user_from_token(token)
    try:
        document = database.get_document(db, document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        verify_document_ownership(user, document)
        if not document.stored_path or not Path(document.stored_path).exists():
            raise HTTPException(status_code=404, detail="Original file is not available")
        media_type = mimetypes.guess_type(document.filename or '')[0] or 'application/octet-stream'
        return FileResponse(
            document.stored_path,
            media_type=media_type,
            filename=document.filename or 'document'
        )
    finally:
        db.close()
