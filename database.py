from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Text, JSON, CheckConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.sql import func
from datetime import datetime, timedelta
import secrets

Base = declarative_base()

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
        return secrets.token_urlsafe(32)

    @staticmethod
    def create_expiry(days=7):
        return datetime.now() + timedelta(days=days)

class Template(Base):
    __tablename__ = 'templates'
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    fields = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=func.now())

class Document(Base):
    __tablename__ = 'documents'
    id = Column(Integer, primary_key=True)
    owner = Column(Integer, ForeignKey('users.id'))
    filename = Column(String(255))
    template_id = Column(Integer, ForeignKey('templates.id'), nullable=False)
    path = Column(String(500), nullable=False)
    created_at = Column(DateTime, default=func.now())
    metadata = relationship('DocumentMetadata', backref='document', uselist=False)

class DocumentMetadata(Base):
    __tablename__ = 'document_metadata'
    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey('documents.id', ondelete='CASCADE'), unique=True)
    fields = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=func.now())

class TokenUsage(Base):
    __tablename__ = 'token_usage'
    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey('documents.id', ondelete='SET NULL'))
    prompt_tokens = Column(Integer)
    completion_tokens = Column(Integer)
    total_tokens = Column(Integer)
    created_at = Column(DateTime, default=func.now())

def get_engine(db_path='sqlite:///documents.db'):
    return create_engine(db_path, echo=False)

def create_tables(engine):
    Base.metadata.create_all(engine)

def get_session(engine):
    Session = sessionmaker(bind=engine)
    return Session()

def create_user(session, username, email, password_hash, role='user'):
    user = User(username=username, email=email, password_hash=password_hash, role=role)
    session.add(user)
    session.commit()
    return user

def get_user(session, user_id=None, username=None, email=None):
    query = session.query(User)
    if user_id:
        return query.filter(User.id == user_id).first()
    if username:
        return query.filter(User.username == username).first()
    if email:
        return query.filter(User.email == email).first()
    return None

def get_all_users(session):
    return session.query(User).all()

def update_user(session, user_id, **kwargs):
    user = get_user(session, user_id=user_id)
    if user:
        for key, value in kwargs.items():
            if hasattr(user, key):
                setattr(user, key, value)
        session.commit()
    return user

def delete_user(session, user_id):
    user = get_user(session, user_id=user_id)
    if user:
        session.delete(user)
        session.commit()
    return user

def create_session(session, user_id, days=7):
    sess = Session(
        user_id=user_id,
        session_token=Session.generate_token(),
        expires_at=Session.create_expiry(days)
    )
    session.add(sess)
    session.commit()
    return sess

def get_session_by_token(session, token):
    return session.query(Session).filter(
        Session.session_token == token,
        Session.expires_at > datetime.now()
    ).first()
    

def create_template(session, name, fields):
    template = Template(name=name, fields=fields)
    session.add(template)
    session.commit()
    return template

def get_template(session, template_id=None, name=None):
    query = session.query(Template)
    if template_id:
        return query.filter(Template.id == template_id).first()
    if name:
        return query.filter(Template.name == name).first()
    return None

def get_all_templates(session):
    return session.query(Template).all()

def update_template(session, template_id, **kwargs):
    template = get_template(session, template_id=template_id)
    if template:
        for key, value in kwargs.items():
            if hasattr(template, key):
                setattr(template, key, value)
        session.commit()
    return template

def delete_template(session, template_id):
    template = get_template(session, template_id=template_id)
    if template:
        session.delete(template)
        session.commit()
    return template

def create_document(session, owner, template_id, path, filename=None):
    doc = Document(owner=owner, template_id=template_id, path=path, filename=filename)
    session.add(doc)
    session.commit()
    return doc

def get_document(session, document_id):
    return session.query(Document).filter(Document.id == document_id).first()

def get_documents_by_owner(session, owner_id):
    return session.query(Document).filter(Document.owner == owner_id).all()

def get_documents_by_template(session, template_id):
    return session.query(Document).filter(Document.template_id == template_id).all()

def get_all_documents(session):
    return session.query(Document).all()

def update_document(session, document_id, **kwargs):
    doc = get_document(session, document_id)
    if doc:
        for key, value in kwargs.items():
            if hasattr(doc, key):
                setattr(doc, key, value)
        session.commit()
    return doc

def delete_document(session, document_id):
    doc = get_document(session, document_id)
    if doc:
        session.delete(doc)
        session.commit()
    return doc

def create_metadata(session, document_id, fields):
    metadata = DocumentMetadata(document_id=document_id, fields=fields)
    session.add(metadata)
    session.commit()
    return metadata

def get_metadata(session, document_id):
    return session.query(DocumentMetadata).filter(DocumentMetadata.document_id == document_id).first()

def update_metadata(session, document_id, fields):
    metadata = get_metadata(session, document_id)
    if metadata:
        metadata.fields = fields
        session.commit()
    else:
        metadata = create_metadata(session, document_id, fields)
    return metadata

def delete_metadata(session, document_id):
    metadata = get_metadata(session, document_id)
    if metadata:
        session.delete(metadata)
        session.commit()
    return metadata

def create_token_usage(session, document_id, prompt_tokens, completion_tokens, total_tokens):
    usage = TokenUsage(
        document_id=document_id,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens
    )
    session.add(usage)
    session.commit()
    return usage

def get_token_usage(session, usage_id=None, document_id=None):
    query = session.query(TokenUsage)
    if usage_id:
        return query.filter(TokenUsage.id == usage_id).first()
    if document_id:
        return query.filter(TokenUsage.document_id == document_id).all()
    return None

def get_all_token_usage(session):
    return session.query(TokenUsage).all()

def get_documents_with_metadata(session, owner_id=None):
    query = session.query(Document).join(DocumentMetadata)
    if owner_id:
        query = query.filter(Document.owner == owner_id)
    return query.all()