import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def _fast_no_retries():
    """Disable retry sleeps so provider-failure tests run instantly."""
    settings = get_settings()
    original = settings.max_retries
    settings.max_retries = 0
    yield
    settings.max_retries = original
