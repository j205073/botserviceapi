import os
import pytest


@pytest.mark.skipif(
    not os.getenv("BOT_APP_ID"),
    reason="需要完整環境變數才能初始化 app",
)
def test_import_app():
    """Verify the app module can be imported without errors."""
    import app
    assert hasattr(app, "app")
