"""Tests for generic usage extraction."""

from sdk.pricing.extractors import Extractor, get_extractor


class TestExtractor:
    """Test generic usage extraction."""

    def test_extract_usage_from_input_output_tokens(self):
        response = {
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_creation_input_tokens": 25,
                "cache_read_input_tokens": 10,
            }
        }

        usage = Extractor().extract_usage(response)

        assert usage is not None
        assert usage["input_tokens"] == 100
        assert usage["output_tokens"] == 50
        assert usage["cache_creation_tokens"] == 25
        assert usage["cache_read_tokens"] == 10

    def test_extract_usage_from_prompt_completion_tokens(self):
        response = {
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "cached_prompt_tokens": 20,
            }
        }

        usage = Extractor().extract_usage(response)

        assert usage is not None
        assert usage["input_tokens"] == 100
        assert usage["output_tokens"] == 50
        assert usage["cache_read_tokens"] == 20

    def test_extract_model(self):
        model = Extractor().extract_model({"model": "custom-model-v1"})

        assert model == "custom-model-v1"

    def test_extract_stop_reason(self):
        stop_reason = Extractor().extract_stop_reason({"stop_reason": "end_turn"})

        assert stop_reason == "end_turn"


class TestExtractorLookup:
    """Test generic extractor lookup."""

    def test_get_extractor_for_named_provider(self):
        extractor = get_extractor("custom-provider")

        assert isinstance(extractor, Extractor)

    def test_get_extractor_requires_provider_name(self):
        extractor = get_extractor("")

        assert extractor is None
