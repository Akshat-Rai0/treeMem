# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2026-10-23

### Changed
- Relabeled scaling benchmarks explicitly as synthetic vault with scripted descent (tokens only).
- Renamed smoke test script from `longmemeval_subset.py` to `smoke_test.py` and its results to `smoke_test_results.json`.
- Replaced personal data in `examples/sample_memory/` and test fixtures with a fictional persona (`Alex Mercer`).
- Updated README benchmark section to honest interim status.
- Added harness compatibility status table with untested flags across external tools.

### Removed
- Removed legacy `files (1)` folder after ensuring all documentation is preserved in `docs/`.

### Added
- GitHub Actions CI workflow (`.github/workflows/ci.yml`) running pytest and vault health checks across Python 3.10-3.13.
- Enhanced `.gitignore` rules for `.events/`, API secrets, and large benchmark artifacts.

## [0.1.0] - 2026-10-22

### Added
- Initial core implementation of TreeMem hierarchical memory architecture.
- Append-only daily log writer with root-to-leaf atomic lock ordering.
- Cytoscape.js X-Ray dashboard with live Server-Sent Events (SSE).
- FastMCP / MCPServer stdio integration with 10 tools.
- Health validator enforcing all 8 system invariants.
