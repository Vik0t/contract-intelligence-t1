# T1 Contract Intelligence API Documentation

Welcome to the **T1 Contract Intelligence** API — a powerful service designed to extract important information from contracts and legal documents using AI.

---

## 📡 Base URL

All API endpoints are relative to:

```
http://your-api-base-url.com
```

---

## 🔐 Authentication

Most endpoints require authentication using a **session token**. Include the token in the `Authorization` header:

```
Authorization: <your-session-token>
```

---

## 🌡️ Health Check

### Ping

> **GET** `/ping`

Check if the service is alive.

#### Responses

| Code | Description |
|------|-------------|
| 200 | Service is running |

---

## 👤 Authentication

### Register a New User

> **POST** `/auth/register`

Create a new user account.

#### Request Body

| Field | Type | Description |
|-------|------|-------------|
| `username` | string | Unique username (3-50 characters) |
| `email` | string | Valid email address |
| `password` | string | Password (minimum 6 characters) |

#### Example Request

```json
{
  "username": "johndoe",
  "email": "john@example.com",
  "password": "securepassword123"
}
```

#### Response

```json
{
  "success": true,
  "message": "User registered successfully",
  "user_id": 1
}
```

---

### Login

> **POST** `/auth/login`

Authenticate a user and receive a session token.

#### Request Body

| Field | Type | Description |
|-------|------|-------------|
| `username` | string | Your username |
| `password` | string | Your password |

#### Example Request

```json
{
  "username": "johndoe",
  "password": "securepassword123"
}
```

#### Response

```json
{
  "user": {
    "id": 1,
    "username": "johndoe",
    "email": "john@example.com",
    "role": "user",
    "created_at": "2026-01-01T00:00:00Z"
  },
  "session_token": "eyJhbGciOiJIUzI1NiIs...",
  "expires_at": "2026-01-02T00:00:00Z"
}
```

---

### Logout

> **POST** `/auth/logout`

Invalidate your current session.

#### Request Body

| Field | Type | Description |
|-------|------|-------------|
| `session_token` | string | The session token to invalidate |

#### Example Request

```json
{
  "session_token": "eyJhbGciOiJIUzI1NiIs..."
}
```

#### Response

```json
{
  "success": true,
  "message": "Logged out successfully"
}
```

---

### Validate Session

> **POST** `/auth/validate`

Check if a session token is still valid.

#### Request Body

| Field | Type | Description |
|-------|------|-------------|
| `session_token` | string | Session token to validate |

#### Example Request

```json
{
  "session_token": "eyJhbGciOiJIUzI1NiIs..."
}
```

#### Response

```json
{
  "valid": true,
  "user_id": 1,
  "expires_at": "2026-01-02T00:00:00Z"
}
```

---

## 👤 User Management

### Get Current User

> **GET** `/users/me`

Retrieve the profile of the currently authenticated user.

#### Headers

| Header | Required | Description |
|--------|----------|-------------|
| `Authorization` | ✅ | Your session token |

#### Response

```json
{
  "id": 1,
  "username": "johndoe",
  "email": "john@example.com",
  "role": "user",
  "created_at": "2026-01-01T00:00:00Z"
}
```

---

### Update Current User

> **PUT** `/users/me`

Update your profile information. All fields are optional.

#### Headers

| Header | Required | Description |
|--------|----------|-------------|
| `Authorization` | ✅ | Your session token |

#### Request Body

| Field | Type | Description |
|-------|------|-------------|
| `username` | string (optional) | New username (3-50 characters) |
| `email` | string (optional) | New email address |
| `password` | string (optional) | New password (minimum 6 characters) |

#### Example Request

```json
{
  "email": "newemail@example.com"
}
```

#### Response

```json
{
  "success": true,
  "message": "User updated successfully",
  "user": {
    "id": 1,
    "username": "johndoe",
    "email": "newemail@example.com",
    "role": "user",
    "created_at": "2026-01-01T00:00:00Z"
  }
}
```

---

### Delete Current User

> **DELETE** `/users/me`

Permanently delete your user account.

#### Headers

| Header | Required | Description |
|--------|----------|-------------|
| `Authorization` | ✅ | Your session token |

#### Response

```json
{
  "success": true,
  "message": "User deleted successfully"
}
```

---

## 📄 Document Management

### Upload Document

> **POST** `/documents`

Upload a contract or legal document for processing.

#### Headers

| Header | Required | Description |
|--------|----------|-------------|
| `Authorization` | ✅ | Your session token |

#### Request Body (`multipart/form-data`)

| Field | Type | Description |
|-------|------|-------------|
| `file` | file | The document file to upload |
| `template_id` | integer (optional) | Template ID for extraction |

#### Response

```json
{
  "success": true,
  "message": "Document uploaded successfully",
  "document_id": 123,
  "document": {
    "id": 123,
    "owner": 1,
    "filename": "contract.pdf",
    "template_id": null,
    "created_at": "2026-01-01T00:00:00Z"
  },
  "parsing_time_seconds": 2.45
}
```

---

### List Documents

> **GET** `/documents`

Retrieve all documents belonging to the current user.

#### Headers

| Header | Required | Description |
|--------|----------|-------------|
| `Authorization` | ✅ | Your session token |

#### Query Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `page` | integer | 1 | Page number for pagination |
| `limit` | integer | 50 | Number of items per page |

#### Response

```json
{
  "total": 25,
  "page": 1,
  "limit": 50,
  "documents": [
    {
      "id": 123,
      "owner": 1,
      "filename": "contract.pdf",
      "template_id": null,
      "created_at": "2026-01-01T00:00:00Z"
    }
  ]
}
```

---

### Get Document

> **GET** `/documents/{document_id}`

Retrieve detailed information about a specific document.

#### Headers

| Header | Required | Description |
|--------|----------|-------------|
| `Authorization` | ✅ | Your session token |

#### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `document_id` | integer | ID of the document |

#### Response

```json
{
  "id": 123,
  "owner": 1,
  "filename": "contract.pdf",
  "template_id": null,
  "created_at": "2026-01-01T00:00:00Z",
  "metadata": {
    "id": 456,
    "document_id": 123,
    "fields": {
      "contract_value": 1500000,
      "effective_date": "2026-01-15",
      "expiry_date": "2027-01-15",
      "parties": ["Acme Corp", "Beta Inc"]
    },
    "created_at": "2026-01-01T00:05:00Z"
  }
}
```

---

### Delete Document

> **DELETE** `/documents/{document_id}`

Permanently delete a document and all associated metadata.

#### Headers

| Header | Required | Description |
|--------|----------|-------------|
| `Authorization` | ✅ | Your session token |

#### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `document_id` | integer | ID of the document to delete |

#### Response

```json
{
  "success": true,
  "message": "Document deleted successfully"
}
```

---

### Extract Metadata

> **POST** `/documents/{document_id}/metadata`

Run AI-powered extraction to pull structured information from your document.

#### Headers

| Header | Required | Description |
|--------|----------|-------------|
| `Authorization` | ✅ | Your session token |

#### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `document_id` | integer | ID of the document to extract from |

#### Response

```json
{
  "success": true,
  "message": "Metadata extracted successfully",
  "metadata_id": 456,
  "metadata": {
    "id": 456,
    "document_id": 123,
    "fields": {
      "contract_value": 1500000,
      "effective_date": "2026-01-15",
      "expiry_date": "2027-01-15",
      "parties": ["Acme Corp", "Beta Inc"],
      "governing_law": "New York"
    },
    "created_at": "2026-01-01T00:05:00Z"
  }
}
```

---

## 📊 Statistics (Admin Only)

### Get Statistics

> **GET** `/stats`

Retrieve platform-wide usage and performance statistics. Requires admin privileges.

#### Headers

| Header | Required | Description |
|--------|----------|-------------|
| `Authorization` | ✅ | Admin session token |

#### Query Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `period_days` | integer | 30 | Number of days to look back |

#### Response

```json
{
  "total_documents": 1024,
  "total_users": 87,
  "total_parsed_documents": 980,
  "total_metadata_extractions": 756,
  "total_tokens_used": 2847500,
  "average_parsing_time": 3.45,
  "average_extraction_time": 1.23,
  "period_start": "2025-12-02T00:00:00Z",
  "period_end": "2026-01-01T00:00:00Z",
  "documents_per_day": {
    "2026-01-01": 42,
    "2025-12-31": 38,
    "2025-12-30": 51
  }
}
```

---

## 📦 Data Models

### User

| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | Unique user identifier |
| `username` | string | User's username |
| `email` | string | User's email address |
| `role` | string | User's role (`user` or `admin`) |
| `created_at` | datetime | Account creation timestamp |

### Document

| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | Unique document identifier |
| `owner` | integer | User ID of document owner |
| `filename` | string | Original filename |
| `template_id` | integer | Template ID used for extraction (optional) |
| `created_at` | datetime | Document creation timestamp |

### Metadata

| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | Unique metadata identifier |
| `document_id` | integer | Associated document ID |
| `fields` | object | Extracted key-value fields |
| `created_at` | datetime | Metadata creation timestamp |

---

## ❌ Error Responses

All endpoints may return validation errors in the following format:

```json
{
  "detail": [
    {
      "loc": ["body", "username"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

### Common HTTP Status Codes

| Code | Description |
|------|-------------|
| 200 | Success |
| 400 | Bad request |
| 401 | Unauthorized / Invalid session |
| 403 | Forbidden |
| 404 | Resource not found |
| 422 | Validation error |
| 500 | Internal server error |

---

## 💡 Tips for Using the API

1. **Always authenticate first** — call `/auth/login` before accessing protected endpoints.
2. **Save your session token** — you'll need it for all subsequent requests.
3. **Extract metadata early** — after uploading a document, run the metadata extraction to get structured data.
4. **Handle pagination** — for large document lists, use the `page` and `limit` parameters.
5. **Check your role** — the `/stats` endpoint is available only for admin users.

---

## 🔗 API Quick Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/ping` | Health check |
| POST | `/auth/register` | Create new user |
| POST | `/auth/login` | Login & get session token |
| POST | `/auth/logout` | End session |
| POST | `/auth/validate` | Validate session token |
| GET | `/users/me` | Get your profile |
| PUT | `/users/me` | Update your profile |
| DELETE | `/users/me` | Delete your account |
| POST | `/documents` | Upload document |
| GET | `/documents` | List your documents |
| GET | `/documents/{id}` | Get document details |
| DELETE | `/documents/{id}` | Delete document |
| POST | `/documents/{id}/metadata` | Extract metadata |
| GET | `/stats` | Admin statistics |

---

> 🚀 **T1 Contract Intelligence**