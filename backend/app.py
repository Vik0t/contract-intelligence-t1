import logging
import traceback
import html
import io
from copy import deepcopy
from datetime import datetime, timedelta
import mimetypes
import os
import shutil
import tempfile
import threading
import bcrypt
import httpx
import pymupdf
from PIL import Image, ImageOps
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, File, Form, HTTPException, Header, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from starlette.concurrency import run_in_threadpool

import backend.database as database
import backend.api_requests as api_requests
from backend.config import get_settings
from backend.file_validation import UploadValidationError, validate_document_file
from backend.extraction import ExtractionService
from backend.jobs import JobManager
from backend.document_view import ViewUnavailable, locate_evidence, page_count as visual_page_count, render_page, view_pdf_path

from src.local_extraction import extract_text_from_document
from src.extraction.summary import summarize_document
from src.extraction.risks import analyze_risks

settings = get_settings()
EXTRACTION_SERVICE = ExtractionService(settings)


@asynccontextmanager
async def lifespan(_app):
    """Recover durable jobs on startup and stop workers on shutdown."""
    JOB_MANAGER.recover()
    try:
        yield
    finally:
        JOB_MANAGER.shutdown()
        from src.extraction.api_models import close_api_clients
        close_api_clients()


app = FastAPI(
    title="T1 Contract Intelligence",
    description="Extracting important info from contracts",
    version="1.1.0",
    root_path=os.getenv("API_ROOT_PATH", ""),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

engine = database.get_engine(settings.database_url)
database.create_tables(engine)

STORAGE_ROOT = Path(settings.document_storage_dir)
STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
PROCESSING_LOCK = threading.Lock()

@app.get("/ping")
async def ping():
    return "pong!"


@app.get("/health/ready", include_in_schema=False)
async def readiness():
    from sqlalchemy import text
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    # Weight and GPU checks run once in scripts.serve before this process starts.
    return {"status": "ready", "database": "ok", "extraction": settings.extraction_backend}


@app.get("/", include_in_schema=False)
async def service_root(request: Request):
    """Small API landing response for direct browser visits."""
    return {
        "service": "T1 Contract Intelligence API",
        "status": "ok",
        "docs": f"{request.scope.get('root_path', '')}/docs",
        "health": f"{request.scope.get('root_path', '')}/ping",
    }


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Avoid noisy 404s when a browser probes the API root."""
    return Response(status_code=204)

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
        review_status=getattr(document, 'review_status', None) or 'pending',
        reviewed_at=getattr(document, 'reviewed_at', None),
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
        summary=getattr(metadata, 'summary', None),
        risks=getattr(metadata, 'risks', None),
        created_at=metadata.created_at
    )


def insight_error_message(exc: Exception, kind: str) -> str:
    label = 'сводку' if kind == 'summary' else 'риски'
    provider = os.getenv('SUMMARY_PROVIDER' if kind == 'summary' else 'RISK_PROVIDER', 'hf').lower()
    service = 'DeepCode API' if provider == 'deepcode' else 'сервис анализа'
    if isinstance(exc, database.MetadataChangedError):
        return 'Поля изменились во время анализа. Обновите сводку и риски для сохранённых данных.'
    if isinstance(exc, RuntimeError) and 'резервный Hugging Face' in str(exc):
        return f'Не удалось обновить {label}: основной и резервный сервисы недоступны. Повторите попытку позже.'
    if isinstance(exc, (httpx.ConnectError, httpx.TimeoutException)):
        return f'Не удалось обновить {label}: {service} недоступен или не отвечает. Проверьте соединение.'
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in (401, 403):
            return f'Не удалось обновить {label}: ключ {service} отклонён.'
        if status == 404:
            return f'Не удалось обновить {label}: модель или адрес {service} не найдены.'
        return f'Не удалось обновить {label}: {service} ответил с ошибкой {status}.'
    return f'Не удалось обновить {label}. Попробуйте ещё раз или обратитесь к администратору.'


def readable_document_pages(parsed_document):
    """Return user-facing page text without parser implementation details."""
    document_ir = parsed_document.document_ir or {}
    pages = []
    for page_index, page in enumerate(document_ir.get('pages') or []):
        blocks = page.get('blocks') or []
        if page.get('needs_ocr'):
            ocr_blocks = [block for block in blocks if block.get('source') == 'ocr']
            if ocr_blocks:
                blocks = ocr_blocks
        blocks = sorted(
            blocks,
            key=lambda block: (
                block.get('order') is None,
                block.get('order') or 0,
                (block.get('bbox') or {}).get('y0') or 0,
                (block.get('bbox') or {}).get('x0') or 0,
            ),
        )
        text = '\n\n'.join(
            str(block.get('text') or '').strip()
            for block in blocks
            if str(block.get('text') or '').strip()
        )
        pages.append({
            'number': page.get('number') or page_index + 1,
            'text': text,
        })
    if not pages:
        pages = [{'number': 1, 'text': parsed_document.text}]
    return pages, document_ir.get('source_format')


def create_text_preview_svg(filename: str, text: str) -> bytes:
    """Create a lightweight first-page preview when a native render is unavailable."""
    raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
    lines = [filename[:48], *raw_lines[:11]]
    text_nodes = []
    for index, line in enumerate(lines):
        safe_line = html.escape(line[:64])
        weight = '700' if index == 0 else '400'
        size = '18' if index == 0 else '12'
        text_nodes.append(
            f'<text x="30" y="{48 + index * 25}" font-family="Arial, sans-serif" '
            f'font-size="{size}" font-weight="{weight}" fill="#25282c">{safe_line}</text>'
        )
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="360" height="480" viewBox="0 0 360 480">'
        '<rect width="360" height="480" fill="#ffffff"/>'
        '<rect x="0" y="0" width="8" height="480" fill="#18aef0"/>'
        f'{"".join(text_nodes)}'
        '</svg>'
    )
    return svg.encode('utf-8')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def process_document_parsing(document_id: int):
    """Parse an uploaded file outside the upload request."""
    db = database.get_session(engine)
    try:
        document = database.get_document(db, document_id)
        if not document or not document.stored_path:
            logger.error(f"Document {document_id} not found or no stored path")
            return
        stored_path = document.stored_path
        logger.info(f"Starting to parse document {document_id}: {stored_path}")

        try:
            with PROCESSING_LOCK:
                started_at = datetime.now()
                logger.info(f"Calling extract_text_from_document for {document_id}")
                parse_path = stored_path
                if Path(stored_path).suffix.lower() == '.docx' and os.getenv('DOCX_USE_RENDERED_PAGES', 'false').lower() == 'true':
                    parse_path = view_pdf_path(stored_path)
                parsed_text, document_ir = extract_text_from_document(parse_path)
                if str(parse_path) != str(stored_path):
                    from src.document_ir import SourceFormat
                    document_ir.source_format = SourceFormat.DOCX
                    document_ir.source_path = str(stored_path)
                parsing_time = (datetime.now() - started_at).total_seconds()
                logger.info(f"Document {document_id} parsed successfully in {parsing_time:.2f}s. Text length: {len(parsed_text)}")

            if database.get_document(db, document_id) is None:
                logger.warning(f"Document {document_id} was deleted during parsing")
                try_remove_file(stored_path)
                return

            document_ir_dict = document_ir.model_dump() if document_ir else None
            database.update_parsed_document(
                db,
                document_id=document_id,
                text=parsed_text,
                document_ir=document_ir_dict
            )
            logger.info(f"Parsed document {document_id} saved to database")

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
            logger.info(f"Document {document_id} status updated to 'ready'")
        except Exception as e:
            logger.error(f"Error parsing document {document_id}: {str(e)}")
            logger.error(traceback.format_exc())
            if database.get_document(db, document_id) is not None:
                database.update_document(
                    db,
                    document_id,
                    processing_status='failed',
                    processing_error='Не удалось подготовить документ к анализу. Повторите попытку позже.'
                )
            else:
                try_remove_file(stored_path)
    except Exception as e:
        logger.error(f"Critical error in process_document_parsing for {document_id}: {str(e)}")
        logger.error(traceback.format_exc())
        if database.get_document(db, document_id) is not None:
            database.update_document(
                db,
                document_id,
                processing_status='failed',
                processing_error='Не удалось подготовить документ к анализу. Повторите попытку позже.'
            )
    finally:
        db.close()


def process_metadata_extraction(document_id: int):
    """Run the GPU extraction job and persist its result."""
    db = database.get_session(engine)
    try:
        document = database.get_document(db, document_id)
        parsed_doc = database.get_parsed_document(db, document_id)
        if not document or not parsed_doc:
            logger.error(f"Document {document_id} or parsed document not found")
            return
        logger.info(f"Starting metadata extraction for document {document_id}")

        try:
            document_ir = None
            if parsed_doc.document_ir:
                from src.document_ir import DocumentIR
                document_ir = DocumentIR.model_validate(parsed_doc.document_ir)
                logger.info(f"DocumentIR loaded for {document_id}")

            with PROCESSING_LOCK:
                started_at = datetime.now()
                logger.info(f"Calling extract_contract_key_data for {document_id}")

                extracted_data, token_usage = EXTRACTION_SERVICE.extract(
                    text=parsed_doc.text,
                    document_ir=document_ir,
                    max_new_tokens=4096,
                    collect_stats=True
                )
                extraction_time = (datetime.now() - started_at).total_seconds()
                logger.info(f"Extraction completed in {extraction_time:.2f}s. Tokens: {token_usage}")

            if database.get_document(db, document_id) is None:
                logger.warning(f"Document {document_id} was deleted during extraction")
                return

            metadata = database.update_metadata(
                db,
                document_id=document_id,
                fields=extracted_data
            )
            logger.info(f"Metadata saved for document {document_id}")

            database.update_document(
                db,
                document_id,
                processing_status='extracted',
                processing_error=None,
                review_status='pending',
                reviewed_at=None,
                reviewed_by=None,
            )

            # Суммаризация — отдельный, не критичный для основного статуса шаг.
            # Если HF API недоступен/лимитирован, документ всё равно должен
            # остаться в статусе 'extracted' с полями, просто без summary.
            try:
                summary_text = summarize_document(parsed_doc.text, extracted_data)
                database.save_insights(
                    db,
                    document_id=document_id,
                    expected_fields=extracted_data,
                    summary=summary_text
                )
                logger.info(f"Summary saved for document {document_id}")
            except Exception as summary_exc:
                logger.warning(
                    f"Summary generation failed for document {document_id}: {summary_exc}"
                )
            try:
                risk_items = analyze_risks(parsed_doc.text, extracted_data)
                database.save_insights(db, document_id=document_id, expected_fields=extracted_data, risks=risk_items)
                logger.info("Risk review saved for document %s", document_id)
            except Exception as risk_exc:
                logger.warning("Risk review failed for document %s: %s", document_id, risk_exc)

            existing_stats = database.get_stats(db, document_id=document_id)
            if existing_stats:
                latest_stat = existing_stats[-1]
                database.update_stats(
                    db,
                    latest_stat.id,
                    extracting_time=extraction_time,
                    prompt_tokens=(latest_stat.prompt_tokens or 0) + token_usage["prompt_tokens"],
                    completion_tokens=(latest_stat.completion_tokens or 0) + token_usage["completion_tokens"],
                    total_tokens=(latest_stat.total_tokens or 0) + token_usage["total_tokens"]
                )
                logger.info(f"Stats updated for document {document_id}")

            logger.info(f"Document {document_id} status updated to 'extracted'")
        except Exception as e:
            logger.error(f"Error extracting metadata for document {document_id}: {str(e)}")
            logger.error(traceback.format_exc())
            if database.get_document(db, document_id) is not None:
                database.update_document(
                    db,
                    document_id,
                    processing_status='failed',
                    processing_error='Не удалось извлечь реквизиты. Повторите попытку позже.'
                )
    except Exception as e:
        logger.error(f"Critical error in process_metadata_extraction for {document_id}: {str(e)}")
        logger.error(traceback.format_exc())
        if database.get_document(db, document_id) is not None:
            database.update_document(
                db,
                document_id,
                processing_status='failed',
                processing_error='Не удалось извлечь реквизиты. Повторите попытку позже.'
            )
    finally:
        db.close()


def run_processing_job(kind: str, document_id: int) -> None:
    if kind == 'parse':
        process_document_parsing(document_id)
    elif kind == 'extract':
        process_metadata_extraction(document_id)
    else:
        raise ValueError(f'Unknown processing job kind: {kind}')


JOB_MANAGER = JobManager(
    engine,
    run_processing_job,
    max_workers=settings.job_worker_count,
    max_attempts=settings.max_job_attempts,
    stale_after_minutes=settings.job_stale_after_minutes,
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
        stored_paths = [
            document.stored_path
            for document in db.query(database.Document).filter(
                database.Document.owner == user.id
            ).all()
            if document.stored_path
        ]
        database.delete_user(db, user.id)
        for stored_path in stored_paths:
            try_remove_file(stored_path)
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
    status_code=202,
    summary="Upload document",
    description="Upload a new document for processing"
)
async def upload_document(
    file: UploadFile = File(...),
    template_id: Optional[int] = Form(None),
    folder_id: Optional[int] = Form(None),
    authorization: str = Header(...)
):
    """
    Upload a new document
    - file: PDF, DOCX, JPG or PNG file to upload
    - template_id: ID of the template to use (optional)
    Authentication token automatically extracted from Authorization header
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authentication scheme")
    token = authorization.replace("Bearer ", "")
    
    user, _ = get_user_from_token(token)
    _.close()
    
    filename = file.filename or ""
    file_extension = os.path.splitext(filename)[1].lower()
    if file_extension not in {'.pdf', '.docx', '.jpg', '.jpeg', '.png'}:
        raise HTTPException(
            status_code=400,
            detail="Поддерживаются PDF, DOCX, JPG и PNG"
        )
    
    temp_path = None
    try:
        temp_fd, temp_path = tempfile.mkstemp(suffix=file_extension)
        with os.fdopen(temp_fd, 'wb') as temp_file:
            total_size = 0
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > settings.upload_limit_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Файл слишком большой. Максимальный размер: {settings.max_upload_size_mb} МБ",
                    )
                temp_file.write(chunk)

        try:
            validate_document_file(
                temp_path,
                file_extension,
                max_pdf_pages=settings.max_pdf_pages,
            )
        except UploadValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        
        db = database.get_session(engine)
        document = None
        stored_path = None
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
                filename=filename,
                folder_id=folder_id
            )
            stored_path = get_document_storage_path(user.id, document.id, filename)
            shutil.copyfile(temp_path, stored_path)
            database.update_document(
                db,
                document.id,
                stored_path=str(stored_path),
                processing_status='processing',
                processing_error=None
            )
            JOB_MANAGER.enqueue(document.id, 'parse')
            
            return api_requests.DocumentUploadResponse(
                success=True,
                message="Документ загружен. Подготовка к анализу началась.",
                document_id=document.id,
                document=create_document_response(document),
                parsing_time_seconds=None
            )
        except Exception:
            if document is not None:
                database.delete_document(db, document.id)
            try_remove_file(stored_path)
            raise
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
            review_status=getattr(document, 'review_status', None) or 'pending',
            reviewed_at=getattr(document, 'reviewed_at', None),
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
        if stored_path and Path(stored_path).suffix.lower() == '.docx':
            try_remove_file(str(Path(stored_path).with_name(Path(stored_path).name + '.rendered.pdf')))
        
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
        JOB_MANAGER.enqueue(document.id, 'extract')
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

        # Previously generated conclusions may contradict the operator's edits.
        # Saving fields must remain immediate even when the analysis API is down.
        metadata.summary = None
        metadata.risks = None
        db.commit()

        database.update_document(
            db,
            document.id,
            processing_status='extracted',
            processing_error=None,
            review_status='pending',
            reviewed_at=None,
            reviewed_by=None,
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
            review_status='pending',
            reviewed_at=None,
            created_at=document.created_at,
            metadata=create_metadata_response(metadata)
        )
    finally:
        db.close()


@app.patch(
    "/documents/{document_id}/review",
    response_model=api_requests.DocumentMetadataResponse,
    summary="Confirm operator review",
    description="Mark extracted document data as reviewed or return it to review",
)
async def update_document_review(
    document_id: int,
    review_data: api_requests.DocumentReviewRequest,
    authorization: str = Header(...),
):
    """Persist the operator's final verification state in the database."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authentication scheme")
    token = authorization.replace("Bearer ", "")
    user, db = get_user_from_token(token)
    try:
        document = database.get_document(db, document_id=document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        verify_document_ownership(user, document)
        metadata = database.get_metadata(db, document.id)
        if not metadata:
            raise HTTPException(
                status_code=409,
                detail="Сначала дождитесь извлечения данных",
            )

        reviewed_at = datetime.now() if review_data.confirmed else None
        document = database.update_document(
            db,
            document.id,
            review_status='reviewed' if review_data.confirmed else 'pending',
            reviewed_at=reviewed_at,
            reviewed_by=user.id if review_data.confirmed else None,
        )
        return api_requests.DocumentMetadataResponse(
            **create_document_response(document).model_dump(),
            metadata=create_metadata_response(metadata),
        )
    finally:
        db.close()


@app.post(
    "/documents/{document_id}/metadata",
    response_model=api_requests.MetadataExtractResponse,
    status_code=202,
    summary="Queue metadata extraction",
    description="Queue metadata extraction and poll the document endpoint for the result"
)
async def extract_metadata(
        document_id: int,
        authorization: str = Header(...)
):
    """Backward-compatible async alias for ``/documents/{id}/analyze``."""
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
            metadata = create_metadata_response(document.document_metadata)
            return api_requests.MetadataExtractResponse(
                success=True,
                message="Metadata already extracted",
                metadata_id=metadata.id,
                metadata=metadata,
            )
        if database.get_parsed_document(db, document_id) is None:
            if document.processing_status == 'processing':
                raise HTTPException(status_code=409, detail="Document is still being prepared")
            raise HTTPException(status_code=400, detail="Document is not ready for analysis")

        database.update_document(
            db,
            document.id,
            processing_status='processing',
            processing_error=None,
        )
        JOB_MANAGER.enqueue(document.id, 'extract')
        return api_requests.MetadataExtractResponse(
            success=True,
            message="Извлечение поставлено в очередь. Получите результат через GET /documents/{id}.",
            metadata_id=None,
            metadata=None,
        )
    finally:
        db.close()
        
# ============ ADMIN ENDPOINTS ============

@app.get(
    "/stats",
    response_model=api_requests.StatsResponse,
    summary="Get statistics",
    description="Get extraction statistics for the current user"
)
async def get_stats(
        period_days: Optional[int] = 30,
        authorization: str = Header(...)
):
    """
    Get extraction stats for the current user
    - period_days: Number of days to include in stats (default 30)
    Includes token usage, document processing metrics, etc.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authentication scheme")
    token = authorization.replace("Bearer ", "")
    user, db = get_user_from_token(token)
    try:
        period_days = period_days or 30
        end_date = datetime.now()
        start_date = end_date - timedelta(days=period_days)

        # Get user's documents
        documents = db.query(database.Document).filter(
            database.Document.owner == user.id,
            database.Document.created_at >= start_date,
            database.Document.created_at <= end_date
        ).all()

        # Get stats for user's documents
        document_ids = [doc.id for doc in documents]
        stats = []
        if document_ids:
            stats = db.query(database.Stats).filter(
                database.Stats.document_id.in_(document_ids),
                database.Stats.created_at >= start_date,
                database.Stats.created_at <= end_date
            ).all()

        # Get metadata for user's documents
        metadata = []
        if document_ids:
            metadata = db.query(database.DocumentMetadata).filter(
                database.DocumentMetadata.document_id.in_(document_ids),
                database.DocumentMetadata.created_at >= start_date,
                database.DocumentMetadata.created_at <= end_date
            ).all()

        # Get parsed documents for user
        parsed_docs = []
        if document_ids:
            parsed_docs = db.query(database.ParsedDocument).filter(
                database.ParsedDocument.document_id.in_(document_ids),
                database.ParsedDocument.created_at >= start_date,
                database.ParsedDocument.created_at <= end_date
            ).all()

        parsing_times = [s.parsing_time for s in stats if s.parsing_time]
        extraction_times = [s.extracting_time for s in stats if s.extracting_time]

        documents_per_day = {}
        for doc in documents:
            day_key = doc.created_at.strftime("%Y-%m-%d")
            documents_per_day[day_key] = documents_per_day.get(day_key, 0) + 1

        return api_requests.StatsResponse(
            total_documents=len(documents),
            total_users=1,  # Just this user
            total_parsed_documents=len(parsed_docs),
            total_metadata_extractions=len(metadata),
            total_tokens_used=sum(s.total_tokens or 0 for s in stats),
            average_parsing_time=round(sum(parsing_times) / len(parsing_times), 2) if parsing_times else 0.0,
            average_extraction_time=round(sum(extraction_times) / len(extraction_times),
                                          2) if extraction_times else 0.0,
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
    "/documents/{document_id}/content",
    response_model=api_requests.DocumentContentResponse,
    response_model_exclude_none=True,
    summary="Read parsed document content",
    description="Return document text grouped by page for source verification",
)
async def get_document_content(document_id: int, authorization: str = Header(...)):
    """Return owned parsed content without parser confidence or pipeline details."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authentication scheme")
    token = authorization.replace("Bearer ", "")
    user, db = get_user_from_token(token)
    try:
        document = database.get_document(db, document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        verify_document_ownership(user, document)
        parsed_document = database.get_parsed_document(db, document_id)
        if not parsed_document:
            raise HTTPException(status_code=409, detail="Document is still being prepared")
        pages, source_format = readable_document_pages(parsed_document)
        visual_count = None
        visual_error = None
        if document.stored_path and Path(document.stored_path).is_file() and source_format in {'pdf', 'docx', 'image'}:
            try:
                visual_count = visual_page_count(document.stored_path)
            except (ViewUnavailable, OSError, ValueError) as exc:
                logger.warning("Visual preview unavailable for document %s: %s", document_id, exc)
                visual_error = str(exc)
        return api_requests.DocumentContentResponse(
            source_format=source_format,
            page_count=len(pages),
            pages=pages,
            visual_page_count=visual_count,
            visual_error=visual_error,
        )
    finally:
        db.close()


@app.get('/documents/{document_id}/pages/{page_number}/image', summary='Render original document page')
async def get_document_page_image(document_id: int, page_number: int, authorization: str = Header(...)):
    if not authorization.startswith('Bearer '):
        raise HTTPException(status_code=401, detail='Invalid authentication scheme')
    user, db = get_user_from_token(authorization.removeprefix('Bearer '))
    try:
        document = database.get_document(db, document_id)
        if not document:
            raise HTTPException(status_code=404, detail='Document not found')
        verify_document_ownership(user, document)
        if not document.stored_path or not Path(document.stored_path).is_file():
            raise HTTPException(status_code=404, detail='Original file is not available')
        try:
            image = render_page(document.stored_path, page_number)
        except IndexError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ViewUnavailable, OSError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return Response(content=image, media_type='image/png', headers={'Cache-Control': 'private, max-age=3600'})
    finally:
        db.close()


@app.post('/documents/{document_id}/source-location', summary='Locate evidence on original pages')
async def get_source_location(document_id: int, body: api_requests.SourceLocationRequest, authorization: str = Header(...)):
    if not authorization.startswith('Bearer '):
        raise HTTPException(status_code=401, detail='Invalid authentication scheme')
    user, db = get_user_from_token(authorization.removeprefix('Bearer '))
    try:
        document = database.get_document(db, document_id)
        if not document:
            raise HTTPException(status_code=404, detail='Document not found')
        verify_document_ownership(user, document)
        if not document.stored_path or not Path(document.stored_path).is_file():
            raise HTTPException(status_code=404, detail='Original file is not available')
        try:
            parsed = database.get_parsed_document(db, document_id)
            location = locate_evidence(document.stored_path, body.evidence, body.page, document_ir=parsed.document_ir if parsed else None)
        except (ViewUnavailable, OSError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if not location:
            raise HTTPException(status_code=404, detail='Фрагмент не найден в оформленном документе')
        return location
    finally:
        db.close()


@app.post('/documents/{document_id}/insights', summary='Generate summary and risk review')
async def refresh_document_insights(document_id: int, authorization: str = Header(...)):
    if not authorization.startswith('Bearer '):
        raise HTTPException(status_code=401, detail='Invalid authentication scheme')
    user, db = get_user_from_token(authorization.removeprefix('Bearer '))
    try:
        document = database.get_document(db, document_id)
        if not document:
            raise HTTPException(status_code=404, detail='Document not found')
        verify_document_ownership(user, document)
        parsed = database.get_parsed_document(db, document_id)
        metadata = database.get_metadata(db, document_id)
        if not parsed or not metadata:
            raise HTTPException(status_code=409, detail='Сначала извлеките поля договора')
        analysis_fields = deepcopy(metadata.fields)
        errors = []
        try:
            summary_text = await run_in_threadpool(summarize_document, parsed.text, analysis_fields)
            metadata = database.save_insights(db, document_id, analysis_fields, summary=summary_text)
        except Exception as exc:
            logger.warning('Summary refresh failed for document %s: %s', document_id, exc)
            errors.append(insight_error_message(exc, 'summary'))
        try:
            risks = await run_in_threadpool(analyze_risks, parsed.text, analysis_fields)
            metadata = database.save_insights(db, document_id, analysis_fields, risks=risks)
        except Exception as exc:
            logger.warning('Risk refresh failed for document %s: %s', document_id, exc)
            errors.append(insight_error_message(exc, 'risks'))
        return {'metadata': create_metadata_response(metadata), 'errors': errors}
    finally:
        db.close()


@app.get(
    "/documents/{document_id}/preview",
    summary="Preview document",
    description="Return a lightweight first-page preview for the document library",
)
async def get_document_preview(document_id: int, authorization: str = Header(...)):
    """Render only the first page; never send the full document to a card preview."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authentication scheme")
    token = authorization.replace("Bearer ", "")
    user, db = get_user_from_token(token)
    try:
        document = database.get_document(db, document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        verify_document_ownership(user, document)
        path = Path(document.stored_path) if document.stored_path else None
        if not path or not path.exists():
            raise HTTPException(status_code=404, detail="Original file is not available")
        if path.suffix.lower() == '.pdf':
            try:
                with pymupdf.open(path) as pdf:
                    if not pdf:
                        raise ValueError("empty pdf")
                    page = pdf[0]
                    scale = min(1.0, 360 / max(page.rect.width, 1))
                    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
                    return Response(
                        content=pixmap.tobytes('png'),
                        media_type='image/png',
                        headers={'Cache-Control': 'private, max-age=3600'},
                    )
            except Exception as exc:
                logger.warning("Could not render PDF preview for %s: %s", document_id, exc)
        if path.suffix.lower() in {'.jpg', '.jpeg', '.png'}:
            try:
                with Image.open(path) as source:
                    image = ImageOps.exif_transpose(source).convert('RGB')
                    image.thumbnail((960, 720))
                    output = io.BytesIO()
                    image.save(output, format='JPEG', quality=84, optimize=True)
                return Response(
                    content=output.getvalue(),
                    media_type='image/jpeg',
                    headers={'Cache-Control': 'private, max-age=3600'},
                )
            except Exception as exc:
                logger.warning("Could not render image preview for %s: %s", document_id, exc)
        parsed_document = database.get_parsed_document(db, document_id)
        preview_text = parsed_document.text if parsed_document else ''
        return Response(
            content=create_text_preview_svg(document.filename or 'Документ', preview_text),
            media_type='image/svg+xml',
            headers={'Cache-Control': 'private, max-age=3600'},
        )
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
