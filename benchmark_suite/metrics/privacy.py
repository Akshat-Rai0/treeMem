"""Privacy and reliability metric helpers."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence


def privacy_case_metrics(cases: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    cases = list(cases)
    total = len(cases)
    passed = sum(1 for c in cases if c.get("passed"))
    leaks = sum(1 for c in cases if c.get("leak"))
    false_denials = sum(1 for c in cases if c.get("false_denial"))
    authorized_success = sum(1 for c in cases if c.get("authorized_success"))
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "failure_rate": (total - passed) / total if total else 0.0,
        "leak_count": leaks,
        "leak_rate": leaks / total if total else 0.0,
        "false_denial_count": false_denials,
        "false_denial_rate": false_denials / total if total else 0.0,
        "authorized_success_count": authorized_success,
        "authorized_success_rate": authorized_success / total if total else 0.0,
    }


def reliability_metrics(events: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    events = list(events)
    total = len(events)
    recovered = sum(1 for e in events if e.get("recovered"))
    data_loss = sum(1 for e in events if e.get("data_loss"))
    corruption = sum(1 for e in events if e.get("corruption"))
    duplicates = sum(1 for e in events if e.get("duplicate_reconstruction"))
    durations = [e.get("recovery_ms") for e in events if isinstance(e.get("recovery_ms"), (int, float))]
    return {
        "total": total,
        "recovered": recovered,
        "recovery_rate": recovered / total if total else 0.0,
        "data_loss_count": data_loss,
        "data_loss_rate": data_loss / total if total else 0.0,
        "corruption_count": corruption,
        "corruption_rate": corruption / total if total else 0.0,
        "duplicate_reconstruction_count": duplicates,
        "duplicate_reconstruction_rate": duplicates / total if total else 0.0,
        "recovery_ms_values": durations,
    }
