def test_import_app():
    """Verify the app module can be imported without errors."""
    import app
    assert hasattr(app, "app")
