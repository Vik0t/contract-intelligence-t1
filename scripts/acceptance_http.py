"""Exercise a deployed API; score only the metadata returned from persistence."""
from hashlib import sha256
import time

import httpx

from backend.delivery_profile import PROFILE, profile_digest


class HttpAcceptanceRunner:
    def __init__(self, base_url, token, *, timeout=60, poll_interval=.1, client=None):
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.client = client or httpx.Client(base_url=base_url.rstrip('/') + '/',
            headers={'Authorization': f'Bearer {token}'}, timeout=min(timeout, 30))
        try:
            self.runtime = self.get('runtime/profile')
            if (self.runtime.get('profile') != PROFILE or
                    self.runtime.get('profile_sha256') != profile_digest(PROFILE)):
                raise ValueError('Server does not run the pinned pmi-rules-v1 profile')
            if not all(self.runtime.get(k) for k in ('rules_sha256', 'runtime_source_sha256', 'dependencies')):
                raise ValueError('Server runtime identity is incomplete')
        except Exception:
            self.client.close()
            raise

    def get(self, path):
        response = self.client.get(path)
        response.raise_for_status()
        return response.json()

    def run(self, source, extension):
        started = time.perf_counter()
        mime = 'application/pdf' if extension == 'pdf' else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        with source.open('rb') as stream:
            response = self.client.post('documents', files={'file': (source.name, stream, mime)})
        response.raise_for_status()
        if response.status_code != 202:
            raise ValueError('Upload did not return 202')
        document_id = response.json()['document_id']
        while True:
            detail = self.get(f'documents/{document_id}')
            if detail['status'] == 'failed':
                raise RuntimeError('Server document processing failed')
            if detail['status'] == 'extracted' and detail.get('metadata'):
                break
            remaining = self.timeout - (time.perf_counter() - started)
            if remaining <= 0:
                raise TimeoutError(f'Processing deadline exceeded for document {document_id}')
            time.sleep(min(self.poll_interval, remaining))
        ready_seconds = time.perf_counter() - started
        metadata = detail['metadata']
        provenance = metadata['processing']
        original = self.client.get(f'documents/{document_id}/file')
        original.raise_for_status()
        content = self.get(f'documents/{document_id}/content')
        reread = self.get(f'documents/{document_id}')
        checks = {
            'original_sha256_matches': sha256(original.content).hexdigest() == sha256(source.read_bytes()).hexdigest(),
            'parsed_content_saved': content.get('source_format') == extension and bool(content.get('pages'))
                and any(page.get('text', '').strip() for page in content.get('pages', [])),
            'metadata_reread_matches': reread.get('metadata') == metadata,
            'profile_matches': provenance.get('delivery_profile') == PROFILE['id']
                and provenance.get('profile_sha256') == self.runtime['profile_sha256']
                and provenance.get('docx_parser') == PROFILE['docx_parser'],
            'runtime_matches': provenance.get('runtime_source_sha256') == self.runtime['runtime_source_sha256']
                and provenance.get('rules_sha256') == self.runtime['rules_sha256'],
            'rules_backend': provenance.get('backend') == 'rules' and provenance.get('model') is None,
        }
        if not all(checks.values()):
            raise ValueError('HTTP persistence check failed: ' + ', '.join(k for k, ok in checks.items() if not ok))
        return {'status': 'ok', 'fields': metadata['fields'], 'pages': content['page_count'],
                'document_id': document_id, 'metadata_id': metadata['id'], 'checks': checks,
                'seconds': ready_seconds, 'verification_seconds': time.perf_counter() - started,
                'original_sha256': sha256(original.content).hexdigest()}

    def close(self):
        self.client.close()
