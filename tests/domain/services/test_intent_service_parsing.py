import pytest
from unittest.mock import MagicMock
from domain.services.intent_service import IntentService, IntentResult


@pytest.fixture
def intent_service():
    mock_config = MagicMock()
    mock_config.openai.use_azure = False
    mock_config.openai.intent_model = "gpt-4o-mini"
    mock_openai = MagicMock()
    return IntentService(config=mock_config, openai_client=mock_openai)


class TestIntentResponseParsing:
    def test_parse_valid_json(self, intent_service):
        raw = '{"is_existing_feature": true, "category": "todo", "action": "add", "content": "買牛奶", "confidence": 0.9, "reason": "明確待辦"}'
        result = intent_service._parse_intent_response(raw)
        assert result.is_existing_feature is True
        assert result.category == "todo"
        assert result.action == "add"
        assert result.confidence == 0.9

    def test_parse_json_with_markdown_wrapper(self, intent_service):
        raw = '```json\n{"is_existing_feature": true, "category": "meeting", "action": "book", "content": "", "confidence": 0.85}\n```'
        result = intent_service._parse_intent_response(raw)
        assert result.category == "meeting"

    def test_parse_empty_response(self, intent_service):
        result = intent_service._parse_intent_response("")
        assert result.is_existing_feature is False
        assert result.confidence == 0.0

    def test_parse_garbage_response(self, intent_service):
        result = intent_service._parse_intent_response("這完全不是JSON")
        assert result.is_existing_feature is False

    def test_normalize_invalid_category(self, intent_service):
        result = IntentResult(
            is_existing_feature=True,
            category="weather",
            action="query",
            content="",
            confidence=0.9,
        )
        normalized = intent_service._normalize_intent_result(result)
        assert normalized.is_existing_feature is False
        assert normalized.confidence == 0.0

    def test_normalize_azure_blocks_model_category(self, intent_service):
        intent_service.config.openai.use_azure = True
        result = IntentResult(
            is_existing_feature=True,
            category="model",
            action="select",
            content="gpt-4o",
            confidence=0.9,
        )
        normalized = intent_service._normalize_intent_result(result)
        assert normalized.is_existing_feature is False

    def test_normalize_valid_todo_category(self, intent_service):
        result = IntentResult(
            is_existing_feature=False,
            category="TODO",
            action="add",
            content="test",
            confidence=0.8,
        )
        normalized = intent_service._normalize_intent_result(result)
        assert normalized.category == "todo"
        assert normalized.is_existing_feature is True

    def test_confidence_clamped_to_valid_range(self, intent_service):
        result = IntentResult(
            is_existing_feature=True,
            category="todo",
            action="add",
            content="",
            confidence=1.5,
        )
        normalized = intent_service._normalize_intent_result(result)
        assert normalized.confidence == 1.0
