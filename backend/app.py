from datetime import datetime, timedelta
import os, tempfile, bcrypt
from fastapi import FastAPI, File, HTTPException, Depends, UploadFile

import backend.database as database
import backend.api_requests as api_requests

from src.parsing import parse_file
from src.llm import extract_contract_key_data

app = FastAPI(
    title="T1 Contract Intelligence",
    description="Extracting important info from contracts",
    version="1.0.0"
)

engine = database.get_engine()
database.create_tables(engine)

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
    return api_requests.DocumentResponse(
        id=document.id,
        owner=document.owner,
        filename=document.filename,
        template_id=document.template_id,
        created_at=document.created_at
    )

def create_metadata_response(metadata):
    """Create a MetadataResponse from a metadata object."""
    return api_requests.MetadataResponse(
        id=metadata.id,
        document_id=metadata.document_id,
        fields=metadata.fields,
        created_at=metadata.created_at
    )

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
async def get_current_user(request: api_requests.CurrentUserRequest = Depends()):
    """
    Get current user profile
    Authentication token automatically extracted from Authorization header
    """
    user, db = get_user_from_token(request.token.token)
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
async def update_current_user(update_data: api_requests.UserUpdateRequest):
    """
    Update current user profile
    - username: New username (optional)
    - email: New email (optional)
    - password: New password (optional)
    Authentication token automatically extracted from Authorization header
    """
    user, db = get_user_from_token(update_data.token.token)
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
async def delete_current_user(request: api_requests.UserDeleteRequest = Depends()):
    """
    Delete current user account
    Authentication token automatically extracted from Authorization header
    """
    user, db = get_user_from_token(request.token.token)
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
    file: UploadFile = File(...),
    document_data: api_requests.DocumentUploadRequest = Depends(api_requests.DocumentUploadRequest.as_form)
):
    """
    Upload a new document
    - file: PDF or DOCX file to upload
    - template_id: ID of the template to use
    Authentication token automatically extracted from Authorization header
    """
    user, _ = get_user_from_token(document_data.token.token)
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
            document = database.create_document(
                db,
                owner=user.id,
                template_id=document_data.template_id,
                filename=file.filename
            )
            
            start_time = datetime.now()
            try:
                parsed_text = parse_file(temp_path)
            except Exception as e:
                database.delete_document(db, document.id)
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to parse document: {str(e)}"
                )
            
            parsing_time = (datetime.now() - start_time).total_seconds()
            
            database.create_parsed_document(db, document_id=document.id, text=parsed_text)
            database.create_stats(
                db,
                document_id=document.id,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                parsing_time=parsing_time,
                extracting_time=None
            )
            
            return api_requests.DocumentUploadResponse(
                success=True,
                message="Document uploaded and parsed successfully",
                document_id=document.id,
                document=create_document_response(document),
                parsing_time_seconds=round(parsing_time, 2)
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
async def list_documents(request: api_requests.DocumentListRequest = Depends()):
    """
    Get all documents for current user
    - page: Page number for pagination
    - limit: Items per page
    Authentication token automatically extracted from Authorization header
    """
    user, db = get_user_from_token(request.token.token)
    try:
        page = request.page or 1
        limit = request.limit or 50
        
        documents, total = database.get_documents_by_owner_paginated(
            db, 
            owner_id=user.id,
            page=page,
            limit=limit
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
async def get_document(request: api_requests.DocumentGetRequest = Depends()):
    """
    Get document by ID with its metadata
    - document_id: ID of the document to retrieve
    Authentication token automatically extracted from Authorization header
    """
    user, db = get_user_from_token(request.token.token)
    try:
        document = database.get_document(db, document_id=request.document_id)
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
async def delete_document(request: api_requests.DocumentDeleteRequest = Depends()):
    """
    Delete document by ID
    - document_id: ID of the document to delete
    Authentication token automatically extracted from Authorization header
    """
    user, db = get_user_from_token(request.token.token)
    try:
        document = database.get_document(db, document_id=request.document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        
        verify_document_ownership(user, document)
        database.delete_document(db, document.id)
        
        return api_requests.DocumentDeleteResponse(
            success=True,
            message="Document deleted successfully"
        )
    finally:
        db.close()

# ============ METADATA ENDPOINTS ============

@app.post(
    "/documents/{document_id}/metadata",
    response_model=api_requests.MetadataParseResponse,
    summary="Parse metadata",
    description="Parse metadata to a document"
)
async def parse_metadata(
    document_id: int,
    request: api_requests.MetadataParseRequest = Depends()
):
    """
    Parse metadata to a document
    - document_id: ID of the document
    Authentication token automatically extracted from Authorization header
    """
    user, db = get_user_from_token(request.token.token)
    try:
        document = database.get_document(db, document_id=document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        
        verify_document_ownership(user, document)
        
        parsed_doc = database.get_parsed_document(db, document_id)
        if not parsed_doc:
            raise HTTPException(status_code=400, detail="Document has not been parsed yet")
        
        start_time = datetime.now()
        try:
            extracted_data = extract_contract_key_data(parsed_doc.text)
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to extract metadata: {str(e)}"
            )
        
        extraction_time = (datetime.now() - start_time).total_seconds()
        
        metadata = database.create_metadata(db, document_id=document_id, fields=extracted_data)
        
        existing_stats = database.get_stats(db, document_id=document_id)
        if existing_stats:
            latest_stat = existing_stats[-1] if isinstance(existing_stats, list) else existing_stats
            database.update_stats(
                db,
                latest_stat.id,
                extracting_time=extraction_time,
                completion_tokens=latest_stat.completion_tokens + len(str(extracted_data).split()),
                total_tokens=latest_stat.total_tokens + len(str(extracted_data).split())
            )
        
        return api_requests.MetadataParseResponse(
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
async def get_stats(request: api_requests.StatsRequest = Depends()):
    """
    Get extraction stats for admins
    - period_days: Number of days to include in stats (default 30)
    Includes token usage, document processing metrics, etc.
    """
    _, db = get_admin_from_token(request.token.token)
    try:
        period_days = request.period_days or 30
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