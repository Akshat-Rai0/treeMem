"""Token counting using a fixed cl100k_base tokenizer.

If the tokenizer data cannot be loaded (for example offline, where tiktoken cannot download it), a rough
word-count estimate is used instead. The estimate runs about 25% to 30% LOW, so every benchmark records which
tokenizer produced its numbers (see tokenizer_name()).
"""

import logging

import tiktoken

logger = logging.getLogger("treemem.tokenizer")

try:
    _ENCODER = tiktoken.get_encoding("cl100k_base")
except Exception:
    _ENCODER = None
    logger.warning(
        "tiktoken could not load cl100k_base (offline?). Token counts are a rough estimate that runs about 25-30% low."
    )

FALLBACK_NAME = "fallback-estimate"


def tokenizer_name() -> str:
    """'cl100k_base' when real counts are in use, 'fallback-estimate' otherwise."""
    return "cl100k_base" if _ENCODER is not None else FALLBACK_NAME


def tokenizer_is_fallback() -> bool:
    """Whether token counts use the conservative local estimate."""
    return _ENCODER is None


def count_tokens(text: str) -> int:
    """Return the number of tokens in the given text using cl100k_base."""
    if not text:
        return 0
    if _ENCODER is not None:
        try:
            return len(_ENCODER.encode(text))
        except Exception:
            pass
    # Fallback heuristic: roughly 0.75 words per token (underestimates real counts)
    words = text.split()
    return max(1, int(len(words) * 1.33))
