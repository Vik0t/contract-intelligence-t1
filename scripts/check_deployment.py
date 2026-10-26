"""Exercise a running deployment through HTTP using synthetic contracts only.

Creates an isolated test account and leaves its documents for browser review.
The URL selects the deployment and its configured inference backend.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import secrets
import tempfile
import time

import httpx

from scripts.ml_check import fixtures, score


def wait_for(client: httpx.Client, document_id: int, predicate, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/documents/{document_id}")
        response.raise_for_status()
        document = response.json()
        if document["status"] == "failed":
            raise RuntimeError(document.get("processing_error") or "Document processing failed")
        if predicate(document):
            return document
        time.sleep(1)
    raise TimeoutError(f"Document {document_id} did not reach the expected state in {timeout}s")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    parser.add_argument("--output", type=Path, default=Path("tmp/deployment-check.json"))
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--session-file", type=Path, help="Optional private credentials for subsequent manual browser checks")
    args = parser.parse_args()
    report = {"url": args.url, "kind": "synthetic_end_to_end", "records": [], "passed": False}
    username = "check" + secrets.token_hex(5)
    password = secrets.token_hex(16)
    try:
        with httpx.Client(base_url=args.url.rstrip("/") + "/api", timeout=180, trust_env=False) as client:
            client.get("/health/ready").raise_for_status()
            response = client.post("/auth/register", json={"username": username, "email": username + "@example.com", "password": password})
            response.raise_for_status()
            response = client.post("/auth/login", json={"username": username, "password": password})
            response.raise_for_status()
            client.headers["Authorization"] = "Bearer " + response.json()["session_token"]
            if args.session_file:
                args.session_file.parent.mkdir(parents=True, exist_ok=True)
                with open(args.session_file, "w", opener=lambda path, flags: os.open(path, flags, 0o600)) as file:
                    json.dump({"username": username, "password": password}, file)
            with tempfile.TemporaryDirectory(prefix="contract-deployment-check-") as directory:
                for extension, path in fixtures(Path(directory)).items():
                    record = {"format": extension, "passed": False}
                    report["records"].append(record)
                    started = time.monotonic()
                    with path.open("rb") as source:
                        response = client.post("/documents", files={"file": (path.name, source)})
                    response.raise_for_status()
                    document_id = response.json()["document_id"]
                    record["document_id"] = document_id
                    wait_for(client, document_id, lambda item: item["status"] == "ready", args.timeout)
                    client.post(f"/documents/{document_id}/analyze").raise_for_status()
                    document = wait_for(client, document_id, lambda item: bool((item.get("metadata") or {}).get("summary")) and isinstance((item.get("metadata") or {}).get("risks"), list), args.timeout)
                    metadata = document["metadata"]
                    checks = score(metadata["fields"])
                    record["field_checks"] = checks
                    assert all(checks.values()), f"Incorrect synthetic fields: {[key for key, value in checks.items() if not value]}"
                    risks = metadata["risks"]
                    assert any("цен" in item["evidence"].casefold() for item in risks), "Price-change risk missing"
                    assert any("неустой" in item["evidence"].casefold() for item in risks), "Uncapped penalty risk missing"
                    record["summary_present"] = True
                    record["risks_found"] = len(risks)
                    content = client.get(f"/documents/{document_id}/content")
                    content.raise_for_status()
                    assert content.json()["visual_page_count"] > 0
                    for endpoint in ("preview", "file", "pages/1/image"):
                        resource = client.get(f"/documents/{document_id}/{endpoint}")
                        resource.raise_for_status()
                        assert resource.content, endpoint
                    field = metadata["fields"]["contract_number"]
                    location = client.post(f"/documents/{document_id}/source-location", json={"evidence": field["evidence"], "page": field["page_number"]})
                    location.raise_for_status()
                    assert location.json()["rects"], "No highlight rectangles"
                    review = client.patch(f"/documents/{document_id}/review", json={"confirmed": True})
                    review.raise_for_status()
                    assert review.json()["review_status"] == "reviewed"
                    edited = deepcopy(metadata["fields"])
                    edited["contract_number"]["value"] = "OPERATOR-017"
                    response = client.patch(f"/documents/{document_id}/metadata", json={"fields": edited})
                    response.raise_for_status()
                    saved = client.get(f"/documents/{document_id}").json()
                    assert saved["metadata"]["fields"]["contract_number"]["value"] == "OPERATOR-017"
                    assert saved["review_status"] == "pending"
                    assert saved["metadata"]["summary"] is None and saved["metadata"]["risks"] is None
                    # Restore the actual number and regenerate analysis after edits.
                    client.patch(f"/documents/{document_id}/metadata", json={"fields": metadata["fields"]}).raise_for_status()
                    refreshed = client.post(f"/documents/{document_id}/insights")
                    refreshed.raise_for_status()
                    assert not refreshed.json()["errors"], "Analysis refresh returned errors"
                    assert refreshed.json()["metadata"]["summary"] and isinstance(refreshed.json()["metadata"]["risks"], list)
                    client.patch(f"/documents/{document_id}/review", json={"confirmed": True}).raise_for_status()
                    record.update(passed=True, elapsed_sec=round(time.monotonic() - started, 2))
                    print(json.dumps(record), flush=True)
            report["passed"] = True
    except Exception as exc:
        # No response bodies or credentials are logged.
        report["error_type"] = type(exc).__name__
        if isinstance(exc, httpx.HTTPStatusError):
            report.update(http_status=exc.response.status_code, endpoint=exc.request.url.path, method=exc.request.method)
        if isinstance(exc, (AssertionError, RuntimeError)):
            report["error"] = str(exc)
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps({"passed": report["passed"], "output": str(args.output), "error_type": report.get("error_type")}), flush=True)
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
