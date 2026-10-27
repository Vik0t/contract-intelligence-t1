import pytest

from src.extraction.api_models import close_api_clients


@pytest.fixture(autouse=True)
def isolated_api_connection_pool():
    close_api_clients()
    yield
    close_api_clients()
