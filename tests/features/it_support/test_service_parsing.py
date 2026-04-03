import pytest
from features.it_support.service import ITSupportService


@pytest.fixture
def svc(monkeypatch):
    """Create ITSupportService with minimal env vars to avoid real API calls during init."""
    monkeypatch.setenv("ASANA_ACCESS_TOKEN", "fake-token")
    monkeypatch.setenv("SMTP_HOST", "localhost")
    return ITSupportService()


class TestParseReporterFromNotes:
    def test_parse_standard_notes(self, svc):
        notes = (
            "單號: ITTRQ20260403001\n"
            "提出人: 王小明 <wang@rinnai.com.tw>\n"
            "提出人部門: 資訊課\n"
            "分類: 印表機/列印 (printer)\n"
            "優先順序: P2"
        )
        result = svc._parse_reporter_from_notes(notes)
        assert result is not None
        assert result["email"] == "wang@rinnai.com.tw"
        assert result["reporter_name"] == "王小明"
        assert result["reporter_department"] == "資訊課"
        assert result["issue_id"] == "ITTRQ20260403001"
        assert result["priority"] == "P2"

    def test_parse_notes_with_colon_variants(self, svc):
        notes = (
            "單號：ITTRQ20260403002\n"
            "提出人：李大華 <lee@rinnai.com.tw>\n"
        )
        result = svc._parse_reporter_from_notes(notes)
        assert result is not None
        assert result["email"] == "lee@rinnai.com.tw"

    def test_parse_empty_notes(self, svc):
        result = svc._parse_reporter_from_notes("")
        assert result is None

    def test_parse_notes_without_email(self, svc):
        notes = "這是一般描述，沒有 IT 支援單格式"
        result = svc._parse_reporter_from_notes(notes)
        assert result is None

    def test_parse_notes_with_issue_id_only(self, svc):
        notes = "單號: ITTRQ20260403003\n描述: 測試問題"
        result = svc._parse_reporter_from_notes(notes)
        assert result is not None
        assert result["issue_id"] == "ITTRQ20260403003"
