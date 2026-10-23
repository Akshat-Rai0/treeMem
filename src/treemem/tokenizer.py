"""Token counting using a fixed cl100k_base tokenizer."""

import tiktoken

try:
    _ENCODER = tiktoken.get_encoding("cl100k_base")
except Exception:
    _ENCODER = None


def count_tokens(text: str) -> int:
    """Return the number of tokens in the given text using cl100k_base."""
    if not text:
        return 0
    if _ENCODER is not None:
        try:
            return len(_ENCODER.encode(text))
        except Exception:
            pass
    # Fallback heuristic: roughly 4 chars or 0.75 words per token
    words = text.split()
    return max(1, int(len(words) * 1.33))
