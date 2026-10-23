# TreeMem 🌲

> **Hierarchical, agent-writable memory for LLM agents exposed as an MCP server, stored as a plain folder of markdown, with a local web dashboard that visualizes every recall.**

[![Tests](https://img.shields.io/badge/tests-21%20passed-brightgreen.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)]()

---

## 1. The One-Line Pitch

An agent reads a concise parent node summary first and descends into child branches only when the question requires more detail, slashing recall token costs by up to **99.3%** at identical accuracy.

**Analogy:** A library catalog card is the parent, the shelf section is a child, and the book is a leaf fact. The agent only walks as far as the query demands.

---

## 2. Key Architecture

```
Agent Harness (Antigravity / Devin / Claude Desktop)
       │  MCP (stdio transport)
       ▼
┌────────────────── Memory Server (Single Process) ──────────────────┐
│  mcp_layer    -> remember, place, recall, expand, compress,         │
│                  commit_summary, search, split, rebuild, status     │
│       │                                                            │
│  tree_manager  (paths, dirty propagation, caps, privacy checks)     │
│       │                 │                  │                        │
│  store (atomic fs)    log_writer (append)  index (BM25 over log)   │
│       │                 │                  │                        │
│  event_bus ───────────────────────────────► dashboard_server       │
└─────────────────────────────────────────────┬──────────────────────┘
                                              │ HTTP + SSE (127.0.0.1)
                                              ▼
                                    Browser Dashboard (Cytoscape.js)

 Disk: memory/ (tree folders with summary.md + log/YYYY-MM-DD.md)
```

- **Append-Only Ground Truth**: `log/YYYY-MM-DD.md` stores every fact permanently. The tree is a derived, rebuildable cache.
- **Agent-Written Summaries**: No server-side LLM hosting or API keys. The server hands out compression prompts; the agent returns text; the server validates length, child lists, and privacy before committing.
- **Staleness Tracking**: New writes mark the node and all ancestors `dirty`. Recalls flag stale summaries, and compression proceeds bottom-up.
- **Privacy Protection**: Nodes marked `sensitivity: private` never leak into ancestor summaries. Ancestors display `"contains private details, expand to view"` and private bodies require `reveal=true`.

---

## 3. Benchmark Results (Committed Data)

Benchmarked on synthetic memory vaults and the `LongMemEval` question-answering subset:

### Token Scaling: Flat Dump vs. TreeMem Descent

| Number of Memories | Flat Dump Cost | TreeMem Average Cost | Token Savings |
|:-------------------|:---------------|:---------------------|:--------------|
| **100 memories**   | 2,041 tokens   | 110 tokens           | **94.61%**    |
| **1,000 memories** | 20,941 tokens  | 223 tokens           | **98.94%**    |
| **10,000 memories**| 227,941 tokens | 1,465 tokens         | **99.36%**    |

### Quality & Latency Metrics
- **Answer Accuracy**: **100.0%** on target questions.
- **Parent-Stop Rate**: **20.0%** answered at depth 0 without child descent (Correctness: **100%**).
- **Recall Latency**: p50 = **1.79 ms**, p95 = **2.01 ms**.
- *Raw data committed in [`bench/results/flat_vs_tree_tokens.json`](bench/results/flat_vs_tree_tokens.json) and [`bench/results/longmemeval_results.json`](bench/results/longmemeval_results.json).*

---

## 4. Quickstart in 3 Commands

### 1. Installation
```bash
git clone https://github.com/akshat/treemem.git
cd treemem
uv venv && uv pip install -e .
```

### 2. Initialize a Vault
```bash
treemem init ./my_memory
```

### 3. Launch the Live X-Ray Dashboard
```bash
treemem serve ./my_memory --port 8765
```
Or run demo mode with pre-populated data and a live animated recall sequence:
```bash
treemem serve --demo
```

---

## 5. MCP Server Configuration

To connect TreeMem to an agent harness (Antigravity, Claude Desktop, Cursor, or Devin), add to your MCP settings:

```json
{
  "mcpServers": {
    "treemem": {
      "command": "treemem",
      "args": ["serve", "/absolute/path/to/my_memory", "--mcp"]
    }
  }
}
```

### MCP Tools Provided
- `remember(fact, hint?)`: Log a new fact and receive candidate topic paths.
- `place(entry_id, path, sensitivity?)`: Place fact into a leaf topic and dirty ancestors.
- `recall(path="/")`: Read concise parent summary and 1-line child teasers (**never** child bodies).
- `expand(path, reveal=false)`: Drill down into child summaries or raw leaf facts.
- `compress(path)`: Receive compression prompt and input summaries to clean a dirty node.
- `commit_summary(path, text)`: Atomically validate and commit a rewritten summary.
- `search(query, limit=10)`: BM25 search over all log entries and leaves (descent fallback).
- `split(path, groups)`: Split an overflowing node into intermediate subtopics.
- `rebuild(path?)`: Rebuild tree structure from ground truth log files.
- `status()`: Session-start health and dirty node count report.

---

## 6. CLI Reference

- `treemem init [path]`: Initialize a new memory vault.
- `treemem check [path]`: Assert all 8 system invariants (exits 0 if clean, 1 if violations).
- `treemem rebuild [path]`: Reconstruct vault from append-only logs.
- `treemem serve [path] [--port 8765] [--demo] [--mcp]`: Launch web dashboard or stdio MCP server.

---

## 7. Limitations & v1 Scope
- **Non-goals**: No learned descent classifier (v2), no vector embedding database (uses lexical BM25), no remote cloud sync.
- **Where it loses**: On small vaults (<30 facts), flat dump token overhead is negligible and descent requires multiple round-trips. TreeMem's advantages become decisive as memories scale beyond 100 entries.
