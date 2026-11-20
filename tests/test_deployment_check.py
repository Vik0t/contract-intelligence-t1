import httpx
import pytest

from scripts import check_deployment


@pytest.mark.parametrize('initial_status,post_status,posts_expected', [
    ('processing', 200, 0), ('extracted', 200, 0), ('ready', 200, 1), ('ready', 409, 1),
])
def test_check_handles_automatic_and_manual_extraction(monkeypatch, initial_status, post_status, posts_expected):
    monkeypatch.setattr(check_deployment.time, 'sleep', lambda _: None)
    statuses = iter([initial_status, 'extracted', 'extracted'])
    requests = []

    def handle(request):
        requests.append(request.method)
        if request.method == 'POST':
            return httpx.Response(post_status, json={})
        status = next(statuses, 'extracted')
        return httpx.Response(200, json={
            'status': status, 'metadata': {'summary': 'Synthetic summary'} if status == 'extracted' else None,
        })

    with httpx.Client(base_url='http://test', transport=httpx.MockTransport(handle)) as client:
        document = check_deployment.wait_for_analysis(client, 42, 10)
    assert document['metadata']['summary']
    assert requests.count('POST') == posts_expected


def test_check_does_not_hide_analysis_request_errors():
    def handle(request):
        return httpx.Response(503 if request.method == 'POST' else 200, json={'status': 'ready'})

    with httpx.Client(base_url='http://test', transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            check_deployment.wait_for_analysis(client, 42, 10)
