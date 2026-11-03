"""WP-D: Test dashboard URL file is written with mode 0o600."""

import os
import shutil
import tempfile
from pathlib import Path

from treemem.cli import _write_dashboard_url_file


def test_dashboard_url_file_mode():
    """Dashboard URL file should be written with mode 0o600."""
    d = tempfile.mkdtemp(prefix="treemem_wpd_")
    try:
        url_file = Path(d) / ".dashboard_url"
        _write_dashboard_url_file(url_file, "http://127.0.0.1:8765/?t=token")
        
        # Check file mode is 0o600 (rw-------)
        stat_info = url_file.stat()
        mode = stat_info.st_mode & 0o777
        assert mode == 0o600, f"Expected mode 0o600, got {oct(mode)}"
        
        # Verify content
        content = url_file.read_text(encoding="utf-8")
        assert content == "http://127.0.0.1:8765/?t=token\n"
    finally:
        shutil.rmtree(d, ignore_errors=True)
