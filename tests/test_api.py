import pytest
from fastapi.testclient import TestClient
from datetime import datetime
import os
import sys

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
def setup_database(tmp_path):
    """Use an isolated database and storage directory for every API test."""
    previous_manager = app_module.JOB_MANAGER
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


def test_favicon_probe_is_empty():
    response = client.get("/favicon.ico")
    assert response.status_code == 204

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
        assert "unsupported" in response.json()["detail"].lower()
    
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
        stored_path = tmp_path / "preview.docx"
        stored_path.write_bytes(b"preview-placeholder")
        db = database.get_session(app_module.engine)
        try:
            user = database.get_user(db, username=TEST_USERNAME)
            document = database.create_document(
                db,
                owner=user.id,
                template_id=None,
                filename="preview.docx",
                stored_path=str(stored_path),
            )
            database.create_parsed_document(db, document.id, "Договор поставки № 42")
            document_id = document.id
        finally:
            db.close()

        response = client.get(f"/documents/{document_id}/preview", headers=headers)

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/svg+xml")
        assert b"preview.docx" in response.content
    
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

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
