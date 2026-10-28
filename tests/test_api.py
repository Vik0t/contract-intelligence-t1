import pytest
from fastapi.testclient import TestClient
from datetime import datetime
import io
import os
import sys
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backend.app as app_module
from backend.app import app
from backend.config import get_settings
from backend.jobs import JobManager
import backend.database as database

client = TestClient(app)

TEST_USERNAME = "testuser"
TEST_EMAIL = "test@example.com"
TEST_PASSWORD = "testpass123"
TEST_ADMIN_USERNAME = "admin_test"
TEST_ADMIN_EMAIL = "admin@example.com"
TEST_ADMIN_PASSWORD = "adminpass123"

@pytest.fixture(autouse=True)
def setup_database(tmp_path, monkeypatch):
    """Use an isolated database and storage directory for every API test."""
    previous_manager = app_module.JOB_MANAGER
    monkeypatch.setattr(app_module.settings, 'auto_extract_uploads', False)
    previous_manager.shutdown()

    engine = database.get_engine(f"sqlite:///{tmp_path / 'test.db'}")
    database.create_tables(engine)
    app_module.engine = engine
    app_module.STORAGE_ROOT = tmp_path / "uploads"
    app_module.STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    app_module.JOB_MANAGER = JobManager(
        engine,
        app_module.run_processing_job,
        max_workers=get_settings().job_worker_count,
        max_attempts=get_settings().max_job_attempts,
        stale_after_minutes=get_settings().job_stale_after_minutes,
    )
    
    db = database.get_session(engine)
    import bcrypt
    password_hash = bcrypt.hashpw(TEST_ADMIN_PASSWORD.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    database.create_user(
        db,
        username=TEST_ADMIN_USERNAME,
        email=TEST_ADMIN_EMAIL,
        password_hash=password_hash,
        role='admin'
    )
    db.close()
    yield
    app_module.JOB_MANAGER.shutdown()

def get_auth_header(username=TEST_USERNAME, email=TEST_EMAIL, password=TEST_PASSWORD):
    """Register and login, return auth header"""
    client.post("/auth/register", json={
        "username": username,
        "email": email,
        "password": password
    })
    login_response = client.post("/auth/login", json={
        "username": username,
        "password": password
    })
    token = login_response.json()["session_token"]
    return {"Authorization": f"Bearer {token}"}

def get_admin_auth_header():
    """Get admin auth header"""
    login_response = client.post("/auth/login", json={
        "username": TEST_ADMIN_USERNAME,
        "password": TEST_ADMIN_PASSWORD
    })
    token = login_response.json()["session_token"]
    return {"Authorization": f"Bearer {token}"}

# ============ BASIC HEALTH CHECK ============

def test_ping():
    """Test basic server health"""
    response = client.get("/ping")
    assert response.status_code == 200
    assert response.json() == "pong!"


def test_service_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["docs"] == "/docs"


def test_swagger_uses_reverse_proxy_prefix(monkeypatch):
    monkeypatch.setattr(app, "root_path", "/api")
    monkeypatch.setattr(app, "servers", [])
    monkeypatch.setattr(app, "openapi_schema", None)
    response = client.get("/docs")
    assert response.status_code == 200
    assert "url: '/api/openapi.json'" in response.text
    assert client.get("/").json()["docs"] == "/api/docs"
    assert client.get("/openapi.json").json()["servers"] == [{"url": "/api"}]


def test_favicon_probe_is_empty():
    response = client.get("/favicon.ico")
    assert response.status_code == 204


def test_server_timestamps_include_timezone_for_remote_browsers():
    from backend.api_requests import UserResponse
    user = UserResponse(id=1, username="operator", email="operator@example.com", role="user", created_at=datetime(2026, 10, 26, 17, 0))
    assert user.created_at.tzinfo is not None
    assert datetime.fromisoformat(user.model_dump(mode="json")["created_at"]).utcoffset() is not None

# ============ AUTHENTICATION TESTS ============

class TestAuthentication:
    """Complete authentication flow tests"""
    
    def test_register_user_success(self):
        """Test successful user registration with valid data"""
        response = client.post("/auth/register", json={
            "username": TEST_USERNAME,
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert data["user_id"] is not None
        assert "successfully" in data["message"].lower()
    
    def test_register_duplicate_username(self):
        """Test registration with duplicate username fails"""
        client.post("/auth/register", json={
            "username": TEST_USERNAME,
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        response = client.post("/auth/register", json={
            "username": TEST_USERNAME,
            "email": "different@example.com",
            "password": TEST_PASSWORD
        })
        assert response.status_code == 400
        assert "username" in response.json()["detail"].lower()
    
    def test_register_duplicate_email(self):
        """Test registration with duplicate email fails"""
        client.post("/auth/register", json={
            "username": "first_user",
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        response = client.post("/auth/register", json={
            "username": "second_user",
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        assert response.status_code in [400, 422]
        if response.status_code == 400:
            assert "email" in response.json()["detail"].lower()
    
    def test_register_invalid_username_too_short(self):
        """Test username length validation"""
        response = client.post("/auth/register", json={
            "username": "ab",
            "email": "valid@example.com",
            "password": TEST_PASSWORD
        })
        assert response.status_code == 422
    
    def test_register_invalid_username_too_long(self):
        """Test username max length"""
        response = client.post("/auth/register", json={
            "username": "a" * 51,
            "email": "valid@example.com",
            "password": TEST_PASSWORD
        })
        assert response.status_code == 422
    
    def test_register_invalid_username_special_chars(self):
        """Test username with special characters"""
        response = client.post("/auth/register", json={
            "username": "user@name!",
            "email": "valid@example.com",
            "password": TEST_PASSWORD
        })
        assert response.status_code == 422
    
    def test_register_invalid_username_with_spaces(self):
        """Test username with spaces"""
        response = client.post("/auth/register", json={
            "username": "user name",
            "email": "valid@example.com",
            "password": TEST_PASSWORD
        })
        assert response.status_code == 422
    
    def test_register_invalid_email_format(self):
        """Test invalid email formats"""
        invalid_emails = [
            "invalid-email",
            "invalid@",
            "@invalid.com",
            "invalid@.com",
            "invalid@com.",
            "",
        ]
        for email in invalid_emails:
            response = client.post("/auth/register", json={
                "username": f"user_{hash(email)}",
                "email": email,
                "password": TEST_PASSWORD
            })
            assert response.status_code == 422, f"Email '{email}' should be invalid"
    
    def test_register_invalid_password_too_short(self):
        """Test password too short"""
        response = client.post("/auth/register", json={
            "username": "validuser",
            "email": "valid@example.com",
            "password": "12345"
        })
        assert response.status_code == 422
    
    def test_register_invalid_password_special_chars(self):
        """Test password with invalid special characters"""
        response = client.post("/auth/register", json={
            "username": "validuser",
            "email": "valid@example.com",
            "password": "pass!@#"
        })
        assert response.status_code == 422
    
    def test_login_success(self):
        """Test successful login returns token"""
        client.post("/auth/register", json={
            "username": TEST_USERNAME,
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        response = client.post("/auth/login", json={
            "username": TEST_USERNAME,
            "password": TEST_PASSWORD
        })
        assert response.status_code == 200
        data = response.json()
        assert "session_token" in data
        assert len(data["session_token"]) > 0
        assert data["user"]["username"] == TEST_USERNAME
        assert data["user"]["email"] == TEST_EMAIL
        assert "id" in data["user"]
        assert "role" in data["user"]
        assert "expires_at" in data
    
    def test_login_invalid_username(self):
        """Test login with non-existent username"""
        response = client.post("/auth/login", json={
            "username": "nonexistent_user",
            "password": TEST_PASSWORD
        })
        assert response.status_code == 401
        assert "invalid" in response.json()["detail"].lower()
    
    def test_login_invalid_password(self):
        """Test login with wrong password"""
        client.post("/auth/register", json={
            "username": TEST_USERNAME,
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        response = client.post("/auth/login", json={
            "username": TEST_USERNAME,
            "password": "wrongpassword123"
        })
        assert response.status_code == 401
    
    def test_login_empty_credentials(self):
        """Test login with empty credentials"""
        response = client.post("/auth/login", json={
            "username": "",
            "password": ""
        })
        assert response.status_code in [401, 422]
    
    def test_validate_session_valid(self):
        """Test session validation with valid token"""
        headers = get_auth_header()
        token = headers["Authorization"].replace("Bearer ", "")
        response = client.post("/auth/validate", json={
            "session_token": token
        })
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] == True
        assert data["user_id"] is not None
        assert data["expires_at"] is not None
    
    def test_validate_session_invalid(self):
        """Test session validation with invalid token"""
        response = client.post("/auth/validate", json={
            "session_token": "invalid_token_12345"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] == False
        assert data["user_id"] is None
    
    def test_validate_session_empty(self):
        """Test session validation with empty token"""
        response = client.post("/auth/validate", json={
            "session_token": ""
        })
        assert response.status_code == 200
        assert response.json()["valid"] == False
    
    def test_logout_success(self):
        """Test successful logout invalidates token"""
        headers = get_auth_header()
        token = headers["Authorization"].replace("Bearer ", "")
        
        # Logout
        response = client.post("/auth/logout", json={
            "session_token": token
        })
        assert response.status_code == 200
        assert response.json()["success"] == True
        
        # Verify token is now invalid
        validate_response = client.post("/auth/validate", json={
            "session_token": token
        })
        assert validate_response.json()["valid"] == False
    
    def test_logout_invalid_token(self):
        """Test logout with invalid token"""
        response = client.post("/auth/logout", json={
            "session_token": "invalid_token"
        })
        assert response.status_code == 401
    
    def test_multiple_sessions(self):
        """Test that multiple logins create different sessions"""
        client.post("/auth/register", json={
            "username": TEST_USERNAME,
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        
        # Login twice
        login1 = client.post("/auth/login", json={
            "username": TEST_USERNAME,
            "password": TEST_PASSWORD
        })
        login2 = client.post("/auth/login", json={
            "username": TEST_USERNAME,
            "password": TEST_PASSWORD
        })
        
        token1 = login1.json()["session_token"]
        token2 = login2.json()["session_token"]
        
        assert token1 != token2, "Each login should generate unique token"
        
        # Both should be valid
        assert client.post("/auth/validate", json={"session_token": token1}).json()["valid"] == True
        assert client.post("/auth/validate", json={"session_token": token2}).json()["valid"] == True

# ============ USER ENDPOINTS TESTS ============

class TestUserEndpoints:
    """Complete user profile management tests"""
    
    def test_get_current_user(self):
        """Test getting current user profile"""
        headers = get_auth_header()
        response = client.get("/users/me", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == TEST_USERNAME
        assert data["email"] == TEST_EMAIL
        assert data["role"] == "user"
        assert "id" in data
        assert "created_at" in data
    
    def test_get_current_user_no_token(self):
        """Test getting profile without authentication"""
        response = client.get("/users/me")
        assert response.status_code == 422
    
    def test_get_current_user_invalid_token(self):
        """Test getting profile with invalid token"""
        response = client.get("/users/me", headers={
            "Authorization": "Bearer invalid_token"
        })
        assert response.status_code == 401
    
    def test_get_current_user_wrong_scheme(self):
        """Test getting profile with wrong auth scheme"""
        response = client.get("/users/me", headers={
            "Authorization": "Basic invalid_token"
        })
        assert response.status_code == 401
    
    def test_update_user_username(self):
        """Test updating username"""
        headers = get_auth_header()
        response = client.put("/users/me", headers=headers, json={
            "username": "newusername"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert data["user"]["username"] == "newusername"
        assert data["user"]["email"] == TEST_EMAIL
    
    def test_update_user_email(self):
        """Test updating email"""
        headers = get_auth_header()
        response = client.put("/users/me", headers=headers, json={
            "email": "newemail@example.com"
        })
        assert response.status_code == 200
        assert response.json()["user"]["email"] == "newemail@example.com"
    
    def test_update_user_password(self):
        """Test updating password and verifying new password works"""
        headers = get_auth_header()
        response = client.put("/users/me", headers=headers, json={
            "password": "newpassword123"
        })
        assert response.status_code == 200
        
        # Old password should fail
        old_login = client.post("/auth/login", json={
            "username": TEST_USERNAME,
            "password": TEST_PASSWORD
        })
        assert old_login.status_code == 401
        
        # New password should work
        new_login = client.post("/auth/login", json={
            "username": TEST_USERNAME,
            "password": "newpassword123"
        })
        assert new_login.status_code == 200
    
    def test_update_user_multiple_fields(self):
        """Test updating multiple fields at once"""
        headers = get_auth_header()
        response = client.put("/users/me", headers=headers, json={
            "username": "multinew",
            "email": "multi@example.com"
        })
        assert response.status_code == 200
        data = response.json()["user"]
        assert data["username"] == "multinew"
        assert data["email"] == "multi@example.com"
    
    def test_update_user_no_changes(self):
        """Test update with no fields"""
        headers = get_auth_header()
        response = client.put("/users/me", headers=headers, json={})
        assert response.status_code == 200
        assert response.json()["success"] == True
    
    def test_update_user_duplicate_username(self):
        """Test updating to existing username fails"""
        # Create another user
        client.post("/auth/register", json={
            "username": "otheruser",
            "email": "other@example.com",
            "password": TEST_PASSWORD
        })
        
        headers = get_auth_header()
        response = client.put("/users/me", headers=headers, json={
            "username": "otheruser"
        })
        assert response.status_code == 400
    
    def test_update_user_duplicate_email(self):
        """Test updating to existing email fails"""
        # Create another user
        client.post("/auth/register", json={
            "username": "emailuser",
            "email": "taken@example.com",
            "password": TEST_PASSWORD
        })
        
        headers = get_auth_header()
        response = client.put("/users/me", headers=headers, json={
            "email": "taken@example.com"
        })
        assert response.status_code == 400
    
    def test_delete_user(self):
        """Test deleting current user"""
        headers = get_auth_header()
        response = client.delete("/users/me", headers=headers)
        assert response.status_code == 200
        assert response.json()["success"] == True
        
        # Verify cannot login after deletion
        login_response = client.post("/auth/login", json={
            "username": TEST_USERNAME,
            "password": TEST_PASSWORD
        })
        assert login_response.status_code == 401
    
    def test_delete_user_invalidates_sessions(self):
        """Test that deleting user invalidates all sessions"""
        headers = get_auth_header()
        token = headers["Authorization"].replace("Bearer ", "")
        
        # Create another session
        login_response = client.post("/auth/login", json={
            "username": TEST_USERNAME,
            "password": TEST_PASSWORD
        })
        token2 = login_response.json()["session_token"]
        
        # Delete user
        client.delete("/users/me", headers=headers)
        
        # Both tokens should be invalid
        assert client.post("/auth/validate", json={"session_token": token}).json()["valid"] == False
        assert client.post("/auth/validate", json={"session_token": token2}).json()["valid"] == False

# ============ DOCUMENT ENDPOINTS TESTS ============

class TestDocumentEndpoints:
    """Document management tests"""
    
    def get_test_file_path(self, filename):
        """Get path to test file"""
        base_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "dataset")
        return os.path.join(base_path, filename)
    
    def test_upload_pdf_document(self):
        """Test uploading a PDF document"""
        headers = get_auth_header()
        test_file = self.get_test_file_path("Договор_001.pdf")
        
        if not os.path.exists(test_file):
            pytest.skip(f"Test file not found: {test_file}")
        
        with open(test_file, "rb") as f:
            response = client.post(
                "/documents",
                headers=headers,
                files={"file": ("test.pdf", f, "application/pdf")},
                data={"template_id": None}  
            )
        
        assert response.status_code == 202
        data = response.json()
        assert data["success"] == True
        assert data["document_id"] is not None
        assert data["document"] is not None
        assert data["document"]["filename"] == "test.pdf"
        assert data["parsing_time_seconds"] is None or data["parsing_time_seconds"] >= 0
    
    def test_upload_docx_document(self):
        """Test uploading a DOCX document"""
        headers = get_auth_header()
        dataset_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "dataset")
        
        if not os.path.exists(dataset_path):
            pytest.skip("Dataset folder not found")
            
        docx_files = [f for f in os.listdir(dataset_path) if f.endswith('.docx')]
        
        if not docx_files:
            pytest.skip("No DOCX files found")
        
        test_file = os.path.join(dataset_path, docx_files[0])
        
        with open(test_file, "rb") as f:
            response = client.post(
                "/documents",
                headers=headers,
                files={"file": ("test.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
                data={"template_id": None}  
            )
        
        assert response.status_code == 202
        assert response.json()["success"] == True

    def test_upload_photo_document(self):
        """A phone photo enters the same asynchronous processing workflow."""
        headers = get_auth_header()
        buffer = io.BytesIO()
        Image.new("RGB", (900, 1200), "white").save(buffer, format="JPEG")

        response = client.post(
            "/documents",
            headers=headers,
            files={"file": ("camera.jpg", buffer.getvalue(), "image/jpeg")},
        )

        assert response.status_code == 202
        data = response.json()
        assert data["success"] is True
        assert data["document"]["filename"] == "camera.jpg"
        assert data["document"]["review_status"] == "pending"
    
    def test_upload_invalid_file_type(self):
        """Test uploading invalid file type"""
        headers = get_auth_header()
        response = client.post(
            "/documents",
            headers=headers,
            files={"file": ("test.txt", b"invalid content", "text/plain")},
            data={"template_id": None}  
        )
        assert response.status_code == 400
        assert "поддерживаются" in response.json()["detail"].lower()
    
    def test_upload_no_file(self):
        """Test uploading without file"""
        headers = get_auth_header()
        response = client.post(
            "/documents",
            headers=headers,
            data={"template_id": None}  
        )
        assert response.status_code == 422
    
    def test_upload_without_auth(self):
        """Test uploading without authentication"""
        response = client.post(
            "/documents",
            files={"file": ("test.pdf", b"content", "application/pdf")},
            data={"template_id": None}  
        )
        assert response.status_code == 422
    
    def test_list_documents_empty(self):
        """Test listing documents when none exist"""
        headers = get_auth_header()
        response = client.get("/documents", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert len(data["documents"]) == 0
        assert data["page"] == 1
        assert data["limit"] == 50
    
    def test_list_documents_with_pagination(self):
        """Test listing documents with pagination"""
        headers = get_auth_header()
        
        # Upload a document if available
        test_file = self.get_test_file_path("Договор_001.pdf")
        if os.path.exists(test_file):
            with open(test_file, "rb") as f:
                client.post(
                    "/documents",
                    headers=headers,
                    files={"file": ("test.pdf", f, "application/pdf")},
                    data={"template_id": None}  
                )
        
        # Test with custom pagination
        response = client.get("/documents?page=1&limit=10", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert data["page"] == 1
        assert data["limit"] == 10
        assert isinstance(data["documents"], list)
    
    def test_get_document_by_id(self):
        """Test getting a specific document"""
        headers = get_auth_header()
        test_file = self.get_test_file_path("Договор_001.pdf")
        
        if not os.path.exists(test_file):
            pytest.skip(f"Test file not found: {test_file}")
        
        # Upload document
        with open(test_file, "rb") as f:
            upload_response = client.post(
                "/documents",
                headers=headers,
                files={"file": ("test.pdf", f, "application/pdf")},
                data={"template_id": None}  
            )
        document_id = upload_response.json()["document_id"]
        
        # Get document
        response = client.get(f"/documents/{document_id}", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == document_id
        assert data["filename"] == "test.pdf"
    
    def test_get_document_not_found(self):
        """Test getting non-existent document"""
        headers = get_auth_header()
        response = client.get("/documents/99999", headers=headers)
        assert response.status_code == 404
    
    def test_get_document_unauthorized(self):
        """Test accessing another user's document"""
        # Create first user and upload document
        headers1 = get_auth_header()
        test_file = self.get_test_file_path("Договор_001.pdf")
        
        if not os.path.exists(test_file):
            pytest.skip(f"Test file not found: {test_file}")
        
        with open(test_file, "rb") as f:
            upload_response = client.post(
                "/documents",
                headers=headers1,
                files={"file": ("test.pdf", f, "application/pdf")},
                data={"template_id": None}  
            )
        document_id = upload_response.json()["document_id"]
        
        # Create second user and try to access
        headers2 = get_auth_header(
            username="otheruser",
            email="other@example.com",
            password="otherpass123"
        )
        
        response = client.get(f"/documents/{document_id}", headers=headers2)
        assert response.status_code == 403

    def test_get_document_content_groups_text_by_page(self):
        headers = get_auth_header()
        db = database.get_session(app_module.engine)
        try:
            user = database.get_user(db, username=TEST_USERNAME)
            document = database.create_document(db, owner=user.id, template_id=None, filename="content.docx")
            database.create_parsed_document(
                db,
                document.id,
                "PAGE 1\n\nДоговор № 10",
                document_ir={
                    "source_format": "docx",
                    "pages": [{
                        "number": 1,
                        "needs_ocr": False,
                        "blocks": [{"text": "Договор № 10", "source": "docx", "order": 0}],
                    }],
                },
            )
            document_id = document.id
        finally:
            db.close()

        response = client.get(f"/documents/{document_id}/content", headers=headers)

        assert response.status_code == 200
        assert response.json() == {
            "source_format": "docx",
            "page_count": 1,
            "pages": [{"number": 1, "text": "Договор № 10"}],
        }

    def test_get_document_preview_returns_lightweight_image(self, tmp_path):
        headers = get_auth_header()
        stored_path = tmp_path / "preview.pdf"
        with app_module.pymupdf.open() as pdf:
            page = pdf.new_page(width=600, height=800)
            page.draw_rect(page.rect, fill=(1, 0, 0), color=(1, 0, 0))
            page = pdf.new_page(width=800, height=400)
            page.draw_rect(page.rect, fill=(0, 0, 1), color=(0, 0, 1))
            pdf.save(stored_path)
        db = database.get_session(app_module.engine)
        try:
            user = database.get_user(db, username=TEST_USERNAME)
            document = database.create_document(
                db,
                owner=user.id,
                template_id=None,
                filename="preview.pdf",
                stored_path=str(stored_path),
            )
            database.create_parsed_document(db, document.id, "PAGE 1\nДоговор поставки № 42")
            document_id = document.id
        finally:
            db.close()

        response = client.get(f"/documents/{document_id}/preview", headers=headers)

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/png")
        with Image.open(io.BytesIO(response.content)) as image:
            assert image.size == (960, 1280)
            assert image.getpixel((480, 640)) == (255, 0, 0)

    def test_docx_preview_uses_fresh_rendered_original_and_ignores_stale_cache(self, tmp_path, monkeypatch):
        import backend.document_view as document_view
        monkeypatch.setenv('LIBREOFFICE_BIN', '')
        monkeypatch.setattr(document_view.shutil, 'which', lambda name: None)
        headers = get_auth_header()
        source = tmp_path / 'original.docx'
        source.write_bytes(b'docx-placeholder')
        rendered = source.with_name(source.name + '.rendered.pdf')
        with app_module.pymupdf.open() as pdf:
            pdf.new_page().insert_text((40, 50), 'Original formatted page')
            pdf.save(rendered)
        db = database.get_session(app_module.engine)
        try:
            user = database.get_user(db, username=TEST_USERNAME)
            document = database.create_document(db, owner=user.id, template_id=None, filename=source.name, stored_path=str(source))
            database.create_parsed_document(db, document.id, 'PAGE 1\nExtracted text')
            document_id = document.id
        finally:
            db.close()
        response = client.get(f'/documents/{document_id}/preview', headers=headers)
        assert response.status_code == 200
        assert response.headers['content-type'].startswith('image/png')
        with Image.open(io.BytesIO(response.content)) as image:
            assert image.width == 960
        changed = rendered.stat().st_mtime_ns + 1_000_000_000
        os.utime(source, ns=(changed, changed))
        response = client.get(f'/documents/{document_id}/preview', headers=headers)
        assert response.status_code == 503
        assert response.headers['content-type'].startswith('application/json')
        assert 'превью' in response.json()['detail']
    
    def test_delete_document_success(self):
        """Test deleting a document"""
        headers = get_auth_header()
        test_file = self.get_test_file_path("Договор_001.pdf")
        
        if not os.path.exists(test_file):
            pytest.skip(f"Test file not found: {test_file}")
        
        # Upload document
        with open(test_file, "rb") as f:
            upload_response = client.post(
                "/documents",
                headers=headers,
                files={"file": ("test.pdf", f, "application/pdf")},
                data={"template_id": None}  
            )
        document_id = upload_response.json()["document_id"]
        
        # Delete document
        response = client.delete(f"/documents/{document_id}", headers=headers)
        assert response.status_code == 200
        assert response.json()["success"] == True
        
        # Verify deleted
        get_response = client.get(f"/documents/{document_id}", headers=headers)
        assert get_response.status_code == 404
    
    def test_delete_document_not_found(self):
        """Test deleting non-existent document"""
        headers = get_auth_header()
        response = client.delete("/documents/99999", headers=headers)
        assert response.status_code == 404
    
    def test_admin_can_access_any_document(self):
        """Test admin can access other users' documents"""
        # Create regular user and upload document
        headers_user = get_auth_header()
        test_file = self.get_test_file_path("Договор_001.pdf")
        
        if not os.path.exists(test_file):
            pytest.skip(f"Test file not found: {test_file}")
        
        with open(test_file, "rb") as f:
            upload_response = client.post(
                "/documents",
                headers=headers_user,
                files={"file": ("test.pdf", f, "application/pdf")},
                data={"template_id": None}  
            )
        document_id = upload_response.json()["document_id"]
        
        # Admin should be able to access
        headers_admin = get_admin_auth_header()
        response = client.get(f"/documents/{document_id}", headers=headers_admin)
        assert response.status_code == 200

# ============ METADATA ENDPOINTS TESTS ============

class TestMetadataEndpoints:
    """Metadata extraction tests"""

    def test_operator_can_confirm_and_reopen_review(self):
        headers = get_auth_header()
        db = database.get_session(app_module.engine)
        try:
            user = database.get_user(db, username=TEST_USERNAME)
            document = database.create_document(
                db,
                owner=user.id,
                template_id=None,
                filename="review.pdf",
            )
            database.create_metadata(
                db,
                document.id,
                {"contract_number": {"value": "42"}},
            )
            document_id = document.id
        finally:
            db.close()

        confirmed = client.patch(
            f"/documents/{document_id}/review",
            headers=headers,
            json={"confirmed": True},
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["review_status"] == "reviewed"
        assert confirmed.json()["reviewed_at"] is not None

        reopened = client.patch(
            f"/documents/{document_id}/review",
            headers=headers,
            json={"confirmed": False},
        )
        assert reopened.status_code == 200
        assert reopened.json()["review_status"] == "pending"
        assert reopened.json()["reviewed_at"] is None

    def test_metadata_edit_returns_confirmed_document_to_review(self):
        headers = get_auth_header()
        db = database.get_session(app_module.engine)
        try:
            user = database.get_user(db, username=TEST_USERNAME)
            document = database.create_document(
                db,
                owner=user.id,
                template_id=None,
                filename="review.pdf",
            )
            database.create_metadata(db, document.id, {"contract_number": {"value": "41"}})
            database.update_document(
                db,
                document.id,
                review_status="reviewed",
                reviewed_at=datetime.now(),
                reviewed_by=user.id,
            )
            document_id = document.id
        finally:
            db.close()

        response = client.patch(
            f"/documents/{document_id}/metadata",
            headers=headers,
            json={"fields": {"contract_number": {"value": "42"}}},
        )

        assert response.status_code == 200
        assert response.json()["review_status"] == "pending"
        assert response.json()["reviewed_at"] is None

    def test_refresh_summary_does_not_guess_risk_perspective(self, monkeypatch):
        headers = get_auth_header()
        db = database.get_session(app_module.engine)
        try:
            user = database.get_user(db, username=TEST_USERNAME)
            document = database.create_document(db, owner=user.id, template_id=None, filename="insights.pdf")
            database.create_parsed_document(db, document.id, "PAGE 1\n\nДоговор продлевается автоматически")
            database.create_metadata(db, document.id, {"contract_number": {"value": "12"}})
            document_id = document.id
        finally:
            db.close()

        monkeypatch.setattr(app_module, "summarize_document", lambda *_args: "Договор с автоматическим продлением.")
        monkeypatch.setattr(app_module, "review_contract_risks", lambda *_args: pytest.fail("Risk review needs an explicit side"))
        response = client.post(f"/documents/{document_id}/insights", headers=headers)
        assert response.status_code == 200
        assert response.json()["errors"] == []
        assert response.json()["metadata"]["summary"] == "Договор с автоматическим продлением."
        assert response.json()["metadata"]["risks"] is None
        assert response.json()["metadata"]["risk_review"] is None

        edited = client.patch(
            f"/documents/{document_id}/metadata", headers=headers,
            json={"fields": {"contract_number": {"value": "13"}}},
        )
        assert edited.status_code == 200
        assert edited.json()["metadata"]["summary"] is None
        assert edited.json()["metadata"]["risks"] is None
    
    def test_background_analysis_cannot_overwrite_operator_edit(self, monkeypatch):
        headers = get_auth_header()
        db = database.get_session(app_module.engine)
        try:
            user = database.get_user(db, username=TEST_USERNAME)
            document = database.create_document(db, owner=user.id, template_id=None, filename="concurrent.pdf")
            database.create_parsed_document(db, document.id, "PAGE 1\nДоговор №12")
            database.create_metadata(db, document.id, {"contract_number": {"value": "12"}})
            document_id = document.id
        finally:
            db.close()

        def edit_while_generating(*_args):
            editing = database.get_session(app_module.engine)
            try:
                database.update_metadata(editing, document_id, {"contract_number": {"value": "13"}})
            finally:
                editing.close()
            return "Сводка по старым данным"

        monkeypatch.setattr(app_module, "summarize_document", edit_while_generating)
        monkeypatch.setattr(app_module, "review_contract_risks", lambda *_args: pytest.fail("Summary must not start a risk review"))
        response = client.post(f"/documents/{document_id}/insights", headers=headers)
        assert response.status_code == 200
        assert response.json()["metadata"]["fields"]["contract_number"]["value"] == "13"
        assert response.json()["metadata"]["summary"] is None
        assert response.json()["metadata"]["risks"] is None
        assert response.json()["errors"]

    def _risk_document(self):
        headers = get_auth_header()
        with database.get_session(app_module.engine) as db:
            user = database.get_user(db, username=TEST_USERNAME)
            document = database.create_document(db, owner=user.id, template_id=None, filename="risk.pdf")
            database.create_parsed_document(db, document.id, "PAGE 1\nДоговор поставки. Поставщик вправе увеличивать цену без согласия Покупателя.")
            database.create_metadata(db, document.id, {"contract_number": {"value": "12"}})
            return headers, document.id

    def test_risk_review_requires_explicit_side_and_scope(self):
        headers, document_id = self._risk_document()
        for payload in ({}, {"contract_type": "supply", "user_side": "customer", "scope_confirmed": False}):
            assert client.post(f"/documents/{document_id}/risks", headers=headers, json=payload).status_code == 422
        stranger = get_auth_header(username="stranger", email="stranger@example.com")
        payload = {"contract_type": "supply", "user_side": "customer", "scope_confirmed": True}
        assert client.post(f"/documents/{document_id}/risks", headers=stranger, json=payload).status_code == 403

    def test_catalog_review_is_persisted_and_invalidated_by_edit(self, monkeypatch):
        headers, document_id = self._risk_document()
        payload = {"contract_type": "supply", "user_side": "customer", "scope_confirmed": True}
        def generated(text, fields, profile):
            return {"status": "complete", "profile": profile.model_dump(), "findings": [{"rule_id": "price_change", "evidence": "Поставщик вправе увеличивать цену без согласия Покупателя.", "basis": {"criterion": "Правило каталога"}}], "coverage": {"chunks_total": 1, "chunks_scanned": 1}}
        monkeypatch.setattr(app_module, "review_contract_risks", generated)
        response = client.post(f"/documents/{document_id}/risks", headers=headers, json=payload)
        assert response.status_code == 200
        assert response.json()["metadata"]["risk_review"]["status"] == "complete"
        assert response.json()["metadata"]["risks"][0]["basis"]
        saved = client.get(f"/documents/{document_id}", headers=headers).json()
        assert saved["metadata"]["risk_review"]["profile"]["user_side"] == "customer"
        edited = client.patch(f"/documents/{document_id}/metadata", headers=headers, json={"fields": {"contract_number": {"value": "13"}}})
        assert edited.json()["metadata"]["risk_review"] is None
        assert edited.json()["metadata"]["risks"] is None

    def test_risk_review_cannot_overwrite_operator_change(self, monkeypatch):
        headers, document_id = self._risk_document()
        def generated(*_args):
            client.patch(f"/documents/{document_id}/metadata", headers=headers, json={"fields": {"contract_number": {"value": "13"}}}).raise_for_status()
            return {"status": "complete", "findings": []}
        monkeypatch.setattr(app_module, "review_contract_risks", generated)
        response = client.post(f"/documents/{document_id}/risks", headers=headers, json={"contract_type": "supply", "user_side": "customer", "scope_confirmed": True})
        assert response.status_code == 409
        saved = client.get(f"/documents/{document_id}", headers=headers).json()
        assert saved["metadata"]["fields"]["contract_number"]["value"] == "13"
        assert saved["metadata"]["risk_review"] is None

    def test_older_risk_run_cannot_overwrite_a_new_perspective(self, monkeypatch):
        headers, document_id = self._risk_document()
        def generated(*_args):
            with database.get_session(app_module.engine) as db:
                database.start_risk_review(db, document_id, {"contract_number": {"value": "12"}}, {"review_id": "newer", "status": "running", "profile": {"user_side": "provider"}})
            return {"status": "complete", "findings": []}
        monkeypatch.setattr(app_module, "review_contract_risks", generated)
        response = client.post(f"/documents/{document_id}/risks", headers=headers, json={"contract_type": "supply", "user_side": "customer", "scope_confirmed": True})
        assert response.status_code == 409
        saved = client.get(f"/documents/{document_id}", headers=headers).json()
        assert saved["metadata"]["risk_review"]["profile"]["user_side"] == "provider"

    def test_failed_risk_run_never_publishes_partial_or_stale_results(self, monkeypatch):
        headers, document_id = self._risk_document()
        with database.get_session(app_module.engine) as db:
            metadata = database.get_metadata(db, document_id)
            metadata.risks = [{"title": "Старый риск"}]
            db.commit()
        def fail(*_args):
            raise RuntimeError("provider returned internal secret that must not reach UI")
        monkeypatch.setattr(app_module, "review_contract_risks", fail)
        response = client.post(f"/documents/{document_id}/risks", headers=headers, json={"contract_type": "services", "user_side": "provider", "scope_confirmed": True})
        assert response.status_code == 200
        metadata = response.json()["metadata"]
        assert metadata["risks"] is None
        assert metadata["risk_review"]["status"] == "failed"
        assert "secret" not in metadata["risk_review"]["error"]

    def test_interrupted_risk_review_can_recover_after_restart(self):
        _headers, document_id = self._risk_document()
        with database.get_session(app_module.engine) as db:
            database.start_risk_review(db, document_id, {"contract_number": {"value": "12"}}, {"review_id": "interrupted", "status": "running"})
            database.recover_risk_reviews(db)
            assert database.get_metadata(db, document_id).risk_review["status"] == "failed"

    def test_extract_metadata_success(self):
        """Test extracting metadata from a parsed document"""
        headers = get_auth_header()
        test_file = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), 
            "dataset", 
            "Договор_001.pdf"
        )
        
        if not os.path.exists(test_file):
            pytest.skip("Test file not found")
        
        # Upload document
        with open(test_file, "rb") as f:
            upload_response = client.post(
                "/documents",
                headers=headers,
                files={"file": ("test.pdf", f, "application/pdf")},
                data={"template_id": None}  
            )
        document_id = upload_response.json()["document_id"]
        
        # Extract metadata - may fail due to model/hardware limitations
        response = client.post(
            f"/documents/{document_id}/metadata",
            headers=headers
        )
        
        # Extraction is queued; the result is read through GET /documents/{id}.
        assert response.status_code in {202, 409}
        if response.status_code == 202:
            data = response.json()
            assert data["success"] is True
            assert data["metadata_id"] is None
    
    def test_extract_metadata_document_not_found(self):
        """Test extracting metadata for non-existent document"""
        headers = get_auth_header()
        response = client.post("/documents/99999/metadata", headers=headers)
        assert response.status_code == 404
    
    def test_extract_metadata_unauthorized(self):
        """Test extracting metadata for another user's document"""
        # Create first user and upload
        headers1 = get_auth_header()
        test_file = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), 
            "dataset", 
            "Договор_001.pdf"
        )
        
        if not os.path.exists(test_file):
            pytest.skip("Test file not found")
        
        with open(test_file, "rb") as f:
            upload_response = client.post(
                "/documents",
                headers=headers1,
                files={"file": ("test.pdf", f, "application/pdf")},
                data={"template_id": None}  
            )
        document_id = upload_response.json()["document_id"]
        
        # Second user tries to extract metadata
        headers2 = get_auth_header(
            username="otheruser",
            email="other@example.com",
            password="otherpass123"
        )
        
        response = client.post(
            f"/documents/{document_id}/metadata",
            headers=headers2
        )
        assert response.status_code == 403

# ============ DATA INTEGRITY TESTS ============

class TestDataIntegrity:
    """Data consistency and integrity tests"""
    
    def test_document_count_after_delete(self):
        """Test document count decreases after deletion"""
        headers = get_auth_header()
        test_file = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), 
            "dataset", 
            "Договор_001.pdf"
        )
        
        if not os.path.exists(test_file):
            pytest.skip("Test file not found")
        
        # Upload document
        with open(test_file, "rb") as f:
            upload_response = client.post(
                "/documents",
                headers=headers,
                files={"file": ("test.pdf", f, "application/pdf")},
                data={"template_id": None}  
            )
        document_id = upload_response.json()["document_id"]
        
        # Get initial count
        list_response = client.get("/documents", headers=headers)
        initial_count = list_response.json()["total"]
        
        # Delete document
        client.delete(f"/documents/{document_id}", headers=headers)
        
        # Verify count decreased
        list_response = client.get("/documents", headers=headers)
        final_count = list_response.json()["total"]
        
        assert final_count == initial_count - 1
    
    def test_user_deletion_cleanup(self):
        """Test that deleting user cleans up their data"""
        headers = get_auth_header()
        token = headers["Authorization"].replace("Bearer ", "")
        
        # Delete user
        client.delete("/users/me", headers=headers)
        
        # Verify sessions are deleted
        validate_response = client.post("/auth/validate", json={
            "session_token": token
        })
        assert validate_response.json()["valid"] == False

def test_pmi_batch_preserves_originals_and_isolates_bad_files(monkeypatch):
    from docx import Document
    from hashlib import sha256
    headers = get_auth_header()
    queued = []
    monkeypatch.setattr(app_module.JOB_MANAGER, 'enqueue', lambda ident, kind: queued.append((ident, kind)))
    buffer = io.BytesIO()
    document = Document()
    document.add_paragraph('Договор № 42 от 15.09.2026')
    document.save(buffer)
    payload = buffer.getvalue()
    response = client.post('/documents/batch', headers=headers, files=[
        ('files', ('first.docx', payload, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')),
        ('files', ('bad.pdf', b'%PDF-corrupt', 'application/pdf')),
        ('files', ('second.docx', payload, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')),
    ])
    assert response.status_code == 207
    result = response.json()
    assert (result['accepted'], result['rejected']) == (2, 1)
    assert result['results'][1]['error']
    assert len(queued) == 2
    listing = client.get('/documents', headers=headers).json()
    assert listing['total'] == 2
    assert len({d['id'] for d in listing['documents']}) == 2
    for item in listing['documents']:
        original = client.get(f"/documents/{item['id']}/file", headers=headers)
        assert sha256(original.content).digest() == sha256(payload).digest()


def test_pmi_registry_sorts_numerically_before_pagination_and_searches_cyrillic():
    import time
    headers = get_auth_header()
    with database.get_session(app_module.engine) as db:
        user = database.get_user(db, username=TEST_USERNAME)
        for index in range(100):
            doc = database.create_document(db, owner=user.id, template_id=None, filename=f'file-{index}.pdf')
            database.create_metadata(db, doc.id, {'contract_number': {'value': f'Д-{index}'},
                'contract_date': {'value': '2026-01-01' if index % 2 else '2026-02-01'},
                'total_amount': {'value': index + 1}, 'parties': [{'name': 'ООО АЛЬФА', 'role': 'Заказчик'}]})
        database.update_document(db, doc.id, processing_status='failed', processing_error='Тестовая ошибка')
        failed_document_id = doc.id
    started = time.perf_counter()
    listed = client.get('/documents?sort_by=total_amount&sort_order=asc&limit=2&page=2', headers=headers)
    assert time.perf_counter() - started < 3
    assert listed.status_code == 200
    assert listed.json()['total'] == 100
    assert [d['fields']['total_amount']['value'] for d in listed.json()['documents']] == [3, 4]
    found = client.get('/documents?search=альфа&sort_by=contract_date&sort_order=desc&limit=100', headers=headers).json()
    assert found['total'] == 100
    assert found['documents'][0]['fields']['contract_date']['value'] == '2026-02-01'
    assert next(d for d in found['documents'] if d['id'] == failed_document_id)['status'] == 'failed'
    assert client.get('/documents?sort_by=unknown', headers=headers).status_code == 422
    assert client.get('/documents?page=0', headers=headers).status_code == 422
    assert client.get('/documents?limit=10000', headers=headers).status_code == 422
    assert client.get('/documents?search=%25', headers=headers).json()['total'] == 0


def test_pmi_unavailable_database_returns_clear_503(monkeypatch):
    from sqlalchemy.exc import OperationalError
    def unavailable(*args, **kwargs):
        raise OperationalError('SELECT 1', {}, Exception('unavailable'))
    monkeypatch.setattr(app_module, 'get_user_from_token', unavailable)
    response = client.get('/documents', headers={'Authorization': 'Bearer unavailable'})
    assert response.status_code == 503
    assert 'База данных' in response.json()['detail']


def test_pmi_reanalysis_updates_same_metadata_and_records_rules(monkeypatch):
    from src.extraction.rules import extract_with_rules
    headers = get_auth_header()
    text = 'PAGE 1\nДоговор № 42\n15.09.2026\nЗаказчик: ООО "Альфа"\nИсполнитель: ООО "Бета"\nСумма договора 100 рублей.'
    with database.get_session(app_module.engine) as db:
        user = database.get_user(db, username=TEST_USERNAME)
        doc = database.create_document(db, owner=user.id, template_id=None, filename='repeat.pdf')
        database.create_parsed_document(db, doc.id, text)
        metadata = database.create_metadata(db, doc.id, {'contract_number': {'value': 'old'}})
        database.update_document(db, doc.id, processing_status='extracted')
        ident, metadata_id = doc.id, metadata.id
    monkeypatch.setattr(app_module.settings, 'extraction_backend', 'rules')
    monkeypatch.setattr(app_module.EXTRACTION_SERVICE, 'extract', lambda **kwargs: extract_with_rules(kwargs['text']))
    monkeypatch.setattr(app_module.JOB_MANAGER, 'enqueue', lambda document_id, kind: app_module.run_processing_job(kind, document_id))
    assert client.post(f'/documents/{ident}/analyze', headers=headers).status_code == 200
    result = client.get(f'/documents/{ident}', headers=headers).json()
    assert result['metadata']['id'] == metadata_id
    assert result['metadata']['fields']['contract_number']['value'] == '42'
    assert result['metadata']['field_statuses']['contract_number']['method'] == 'rule'
    assert result['metadata']['processing']['rules_version']
    assert result['metadata']['processing']['processed_at']
    assert client.get('/documents', headers=headers).json()['total'] == 1
    with database.get_session(app_module.engine) as db:
        assert db.query(database.DocumentMetadata).count() == 1


def test_api_model_identity_is_saved_without_local_revision(monkeypatch):
    from src.extraction.provenance import model_identity
    from src.extraction.validation import validate_model_result
    headers = get_auth_header()
    text = 'PAGE 1\nДоговор № 42'
    with database.get_session(app_module.engine) as db:
        user = database.get_user(db, username=TEST_USERNAME)
        doc = database.create_document(db, owner=user.id, template_id=None, filename='identity.pdf')
        database.create_parsed_document(db, doc.id, text)
        ident = doc.id
    fields = validate_model_result({'contract_number': {'value': '42', 'evidence': 'Договор № 42'}}, text)
    fields['_provenance'] = {**model_identity('provider/actual-model', 'api'), 'prompts': ['synthetic test prompt']}
    monkeypatch.setenv('CONTRACT_MODEL_REVISION', 'unrelated-local-revision')
    monkeypatch.setattr(app_module.settings, 'extraction_backend', 'api')
    monkeypatch.setattr(app_module.EXTRACTION_SERVICE, 'extract', lambda **kw: (fields, {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}))
    monkeypatch.setattr(app_module, 'summarize_document', lambda *args: 'Проверочная сводка')
    app_module.process_metadata_extraction(ident)
    saved = client.get(f'/documents/{ident}', headers=headers).json()
    assert saved['status'] == 'extracted'
    processing = saved['metadata']['processing']
    assert processing['backend'] == 'api'
    assert processing['model'] == 'provider/actual-model'
    assert processing['model_revision'] is None
    assert processing['model_revision_source'] == 'unknown'
    assert processing['prompts'] == ['synthetic test prompt']
    with database.get_session(app_module.engine) as db:
        assert database.get_metadata(db, ident).fields['_provenance']['model'] == 'provider/actual-model'


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])


def test_registry_status_filter_applies_before_pagination_and_respects_owner():
    headers = get_auth_header()
    other_headers = get_auth_header('registryother', 'registry_other@example.com', 'anotherpass123')
    with database.get_session(app_module.engine) as db:
        owner = database.get_user(db, username=TEST_USERNAME)
        other = database.get_user(db, username='registryother')
        ids = {}
        for key, status, reviewed, has_metadata, user_id in [
            ('pending_a', 'extracted', False, True, owner.id),
            ('pending_b', 'extracted', False, True, owner.id),
            ('reviewed', 'extracted', True, True, owner.id),
            ('processing', 'processing', False, False, owner.id),
            ('reanalyzing', 'processing', True, True, owner.id),
            ('failed', 'failed', True, True, owner.id),
            ('uploaded', 'uploaded', False, False, owner.id),
            ('foreign', 'extracted', False, True, other.id),
        ]:
            doc = database.create_document(db, owner=user_id, template_id=None, filename=f'{key}.pdf')
            database.update_document(db, doc.id, processing_status=status, review_status='reviewed' if reviewed else 'pending')
            if has_metadata:
                database.create_metadata(db, doc.id, {'contract_number': {'value': key}})
            ids[key] = doc.id
    pending = client.get('/documents?view_status=pending&limit=1&page=2', headers=headers).json()
    assert pending['total'] == 2
    assert [doc['id'] for doc in pending['documents']] == [ids['pending_a']]
    assert {doc['id'] for doc in client.get('/documents?view_status=reviewed', headers=headers).json()['documents']} == {ids['reviewed']}
    assert {doc['id'] for doc in client.get('/documents?view_status=processing', headers=headers).json()['documents']} == {ids['processing'], ids['reanalyzing'], ids['uploaded']}
    assert {doc['id'] for doc in client.get('/documents?view_status=failed', headers=headers).json()['documents']} == {ids['failed']}
    assert client.get('/documents?view_status=pending&search=pending_b', headers=headers).json()['total'] == 1
    assert client.get('/documents?view_status=pending', headers=other_headers).json()['total'] == 1
    assert client.get('/documents?view_status=unknown', headers=headers).status_code == 422


def test_operator_amount_edit_retains_currency_without_claiming_old_source():
    headers = get_auth_header()
    with database.get_session(app_module.engine) as db:
        owner = database.get_user(db, username=TEST_USERNAME)
        document = database.create_document(db, owner=owner.id, template_id=None, filename='manual-amount.pdf')
        database.create_metadata(db, document.id, {'total_amount': {'value': 1000, 'currency': 'RUB', 'evidence': 'Сумма 1000 рублей'}})
        document_id = document.id
    response = client.patch(f'/documents/{document_id}/metadata', headers=headers,
                            json={'fields': {'total_amount': {'value': 1250.5, 'currency': 'USD'}}})
    assert response.status_code == 200
    amount = response.json()['metadata']['fields']['total_amount']
    assert amount['value'] == 1250.5 and amount['currency'] == 'USD'
    assert amount['method'] == 'manual' and amount['status'] == 'needs_review'
    assert not amount.get('evidence')
    assert client.get(f'/documents/{document_id}', headers=headers).json()['metadata']['fields']['total_amount']['currency'] == 'USD'
