import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def _test_settings():
    """Make tests independent of the local .env.

    * disable retry sleeps so provider-failure tests run instantly;
    * pin both channels to the ``console`` mock so a live SMTP/Meta config in .env doesn't
      turn unit tests into real network sends.
    """
    settings = get_settings()
    saved = {
        "max_retries": settings.max_retries,
        "email_provider": settings.email_provider,
        "whatsapp_provider": settings.whatsapp_provider,
        "require_opt_in_for_whatsapp": settings.require_opt_in_for_whatsapp,
    }
    settings.max_retries = 0
    settings.email_provider = "console"
    settings.whatsapp_provider = "console"
    settings.require_opt_in_for_whatsapp = True
    yield
    for k, v in saved.items():
        setattr(settings, k, v)
