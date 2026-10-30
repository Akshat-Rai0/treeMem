# TreeMem 🌲

> **Hierarchical, agent-writable memory for LLM agents exposed as a Model Context Protocol (MCP) server, stored as a plain folder of human-readable Markdown, with a live local web dashboard that visualizes every recall.**

[![CI](https://github.com/Akshat-Rai0/treeMem/actions/workflows/ci.yml/badge.svg)](https://github.com/Akshat-Rai0/treeMem/actions/workflows/ci.yml)
[![Tests: 128 Passing](https://img.shields.io/badge/tests-128%20passed-brightgreen.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)]()
[![MCP: 2024-11-05](https://img.shields.io/badge/MCP-compatible-purple.svg)](https://modelcontextprotocol.io/)

---

## Table of Contents

1. [The Core Idea](#1-the-core-idea)
2. [Why TreeMem? The Problem with Flat Memory & Naive RAG](#2-why-treemem-the-problem-with-flat-memory--naive-rag)
3. [System Architecture](#3-system-architecture)
4. [The 8 System Invariants](#4-the-8-system-invariants)
5. [Quickstart in 3 Commands](#5-quickstart-in-3-commands)
6. [Live X-Ray Dashboard](#6-live-x-ray-dashboard)
7. [MCP Tool Reference & Harness Configuration](#7-mcp-tool-reference--harness-configuration)
8. [Instruction-File Fallback (Zero-MCP Mode)](#8-instruction-file-fallback-zero-mcp-mode)
9. [Vault Specification & File Formats](#9-vault-specification--file-formats)
10. [CLI Reference](#10-cli-reference)
11. [Benchmarks & Honest Evaluation](#11-benchmarks--honest-evaluation)
12. [Testing & Crash Recovery](#12-testing--crash-recovery)
13. [Limitations & Trade-offs](#13-limitations--trade-offs)
14. [Roadmap](#14-roadmap)

---

## 1. The Core Idea

When an agent needs information, dumping every memory ever recorded into context wastes thousands of prompt tokens and drowns out the prompt's instructions.

TreeMem organizes memory as a **hierarchical tree of topic nodes**:
- **Parent nodes** contain concise summaries (40–120 tokens) and 1-line teasers for their children.
- **Child nodes** unpack greater topical detail.
- **Leaf nodes** store raw, granular facts referencing an append-only daily ledger.

When an agent queries TreeMem, it starts at the root summary (`recall("/")`). If the parent summary answers the query directly, the agent **stops immediately ("parent-stop")** having consumed fewer than 100 tokens. Only if the query demands specific detail does the agent step down one branch (`recall("/topic")` or `expand`).

> **The Library Analogy:** A library catalog card is the root parent, the floor section is a child, and the shelf book is a leaf. You never pull all 50,000 books off the shelf just to look up a publishing date.

---

## 2. Why TreeMem? The Problem with Flat Memory & Naive RAG

| Approach | Token Scaling | Topical Drill-down | Developer Observability | Privacy Guarantees |
|:---|:---:|:---:|:---:|:---:|
| **Flat Scratchpad / Notes** | $O(N)$ context explosion | ❌ All or nothing | ❌ None | ❌ Full context leak |
| **Top-K Vector RAG** | Unbounded chunk fragments | ❌ Loss of hierarchy | ❌ Black-box cosine distance | ⚠️ Chunk-level only |
| **Chronological Trees (OptMem)** | Balanced binary tree | ❌ No topical branches | ⚠️ Limited | ❌ No privacy masks |
| **TreeMem 🌲** | **$O(\log N)$ descent** | ✅ **Agent-guided descent** | ✅ **Live Cytoscape X-Ray** | ✅ **Descent masks & leak guards** |

### Key Differentiators:
1. **Agent-Guided Descent (Parent-Stop)**: Recalling the root gives a parent summary and child teasers. The agent decides if the parent summary is sufficient or if it needs to descend into child branches.
2. **Transparent, Zero-Lock-In Storage**: The memory vault is a standard directory of human-readable Markdown files with YAML frontmatter, 100% compatible with Obsidian and standard CLI tools (`cat`, `grep`).
3. **Append-Only Ground Truth**: `log/YYYY-MM-DD.md` stores every fact permanently. The hierarchical tree is a derived, rebuildable cache.
4. **Agent-Written Summaries (No Server LLM Hosting)**: TreeMem never runs or hosts an LLM model, requiring no OpenAI or Anthropic API keys. The server hands out compression prompts; the agent writes the summary; the server rigorously validates token caps and child lists before committing atomically.
5. **Staleness Tracking**: When a leaf is written, all ancestor directories are marked `dirty: true`. Recalls flag stale summaries, prompting bottom-up compression.
6. **Built-in Privacy Bounds**: Sensitive subtopics (`sensitivity: private`) are masked in ancestor teasers as `"contains private details, expand to view"` and are protected against leakages by automated substring and token-overlap validator checks.

---

## 3. System Architecture

```
Agent Harness (Antigravity / Devin / Claude Desktop / Cursor)
       │  MCP (JSON-RPC stdio transport)
       ▼
┌────────────────── TreeMem Server (Single Process) ──────────────────┐
│                                                                     │
│  mcp_layer.py ────► remember, place, recall, expand, compress,       │
│                     commit_summary, search, split, rebuild, status  │
│       │                                                             │
│  tree_manager.py ─► Path resolution, dirty propagation,             │
│       │             branching caps, privacy leakage validators      │
│       │                                                             │
│       ├── store.py         (Atomic tmp-and-rename writes, locks)    │
│       ├── log_writer.py    (Append-only daily ledger YYYY-MM-DD)    │
│       ├── index.py         (BM25 lexical index over logs & leaves)  │
│       ├── health.py        (Validator asserting all 8 invariants)   │
│       └── event_bus.py ──► SSE stream broadcast                     │
│                                   │                                 │
└───────────────────────────────────┼─────────────────────────────────┘
                                    │ HTTP + SSE (127.0.0.1:8765)
                                    ▼
┌───────────────────── X-Ray Web Dashboard ───────────────────────────┐
│  Cytoscape.js Canvas | Live Recall Path | Inspector | Replay Engine  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────── Local Vault Filesystem (memory/) ─────────────────┐
│  summary.md               (Root catalog summary & child teasers)    │
│  ├── identity/summary.md  (Subtopic summary & facts)                │
│  ├── projects/summary.md  (Subtopic summary & facts)                │
│  └── log/YYYY-MM-DD.md    (Append-only permanent ground truth)      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 4. The 8 System Invariants

TreeMem is built around 8 strict structural invariants verified by [`treemem check`](file:///Users/bipinkumarrai/Desktop/EVERYTHING/CODING%20PROJECTS/PORTFOLIO%20PROJ/treeMem/src/treemem/cli.py) and enforced continuously across all test suites:

1. **Node Completeness**: Every directory under the vault root (except `log/` and hidden folders) contains a valid `summary.md` with YAML frontmatter.
2. **Log Ground Truth**: Every fact in every node references an existing, valid log entry ID (`YYYY-MM-DD#line`).
3. **Child Directory Parity**: The `## Children` list in a node's `summary.md` strictly matches the actual child subdirectories on disk (no missing, no invented children).
4. **Rebuildability**: Wiping the tree and running `treemem rebuild` reconstructs all nodes and facts faithfully from the append-only log files.
5. **No Private Leakage**: An ancestor's summary text never leaks keywords, facts, or tokens from any descendant marked `sensitivity: private`.
6. **Dirty Propagation**: Adding a fact to a node immediately marks that node and every ancestor path up to the root as `dirty: true`.
7. **Atomic Operations**: No write leaves lingering `.tmp` files on disk, even if aborted or interrupted.
8. **Append-Only Ledger**: Existing lines in `log/YYYY-MM-DD.md` are never edited or truncated.

---

## 5. Quickstart in 3 Commands

### Step 1: Install TreeMem
Requires Python 3.10+. We recommend using [`uv`](https://github.com/astral-sh/uv):

```bash
git clone https://github.com/Akshat-Rai0/treeMem.git
cd treeMem
uv venv && uv pip install -e .
```

### Step 2: Initialize a Vault
Create a clean memory directory structure:

```bash
treemem init ./my_memory
```

This creates `./my_memory/summary.md` and `./my_memory/log/`.

### Step 3: Launch the Live X-Ray Dashboard
Run the dashboard server locally on port 8765:

```bash
treemem serve ./my_memory --port 8765
```

Open the authenticated URL printed in your terminal (e.g. `http://127.0.0.1:8765/?t=<token>`).

> **Instant Demo**: To test the dashboard immediately without an agent or memory files:
> ```bash
> treemem serve --demo
> ```
> This loads an interactive sandbox with 28 topic nodes and plays an animated live recall sequence.

---

## 6. Live X-Ray Dashboard

TreeMem includes a local, read-only web dashboard served directly by the server:

- **Graph Canvas**: Interactive Cytoscape.js canvas supporting both top-down **Hierarchical Tree** and **Radial** layouts.
- **Visual Encoding**:
  - **Teal Glow**: Traversed nodes and edges in the current recall path.
  - **Dashed Border**: Dirty nodes whose child facts have updated.
  - **Lock Icon**: Private nodes protected from ancestor leaks.
  - **Node Size**: Dynamically scaled based on token count (clamped 40–150 tokens).
- **Inspector Panel**: Click any node to view its frontmatter metadata, summary, child teasers, and recent log events.
- **Token Comparison Meter**: Shows exact tokens consumed by the current descent vs. a flat dump baseline of all leaf facts.
- **Time-Travel Replay Bar**: Step through multi-hop recalls forward and backward, with adjustable playback speeds (0.5x, 1x, 2x).
- **Health Indicator**: Real-time badge asserting invariant compliance (Green = Clean, Amber = Dirty nodes pending compression, Red = Invariant violation).

---

## 7. MCP Tool Reference & Harness Configuration

### Harness Setup (stdio Transport)

Add TreeMem to your agent harness configuration (e.g. Claude Desktop, Antigravity, Cursor, or Devin):

#### Claude Desktop (`claude_desktop_config.json`) / Antigravity (`mcp_config.json`):
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

### The 10 MCP Tools

| Tool | Parameters | Description |
|:---|:---|:---|
| `remember` | `fact: str, hint?: str` | Appends fact to today's log, returns entry ID and candidate topic paths. |
| `place` | `entry_id: str, path: str, sensitivity?: str` | Places fact into a leaf node and marks all ancestors `dirty`. |
| `recall` | `path: str = "/"`, `query?: str`, `follow?: bool`, `max_depth?: int` | Reads node summary and 1-line child teasers (**never** child bodies). With `query` it adds the descent-gate verdict; with `follow=true` the server follows the gate read-only (never into private nodes) and returns where it stopped, in one call. |
| `expand` | `path: str, reveal: bool = false` | Drills down into child summaries or raw leaf facts. `reveal=true` is only honored when the server operator set `TREEMEM_ALLOW_REVEAL=1`; otherwise private content stays hidden and the result carries `reveal_denied`. |
| `compress` | `path: str` | Returns compression prompt and child text to clean a dirty node (Option A). |
| `auto_compress` | `path?: str` | (Optional) Compresses dirty nodes bottom-up using an external LLM (Groq); reads API keys from `.env`. |
| `commit_summary` | `path: str, text: str` | Validates token cap, child list, and privacy before committing atomically. |
| `search` | `query: str, limit: int = 10, reveal: bool = False` | BM25 lexical search over log entries and leaves (fallback mechanism). Hits under private nodes are withheld unless `reveal=true` **and** the operator granted reveal (`TREEMEM_ALLOW_REVEAL=1`). |

**Reveal policy.** The model must not be able to grant itself access to private data, so `reveal=true` in a tool call is a *request*, not a switch. The MCP server honors it only when a human starts it with `TREEMEM_ALLOW_REVEAL=1`. Without that, `expand` and `search` return `reveal_denied: true` plus a note telling the agent to ask the user. Direct Python callers (tests, CLI, dashboard with its own token) use `TreeManager` directly and are not affected.

| `split` | `path: str, groups: dict` | Splits an overflowing node into subtopics to preserve branching caps. |
| `rebuild` | `path?: str` | Reconstructs tree structure from append-only log files. |
| `status` | *None* | Session-start health report with total nodes, facts, and dirty count. |

> **Note on Summarization Modes**:
> * **Default Mode (Option A)**: TreeMem hosts zero models and requires zero external API keys. The client agent generates the summary text and commits it via `commit_summary`.
> * **Pluggable Auto-Compressor (`auto_compress` / Option B)**: An optional background engine that uses an external LLM (Groq) to clean dirty nodes bottom-up. Requires `GROQ_API_KEY_1` or `GROQ_API_KEY` set in `.env` (which is git-ignored).

---

## 8. Instruction-File Fallback (Zero-MCP Mode)

If your harness does not support MCP or you prefer standard file execution, provide your agent with the following system prompt block (found in [`examples/AGENTS_md_block.md`](file:///Users/bipinkumarrai/Desktop/EVERYTHING/CODING%20PROJECTS/PORTFOLIO%20PROJ/treeMem/examples/AGENTS_md_block.md)):

```markdown
# TreeMem Memory Protocol

You have access to a persistent hierarchical memory vault located at `memory/`.

## 1. Reading Memory (Parent-First Descent)
1. Read the root catalog first:
   cat memory/summary.md
2. Check if the root summary or child teasers under `## Children` answer the question.
   If yes, STOP immediately (Parent-Stop).
3. If more detail is required, inspect only the relevant child topic:
   cat memory/<topic>/summary.md
4. Only read leaf notes if raw facts are required.

## 2. Storing New Facts
1. Append to today's daily log file (`memory/log/YYYY-MM-DD.md`):
   echo "- <next_id> | $(date -u +%H:%M:%SZ) | session=agent | fact: <text> | hint: <topic>" >> memory/log/$(date -u +%Y-%m-%d).md
2. Place the fact in the appropriate leaf node:
   echo "- <text> (log: $(date -u +%Y-%m-%d)#<next_id>)" >> memory/<topic>/summary.md
3. Set `dirty: true` in the YAML frontmatter of the leaf node and all ancestor directories up to the root.
```

---

## 9. Vault Specification & File Formats

### 1. Node Specification (`<path>/summary.md`)
```markdown
---
name: projects
aliases: [software, coding, portfolio]
dirty: false
updated: 2026-10-23T12:00:00Z
tokens: 82
sensitivity: normal
children_cap: 10
---
Portfolio projects including TreeMem, an MCP hierarchical memory server.

## Children
- [[treemem]] - Hierarchical agent-writable memory system
- [[sidecar]] - Molecular structure viewer plugin

## Facts
- Completed Phase 1 core storage and invariant tests (log: 2026-10-23#001)
```

### 2. Daily Log Specification (`log/YYYY-MM-DD.md`)
```markdown
- 001 | 10:12:03Z | session=default | fact: Building TreeMem MCP server | hint: projects/treemem
- 002 | 10:15:22Z | session=default | fact: Favorite language is Python | hint: skills/python
```

---

## 10. CLI Reference

```bash
# Initialize a new empty vault
treemem init [path]

# Assert all 8 system invariants (exits 0 if clean, 1 if violated)
treemem check [path]

# Reconstruct all nodes and facts from the append-only daily logs
treemem rebuild [path]

# Automatically compress dirty nodes bottom-up using server-side LLM (Option B)
treemem compress [path] [--node path]

# Start the local read-only web dashboard
treemem serve [path] --port 8765

# Start dashboard with background auto-compressor daemon active
treemem serve [path] --auto-compress

# Launch as a stdio MCP server for agent harnesses
treemem serve [path] --mcp

# Launch interactive demo sandbox with pre-built sample memory
treemem serve --demo
```

---

## 11. Benchmarks & Honest Evaluation

### Real LLM Agent Benchmark (`qwen/qwen3.8-27b` via Groq)
*Automated evaluation comparing single-prompt flat memory dump against autonomous TreeMem MCP tool descent ($n=12$ queries across identity, career, education, preferences, private finance, and out-of-domain negative controls):*

<!-- BENCHMARK_TABLE_REAL_START -->
| Metric | Flat Memory Dump | TreeMem Autonomous Descent | Impact |
|:---|:---|:---|:---|
| **Answer Accuracy** | **100.0%** (11/11) | **100.0%** (11/11) | Parity on the scored questions |
| **Memory Payload Tokens** | 7,812 tokens | **1,371 tokens** | **82.45% payload token reduction** |
| **Total API Wire Tokens** | **9,858 tokens** | 66,758 tokens | Multi-turn tool calling re-sends schema/prompts per hop |
| **Parent-Stop Rate** | N/A | **8.3%** (1/12) | Evaluated at root depth 0 when summary was sufficient |
| **Mean / Max Latency** | 0.81s / 2.79s | 19.36s / 30.99s | Multi-hop sequential tool execution latency |
| **Private Data Leaked** (1 private question) | 1 | 0 | Flat has no access control; TreeMem withholds private nodes unless the operator grants reveal |
<!-- BENCHMARK_TABLE_REAL_END -->

*Raw data committed in [`bench/results/llm_eval_results.json`](bench/results/llm_eval_results.json).*

> **The Multi-Turn Overhead Trade-Off:** On small vaults (<30 facts), flat context dumps are faster and cheaper in total API wire tokens (9,858 vs 63,695 tokens) because multi-turn tool calling retransmits the system prompt and tool definitions on every hop. However, TreeMem achieves an **82.76% reduction in memory payload**, proving that hierarchical descent prevents memory context saturation as vaults scale to hundreds and thousands of entries.

### Synthetic Vault Scaling Study
*Measuring memory payload token cost between flat note dumps vs. TreeMem hierarchical descent:*

<!-- BENCHMARK_TABLE_SYNTHETIC_START -->
| Memory Scale | Flat Dump Cost | TreeMem Average Cost | Token Savings |
|:---|:---|:---|:---|
| **100 memories** | 2,041 tokens | 110 tokens | **94.61%** |
| **1,000 memories** | 20,941 tokens | 223 tokens | **98.94%** |
| **10,000 memories** | 227,941 tokens | 1,465 tokens | **99.36%** |
<!-- BENCHMARK_TABLE_SYNTHETIC_END -->

*Raw data committed in [`bench/results/flat_vs_tree_tokens.json`](bench/results/flat_vs_tree_tokens.json).*

### Repeated runs: flat vs manual descent vs guided descent
<!-- BENCHMARK_TABLE_AGG_START -->
3 runs x 12 questions, `qwen/qwen3.8-27b`, mean ± std. Accuracy is over the non-private questions; latency excludes pacing sleeps.

| Arm | Accuracy % | Private leaks | Wire tokens | Mean hops | Single-call % | Mean latency (s) |
|:---|:---|:---|:---|:---|:---|:---|
| Flat dump | 100.0 ± 0.0 | 1.0 ± 0.0 | 9,858 ± 0 | 0.00 ± 0.00 | 0.0 ± 0.0 | 0.76 ± 0.15 |
| TreeMem, manual descent | 100.0 ± 0.0 | 0.0 ± 0.0 | 66,758 ± 0 | 3.83 ± 0.00 | 8.3 ± 0.0 | 18.98 ± 0.87 |
| TreeMem, guided descent (`follow=true`) | 100.0 ± 0.0 | 0.0 ± 0.0 | 48,356 ± 0 | 2.67 ± 0.00 | 33.3 ± 0.0 | 14.39 ± 1.12 |

_Std is 0 for accuracy, tokens and hops: temperature is 0 and the vault and questions are fixed, so repeated runs reproduce the same output. This shows reproducibility, not robustness._
<!-- BENCHMARK_TABLE_AGG_END -->

### Second model check
<!-- BENCHMARK_TABLE_AGG2_START -->
_Not measured yet._ Run `python bench/eval/run_eval.py --model <model-id> --out-dir bench/results_<name> --arms flat,tree_follow --runs 1`, then `python bench/eval/rebuild_aggregate.py --results-dir bench/results_<name> --regrade`, then `python bench/make_readme_tables.py`.
<!-- BENCHMARK_TABLE_AGG2_END -->

### Descent gate, offline check (no API calls)
`python bench/gate_offline_eval.py --set all --compare` asks, for each question: does the text returned by ONE `recall(follow=true)` call contain the answer? A "stop" where it does not is a **premature stop**. The held-out questions were written before the gate was changed and use different wording from the dev questions.

<!-- GATE_TABLE_START -->
| Question set | Gate | Answerable from first call | Premature stops | Mean steps | Private leaks |
|:---|:---|:---|:---|:---|:---|
| 12 dev questions | legacy | 5/10 | q02_profession, q05_career_overview, q06_college_name, q09_project (4) | 0.417 | 0 |
| 12 dev questions | current | 9/10 | none (0) | 0.833 | 0 |
| 26 held-out questions | legacy | 10/19 | h06_intern, h08_degree, h10_classes (3) | 0.346 | 0 |
| 26 held-out questions | current | 12/19 | h06_intern (1) | 0.462 | 0 |

_Measured with scikit-learn installed (hybrid TF-IDF + lexical scoring). Numbers differ slightly between the two modes._
<!-- GATE_TABLE_END -->

The current gate counts a stop as sufficient only when the node summary covers the question's own words (a literal match counts more than a synonym), prefers a child that contains words the parent lacks, and descends when a child scores close to the parent, because a wrong stop is costly while an extra server-side step is nearly free. One parameter (`descend_ratio`) was chosen after seeing both sets, so the held-out set is no longer clean; the choice sits on a plateau (0.2 to 0.4 give the same results). Remaining misses are mostly vocabulary mismatches (for example "employs" against "Work history") and one routing error (`h06`: "intern before his current job" went to `current_job`). Those need better synonyms or embeddings, which I did not add to avoid fitting the sample vault.

### Known limitations (read before quoting numbers)
- **Repeated runs are not independent samples.** The model runs at temperature 0 on a fixed vault with fixed questions, so the committed 3-run result reproduced the same tokens, hops and answers every time (std = 0). That shows the harness is reproducible, not that the numbers are robust. Real variance needs paraphrased questions, a larger question set, or sampling at temperature above 0.
- **Small sample.** 12 questions (11 scored) on an 8-fact vault. Treat 100% accuracy as "no failures observed on this set", not as a measured accuracy.
- **A flat dump still wins on this vault.** Every tool call re-sends the system prompt and tool schemas (about 1,100 prompt tokens per call), so even a single guided call costs more than the whole flat dump. Guided descent cut total tokens and hops compared with manual descent in the committed runs, but not below the flat baseline. The memory-payload reduction (the tree returns far less memory text) does not become a total-token win at this size.
- **Guided descent does not always help.** In the committed runs it answered some questions in one call, but on others (for example the negative control and the private question) it cost as much as or more than manual descent.
- **Premature stops are the real accuracy risk.** The gate used to decide the root summary was sufficient when it only shared words with the question; with gpt-oss-120b the agent then answered "personal memory vault" for a question whose answer is a named project. The gate is changed (see the offline table above) but the fix is **not yet confirmed with a real LLM**; re-run `run_eval.py` on both models. A wrong stop looks like a confident answer, so keep measuring it on a larger question set.
- **Results are model-dependent.** The same tree answered a question in one call with one model and needed several calls with another. Do not generalize from one model.
- **The grader matters.** An earlier grader marked correct flat answers wrong because of a no-break space and a curly apostrophe. Answers are now normalized before matching, and `python bench/eval/rebuild_aggregate.py --regrade` re-grades saved runs with the current grader without any API calls.
- The descent gate is a lexical + TF-IDF heuristic over summaries. If the question's words are not in the summaries it falls back to search.
- Break-even against flat is not measured. A rough extrapolation: the guided arm averaged about 4,000 wire tokens per question, so flat should lose once the log grows to roughly 6x its current size. Verify this with a larger vault before claiming it.

### Plumbing Smoke Test ($n=5$, Scripted Descent)
<!-- SMOKE_BLOCK_START -->
- **Token Reduction**: 9.2% on a small 8-fact vault.
- **Parent-Stop Rate**: 20.0% (depth 0).
- **Descent Latency**: p50 = 2.29 ms, p95 = 2.87 ms.
- *Raw data committed in [`bench/results/smoke_test_results.json`](bench/results/smoke_test_results.json).*
<!-- SMOKE_BLOCK_END -->

---

## 12. Testing & Crash Recovery

The test suite covers unit behavior, concurrent writers, crash simulation, security, and randomized property sequences:

```bash
PYTHONPATH=src python3 -m pytest tests/ -q
```

```
........................................................................ [100%]
============================== 128 passed in 3.27s ==============================
```

- **Crash Mid-Write Simulation**: Tests deliberately simulate process crashes (`SIGKILL` / interrupted writes) during atomic file operations to confirm that corruptions and stray `.tmp` files never persist.
- **Property-Based Testing**: Randomized multi-step operations (`remember` $\to$ `place` $\to$ `recall` $\to$ `search`) verify that all 8 invariants hold under arbitrary mutation sequences.

---

## 13. Limitations & Known Issues

1. **Small Vaults Favor Flat Dump**: On vaults with fewer than ~30 facts, a single flat context dump is faster and consumes fewer total API wire tokens (9,858 vs 63,695 tokens) because multi-turn tool calling re-transmits tool definitions and system prompts on every hop.
2. **The Agent Over-Descends**: Without single-call guided descent (`follow=True`), autonomous agents frequently take 4–6 tool calls when a parent summary was already sufficient to answer the question.
3. **Negative-Control Exhaustion**: When queried about facts absent from the vault (e.g., favorite sports car brand), agents tend to exhaust their multi-hop turn budget searching alternative branches before concluding the information is unknown.
4. **Single-Agent Local Focus**: Designed as a local daemon for single-agent sessions; multi-user distributed synchronization is out of scope.

---

## 14. Roadmap

- [x] **Phase 0**: Harness feasibility notes, prior art analysis, and sample vault.
- [x] **Phase 1**: Atomic markdown store, daily log writer, branching enforcement, and 8 invariants.
- [x] **Phase 2**: MCP server with 10 tools, BM25 indexing, and Option A agent summarization.
- [x] **Phase 3**: Event bus, SSE streaming, and Cytoscape.js X-Ray dashboard.
- [x] **Phase 5**: Concurrency locking, crash recovery tests, and security hardening.
- [ ] **Phase 4**: Automated LongMemEval benchmark harness with real LLM inference.
- [ ] **v1.5**: Transclusion for volatile scalar facts (`![[node#line]]` markdown embeds).
- [ ] **v2**: Learned descent classifier gating, native Obsidian plugin, and hybrid vector index.

---

## License

Distributed under the [MIT License](LICENSE).
