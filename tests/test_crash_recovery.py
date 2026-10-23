"""Tests for crash recovery: killing processes mid-write and verifying invariant recovery."""

import multiprocessing
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from treemem.health import HealthChecker
from treemem.store import NodeData, Store
from treemem.tree_manager import TreeManager


@pytest.fixture
def vault():
    d = tempfile.mkdtemp(prefix="treemem_crash_")
    v = Path(d)
    yield v
    shutil.rmtree(d, ignore_errors=True)


def test_crash_mid_atomic_write(vault):
    """Simulate a crash that leaves an uncommitted .tmp file; verify startup cleans it and passes health."""
    mgr = TreeManager(vault)

    # Establish an initial healthy state
    rem = mgr.remember("Initial verified fact", hint="system/core")
    mgr.place(rem["entry_id"], "system/core")

    # Manually simulate a crash that occurred while writing a new summary:
    # A .tmp file was created and partially written before the process was killed
    tmp_file = vault / "system" / "summary.md.tmp"
    with open(tmp_file, "w") as f:
        f.write("---\nname: system\ncorrupted_half_written: true\n")

    # Initial check before cleanup sees the stray tmp
    checker_before = HealthChecker(mgr.store, mgr.log_writer)
    health_before = checker_before.check_all()
    assert health_before["ok"] is False
    assert any(v["invariant"] == 7 for v in health_before["violations"])

    # Startup recovery: new TreeManager instance runs store.cleanup_temp_files()
    recovered_mgr = TreeManager(vault)
    health_after = recovered_mgr.health_checker.check_all()
    assert health_after["ok"] is True
    assert not tmp_file.exists()


def _continuous_writer_process(vault_str: str, stop_flag):
    """Child process that continuously creates nodes and writes facts."""
    vault = Path(vault_str)
    mgr = TreeManager(vault)
    idx = 0
    while not stop_flag.value:
        try:
            rem = mgr.remember(f"Fact from worker {idx}", hint=f"crash_test/node_{idx % 5}")
            mgr.place(rem["entry_id"], f"crash_test/node_{idx % 5}")
            idx += 1
            time.sleep(0.005)
        except Exception:
            pass


def test_hard_kill_during_active_writes(vault):
    """Spawn active writer process, kill with SIGKILL abruptly, verify vault recovers cleanly."""
    vault_str = str(vault.resolve())

    # Pre-init vault
    mgr = TreeManager(vault)
    rem = mgr.remember("Baseline fact before crash", hint="baseline")
    mgr.place(rem["entry_id"], "baseline")

    # Spawn worker subprocess using python -c
    worker_script = f"""
import time, sys
from pathlib import Path
from treemem.tree_manager import TreeManager

mgr = TreeManager(Path(sys.argv[1]))
idx = 0
while True:
    try:
        rem = mgr.remember(f"Active fact {{idx}}", hint=f"active_nodes/n_{{idx % 3}}")
        mgr.place(rem["entry_id"], f"active_nodes/n_{{idx % 3}}")
        idx += 1
        time.sleep(0.002)
    except Exception:
        pass
"""

    proc = subprocess.Popen([sys.executable, "-c", worker_script, vault_str])
    time.sleep(0.1)  # Let worker perform multiple atomic writes

    # Send SIGKILL (abrupt ungraceful termination)
    proc.kill()
    proc.wait()

    # Re-instantiate TreeManager to simulate service restart
    restarted_mgr = TreeManager(vault)
    health = restarted_mgr.health_checker.check_all()

    # If any node was left dirty or intermediate node lacked summary due to kill,
    # rebuild from ground-truth log restores complete integrity
    if not health["ok"]:
        restarted_mgr.rebuild()
        health = restarted_mgr.health_checker.check_all()

    assert health["ok"] is True, f"Vault failed health check after restart: {health['violations']}"
    assert health["total_facts"] >= 1
