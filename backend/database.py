from sqlalchemy import Float, create_engine, Column, Integer, String, DateTime, ForeignKey, Text, JSON, CheckConstraint, Boolean, Index, inspect, text, or_, cast
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.sql import func
from datetime import datetime, timedelta
import json
import secrets

Base = declarative_base()

# ============ MODELS ============

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String(50), nullable=False, unique=True)
    email = Column(String(100), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(10), default='user')
    created_at = Column(DateTime, default=func.now())
    __table_args__ = (
        CheckConstraint("role IN ('user', 'admin')"),
    )
    sessions = relationship('Session', backref='user', lazy='dynamic')

class Session(Base):
    __tablename__ = 'sessions'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    session_token = Column(String(255), nullable=False, unique=True)
    created_at = Column(DateTime, default=func.now())
    expires_at = Column(DateTime, nullable=False)

    @staticmethod
    def generate_token():
        """Generate a secure random session token."""
        return secrets.token_urlsafe(32)

    @staticmethod
    def create_expiry(days=7):
        """Create expiration datetime for session."""
        return datetime.now() + timedelta(days=days)

class Template(Base):
    __tablename__ = 'templates'
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    fields = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=func.now())

class Folder(Base):
    __tablename__ = 'folders'
    id = Column(Integer, primary_key=True)
    owner = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    name = Column(String(120), nullable=False)
    created_at = Column(DateTime, default=func.now())

class Document(Base):
    __tablename__ = 'documents'
    id = Column(Integer, primary_key=True)
    owner = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    filename = Column(String(255))
    template_id = Column(Integer, ForeignKey('templates.id'), nullable=True)
    folder_id = Column(Integer, ForeignKey('folders.id', ondelete='SET NULL'), nullable=True)
    stored_path = Column(String(1024), nullable=True)
    processing_status = Column(String(30), nullable=False, default='uploaded')
    processing_error = Column(Text, nullable=True)
    review_status = Column(String(20), nullable=False, default='pending')
    reviewed_at = Column(DateTime, nullable=True)
    reviewed_by = Column(Integer, nullable=True)
    contract_family = Column(String(255), nullable=True)
    is_scan = Column(Boolean, default=False)
    has_tables = Column(Boolean, default=False)
    language = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=func.now())
    document_metadata = relationship('DocumentMetadata', backref='document', uselist=False)
    parsed_text = relationship('ParsedDocument', backref='document', uselist=False)

class DocumentMetadata(Base):
    __tablename__ = 'document_metadata'
    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey('documents.id', ondelete='CASCADE'), unique=True, nullable=False)
    fields = Column(JSON, nullable=False)
    summary = Column(Text, nullable=True)
    risks = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=func.now())

class Stats(Base):
    __tablename__ = 'stats'
    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey('documents.id', ondelete='SET NULL'))
    prompt_tokens = Column(Integer)
    completion_tokens = Column(Integer)
    total_tokens = Column(Integer)
    parsing_time = Column(Float, nullable=True)
    extracting_time = Column(Float, nullable=True)
    created_at = Column(DateTime, default=func.now())

class ParsedDocument(Base):
    __tablename__ = 'parsed_documents'
    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey('documents.id', ondelete='CASCADE'), unique=True, nullable=False)
    text = Column(Text, nullable=False)
    document_ir = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=func.now())


class ProcessingJob(Base):
    __tablename__ = 'processing_jobs'
    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey('documents.id', ondelete='CASCADE'), nullable=False)
    kind = Column(String(30), nullable=False)
    status = Column(String(20), nullable=False, default='queued')
    active_key = Column(String(120), nullable=True, unique=True)
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    error = Column(Text, nullable=True)
    available_at = Column(DateTime, default=func.now())
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index('ix_processing_jobs_status_available', 'status', 'available_at'),
        Index('ix_processing_jobs_document_kind', 'document_id', 'kind'),
    )

# ============ ENGINE & SESSION ============

def get_engine(db_path='sqlite:///documents.db'):
    """Create and return SQLAlchemy engine."""
    engine_kwargs = {
        "echo": False,
        "pool_pre_ping": True,
        # ensure_ascii=False: без этого json.dumps по умолчанию экранирует
        # кириллицу в \uXXXX-последовательности, и substring-поиск по
        # DocumentMetadata.fields (ILIKE на кириллице) никогда не находит
        # совпадений, хотя сами данные на месте.
        "json_serializer": lambda obj: json.dumps(obj, ensure_ascii=False),
    }
    if 'sqlite' in db_path:
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(db_path, **engine_kwargs)
    
    if 'sqlite' in db_path:
        from sqlalchemy import event
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    
    return engine

def create_tables(engine):
    """Create all database tables."""
    Base.metadata.create_all(engine)

    # Add product fields to databases created by the previous API version.
    columns = {column['name'] for column in inspect(engine).get_columns('documents')}
    with engine.begin() as connection:
        if 'folder_id' not in columns:
            connection.execute(text('ALTER TABLE documents ADD COLUMN folder_id INTEGER'))
        if 'stored_path' not in columns:
            connection.execute(text('ALTER TABLE documents ADD COLUMN stored_path VARCHAR(1024)'))
        if 'processing_status' not in columns:
            connection.execute(text("ALTER TABLE documents ADD COLUMN processing_status VARCHAR(30) NOT NULL DEFAULT 'uploaded'"))
        if 'processing_error' not in columns:
            connection.execute(text('ALTER TABLE documents ADD COLUMN processing_error TEXT'))
        if 'review_status' not in columns:
            connection.execute(text("ALTER TABLE documents ADD COLUMN review_status VARCHAR(20) NOT NULL DEFAULT 'pending'"))
        if 'reviewed_at' not in columns:
            connection.execute(text('ALTER TABLE documents ADD COLUMN reviewed_at DATETIME'))
        if 'reviewed_by' not in columns:
            connection.execute(text('ALTER TABLE documents ADD COLUMN reviewed_by INTEGER'))

    metadata_columns = {column['name'] for column in inspect(engine).get_columns('document_metadata')}
    with engine.begin() as connection:
        if 'summary' not in metadata_columns:
            connection.execute(text('ALTER TABLE document_metadata ADD COLUMN summary TEXT'))
        if 'risks' not in metadata_columns:
            connection.execute(text('ALTER TABLE document_metadata ADD COLUMN risks JSON'))

def get_session(engine):
    """Create and return a new database session."""
    Session = sessionmaker(bind=engine)
    return Session()

# ============ USER OPERATIONS ============

def create_user(session, username, email, password_hash, role='user'):
    """Create a new user."""
    user = User(username=username, email=email, password_hash=password_hash, role=role)
    session.add(user)
    session.commit()
    return user

def get_user(session, user_id=None, username=None, email=None):
    """Get a user by ID, username, or email."""
    query = session.query(User)
    if user_id:
        return query.filter(User.id == user_id).first()
    if username:
        return query.filter(User.username == username).first()
    if email:
        return query.filter(User.email == email).first()
    return None

def get_all_users(session):
    """Get all users."""
    return session.query(User).all()

def update_user(session, user_id, **kwargs):
    """Update user fields."""
    user = get_user(session, user_id=user_id)
    if user:
        for key, value in kwargs.items():
            if hasattr(user, key):
                setattr(user, key, value)
        session.commit()
    return user

def delete_user(session, user_id):
    """Delete a user and all database-owned data belonging to them."""
    user = get_user(session, user_id=user_id)
    if user:
        session.query(Session).filter(Session.user_id == user_id).delete()
        document_ids = [
            document.id
            for document in session.query(Document).filter(Document.owner == user_id).all()
        ]
        if document_ids:
            session.query(Stats).filter(Stats.document_id.in_(document_ids)).update(
                {Stats.document_id: None},
                synchronize_session=False,
            )
            session.query(ProcessingJob).filter(
                ProcessingJob.document_id.in_(document_ids)
            ).delete(synchronize_session=False)
            session.query(ParsedDocument).filter(
                ParsedDocument.document_id.in_(document_ids)
            ).delete(synchronize_session=False)
            session.query(DocumentMetadata).filter(
                DocumentMetadata.document_id.in_(document_ids)
            ).delete(synchronize_session=False)
            session.query(Document).filter(Document.id.in_(document_ids)).delete(
                synchronize_session=False
            )
        session.query(Folder).filter(Folder.owner == user_id).delete(
            synchronize_session=False
        )
        session.delete(user)
        session.commit()
    return user

# ============ SESSION OPERATIONS ============

def create_session(session, user_id, days=7):
    """Create a new session for a user."""
    sess = Session(
        user_id=user_id,
        session_token=Session.generate_token(),
        expires_at=Session.create_expiry(days)
    )
    session.add(sess)
    session.commit()
    return sess

def get_session_by_token(session, token):
    """Get a valid session by token."""
    return session.query(Session).filter(
        Session.session_token == token,
        Session.expires_at > datetime.now()
    ).first()

def delete_session_by_token(session, token):
    """Delete a session by token."""
    sess = session.query(Session).filter(Session.session_token == token).first()
    if sess:
        session.delete(sess)
        session.commit()
    return sess

# ============ TEMPLATE OPERATIONS ============

def create_template(session, name, fields):
    """Create a new template."""
    template = Template(name=name, fields=fields)
    session.add(template)
    session.commit()
    return template

def get_template(session, template_id=None, name=None):
    """Get a template by ID or name."""
    query = session.query(Template)
    if template_id:
        return query.filter(Template.id == template_id).first()
    if name:
        return query.filter(Template.name == name).first()
    return None

def get_all_templates(session):
    """Get all templates."""
    return session.query(Template).all()

def update_template(session, template_id, **kwargs):
    """Update template fields."""
    template = get_template(session, template_id=template_id)
    if template:
        for key, value in kwargs.items():
            if hasattr(template, key):
                setattr(template, key, value)
        session.commit()
    return template

def delete_template(session, template_id):
    """Delete a template."""
    template = get_template(session, template_id=template_id)
    if template:
        session.delete(template)
        session.commit()
    return template

# ============ DOCUMENT OPERATIONS ============

def create_document(session, owner, template_id, filename=None, contract_family=None,
                    is_scan=False, has_tables=False, language=None, stored_path=None,
                    folder_id=None):
    """Create a new document."""
    doc = Document(
        owner=owner, 
        template_id=template_id, 
        filename=filename,
        folder_id=folder_id,
        stored_path=stored_path,
        contract_family=contract_family,
        is_scan=is_scan,
        has_tables=has_tables,
        language=language
    )
    session.add(doc)
    session.commit()
    return doc

def get_document(session, document_id):
    """Get a document by ID."""
    return session.query(Document).filter(Document.id == document_id).first()

def get_documents_by_owner(session, owner_id):
    """Get all documents for a specific owner."""
    return session.query(Document).filter(Document.owner == owner_id).all()

def get_documents_by_owner_paginated(session, owner_id, page=1, limit=50,
                                     folder_id=None, search=None):
    """Get paginated documents for a specific owner.

    search matches both the filename and the extracted metadata fields
    (JSON column, matched as serialized text — simple substring search,
    not a structured per-field lookup).
    """
    offset = (page - 1) * limit
    query = session.query(Document).filter(Document.owner == owner_id)
    if folder_id is not None:
        query = query.filter(Document.folder_id == folder_id)
    if search:
        query = query.outerjoin(
            DocumentMetadata, DocumentMetadata.document_id == Document.id
        ).filter(
            or_(
                Document.filename.ilike(f'%{search}%'),
                cast(DocumentMetadata.fields, String).ilike(f'%{search}%'),
            )
        )
    total = query.count()
    documents = query.order_by(Document.created_at.desc()).offset(offset).limit(limit).all()
    return documents, total

def get_folders_by_owner(session, owner_id):
    """Get folders owned by a user."""
    return session.query(Folder).filter(Folder.owner == owner_id).order_by(Folder.name.asc()).all()

def get_folder(session, folder_id):
    """Get a folder by ID."""
    return session.query(Folder).filter(Folder.id == folder_id).first()

def create_folder(session, owner, name):
    """Create a folder for a user."""
    folder = Folder(owner=owner, name=name.strip())
    session.add(folder)
    session.commit()
    return folder

def update_folder(session, folder_id, name):
    """Rename a folder."""
    folder = get_folder(session, folder_id)
    if folder:
        folder.name = name.strip()
        session.commit()
    return folder

def delete_folder(session, folder_id):
    """Delete a folder and move its documents to the root."""
    folder = get_folder(session, folder_id)
    if folder:
        session.query(Document).filter(Document.folder_id == folder_id).update(
            {Document.folder_id: None}, synchronize_session=False
        )
        session.delete(folder)
        session.commit()
    return folder

def get_documents_by_template(session, template_id):
    """Get all documents using a specific template."""
    return session.query(Document).filter(Document.template_id == template_id).all()

def get_all_documents(session):
    """Get all documents."""
    return session.query(Document).all()

def get_documents_by_period(session, start_date, end_date):
    """Get documents created within a specific time period."""
    return session.query(Document).filter(
        Document.created_at >= start_date,
        Document.created_at <= end_date
    ).all()

def get_documents_with_metadata(session, owner_id=None):
    """Get documents with their metadata, optionally filtered by owner."""
    query = session.query(Document).join(DocumentMetadata)
    if owner_id:
        query = query.filter(Document.owner == owner_id)
    return query.all()

def update_document(session, document_id, **kwargs):
    """Update document fields."""
    doc = get_document(session, document_id)
    if doc:
        for key, value in kwargs.items():
            if hasattr(doc, key):
                setattr(doc, key, value)
        session.commit()
    return doc

def delete_document(session, document_id):
    """Delete a document and all related data."""
    doc = get_document(session, document_id)
    if doc:
        session.query(ProcessingJob).filter(
            ProcessingJob.document_id == document_id
        ).delete(synchronize_session=False)
        session.query(ParsedDocument).filter(ParsedDocument.document_id == document_id).delete()
        session.query(DocumentMetadata).filter(DocumentMetadata.document_id == document_id).delete()
        session.delete(doc)
        session.commit()
    return doc

# ============ METADATA OPERATIONS ============

def create_metadata(session, document_id, fields, summary=None, risks=None):
    """Create document metadata."""
    metadata = DocumentMetadata(document_id=document_id, fields=fields, summary=summary, risks=risks)
    session.add(metadata)
    session.commit()
    return metadata

def get_metadata(session, document_id):
    """Get document metadata."""
    return session.query(DocumentMetadata).filter(DocumentMetadata.document_id == document_id).first()

def get_metadata_by_period(session, start_date, end_date):
    """Get metadata created within a specific time period."""
    return session.query(DocumentMetadata).filter(
        DocumentMetadata.created_at >= start_date,
        DocumentMetadata.created_at <= end_date
    ).all()

def update_metadata(session, document_id, fields, summary=None, risks=None):
    """Update or create document metadata."""
    metadata = get_metadata(session, document_id)
    if metadata:
        metadata.fields = fields
        if summary is not None:
            metadata.summary = summary
        if risks is not None:
            metadata.risks = risks
        session.commit()
    else:
        metadata = create_metadata(session, document_id, fields, summary=summary, risks=risks)
    return metadata

def delete_metadata(session, document_id):
    """Delete document metadata."""
    metadata = get_metadata(session, document_id)
    if metadata:
        session.delete(metadata)
        session.commit()
    return metadata

# ============ STATS OPERATIONS ============

def create_stats(session, document_id, prompt_tokens, completion_tokens, total_tokens, 
                 parsing_time=None, extracting_time=None):
    """Create stats record for a document."""
    stats = Stats(
        document_id=document_id,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        parsing_time=parsing_time,
        extracting_time=extracting_time
    )
    session.add(stats)
    session.commit()
    return stats

def get_stats(session, stats_id=None, document_id=None):
    """Get stats by ID or document ID."""
    query = session.query(Stats)
    if stats_id:
        return query.filter(Stats.id == stats_id).first()
    if document_id:
        return query.filter(Stats.document_id == document_id).all()
    return None

def get_all_stats(session):
    """Get all stats records."""
    return session.query(Stats).all()

def get_stats_by_period(session, start_date, end_date):
    """Get stats within a specific time period."""
    return session.query(Stats).filter(
        Stats.created_at >= start_date,
        Stats.created_at <= end_date
    ).all()

def update_stats(session, stats_id, **kwargs):
    """Update stats fields."""
    stats = session.query(Stats).filter(Stats.id == stats_id).first()
    if stats:
        for key, value in kwargs.items():
            if hasattr(stats, key):
                setattr(stats, key, value)
        session.commit()
    return stats

def delete_stats(session, stats_id):
    """Delete stats record."""
    stats = session.query(Stats).filter(Stats.id == stats_id).first()
    if stats:
        session.delete(stats)
        session.commit()
    return stats

# ============ PARSED DOCUMENT OPERATIONS ============

def create_parsed_document(session, document_id, text, document_ir=None):
    """Create parsed document text and DocumentIR."""
    parsed = ParsedDocument(
        document_id=document_id, 
        text=text,
        document_ir=document_ir
    )
    session.add(parsed)
    session.commit()
    return parsed

def get_parsed_document(session, document_id):
    """Get parsed document by document ID."""
    return session.query(ParsedDocument).filter(ParsedDocument.document_id == document_id).first()

def get_parsed_document_by_id(session, parsed_id):
    """Get parsed document by ID."""
    return session.query(ParsedDocument).filter(ParsedDocument.id == parsed_id).first()

def get_all_parsed_documents(session):
    """Get all parsed documents."""
    return session.query(ParsedDocument).all()

def get_parsed_documents_by_period(session, start_date, end_date):
    """Get parsed documents created within a specific time period."""
    return session.query(ParsedDocument).filter(
        ParsedDocument.created_at >= start_date,
        ParsedDocument.created_at <= end_date
    ).all()

def update_parsed_document(session, document_id, text, document_ir=None):
    """Update parsed document text and DocumentIR."""
    parsed = get_parsed_document(session, document_id)
    if parsed:
        parsed.text = text
        if document_ir is not None:
            parsed.document_ir = document_ir
        session.commit()
    else:
        parsed = create_parsed_document(session, document_id, text, document_ir)
    return parsed

def delete_parsed_document(session, document_id):
    """Delete parsed document by document ID."""
    parsed = get_parsed_document(session, document_id)
    if parsed:
        session.delete(parsed)
        session.commit()
    return parsed

def delete_parsed_document_by_id(session, parsed_id):
    """Delete parsed document by ID."""
    parsed = get_parsed_document_by_id(session, parsed_id)
    if parsed:
        session.delete(parsed)
        session.commit()
    return parsed


# ============ PROCESSING JOB OPERATIONS ============

def get_job(session, job_id):
    return session.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()


def get_active_job(session, document_id, kind):
    return session.query(ProcessingJob).filter(
        ProcessingJob.document_id == document_id,
        ProcessingJob.kind == kind,
        ProcessingJob.status.in_(['queued', 'running']),
    ).order_by(ProcessingJob.id.desc()).first()


def create_job(session, document_id, kind, max_attempts=3):
    """Create an idempotent queued job for a document."""
    active = get_active_job(session, document_id, kind)
    if active:
        return active, False

    job = ProcessingJob(
        document_id=document_id,
        kind=kind,
        status='queued',
        active_key=f'{kind}:{document_id}',
        max_attempts=max_attempts,
    )
    session.add(job)
    try:
        session.commit()
    except Exception:
        session.rollback()
        active = get_active_job(session, document_id, kind)
        if active:
            return active, False
        raise
    return job, True


def recover_stale_jobs(session, stale_before):
    """Return interrupted running jobs to the durable queue."""
    return session.query(ProcessingJob).filter(
        ProcessingJob.status == 'running',
        ProcessingJob.started_at < stale_before,
    ).update(
        {
            ProcessingJob.status: 'queued',
            ProcessingJob.started_at: None,
            ProcessingJob.error: 'Восстановлено после перезапуска worker',
        },
        synchronize_session=False,
    )


def get_queued_jobs(session):
    return session.query(ProcessingJob).filter(
        ProcessingJob.status == 'queued',
        ProcessingJob.available_at <= datetime.now(),
    ).order_by(ProcessingJob.created_at.asc()).all()


def update_job(session, job_id, **kwargs):
    job = get_job(session, job_id)
    if job:
        for key, value in kwargs.items():
            if hasattr(job, key):
                setattr(job, key, value)
        session.commit()
    return job