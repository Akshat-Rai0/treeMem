"""Server-side policy for revealing private memory.

An agent can pass reveal=true in a tool call, but the model should not be able to
grant itself access to private data. Reveal is therefore honored only when the human
who starts the server has granted it through the environment, for example:

    TREEMEM_ALLOW_REVEAL=1 python -m treemem.cli serve

Direct Python callers (tests, the CLI, the dashboard with its own token) use the
TreeManager API directly and are not affected by this policy.
"""

import os
from typing import Tuple

ENV_VAR = "TREEMEM_ALLOW_REVEAL"

DENIED_NOTE = (
    "Reveal was requested but is not granted on this server, so private content stays hidden. "
    "Tell the user the information is private and ask them to grant access "
    f"(the server operator sets {ENV_VAR}=1). Do not retry with reveal=true."
)


def reveal_granted() -> bool:
    """True only when the server operator has explicitly granted reveal."""
    return os.environ.get(ENV_VAR, "").strip() == "1"


def resolve_reveal(requested: bool) -> Tuple[bool, bool]:
    """Return (effective_reveal, denied).

    effective_reveal is what should be passed to the TreeManager.
    denied is True when the caller asked for reveal but the policy refused it.
    """
    if not requested:
        return False, False
    if reveal_granted():
        return True, False
    return False, True
