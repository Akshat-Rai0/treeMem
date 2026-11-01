"""Tests for tokenizer visibility and offline fallback."""

from treemem import tokenizer


def test_tokenizer_name_cl100k_when_encoder_present(monkeypatch):
    class FakeEncoder:
        def encode(self, text):
            return [1] * len(text.split())

    monkeypatch.setattr(tokenizer, "_ENCODER", FakeEncoder())
    assert tokenizer.tokenizer_name() == "cl100k_base"


def test_tokenizer_name_fallback_when_encoder_none(monkeypatch):
    monkeypatch.setattr(tokenizer, "_ENCODER", None)
    assert tokenizer.tokenizer_name() == tokenizer.FALLBACK_NAME
    assert tokenizer.count_tokens("The quick brown fox jumps over the lazy dog.") >= 1
    assert tokenizer.count_tokens("") == 0
