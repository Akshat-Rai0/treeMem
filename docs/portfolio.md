# TreeMem: Portfolio Project Card & Resume Highlights

> **Hierarchical, agent-writable memory for LLM agents exposed as an MCP server with a live local web dashboard.**

---

## 1. Executive Summary & Pitch

- **The Problem:** Modern LLM agents rely on flat scratchpads (which blow up prompt contexts as notes accumulate) or naive vector search (which destroys relational hierarchies and provides zero developer observability).
- **The Solution:** TreeMem structures persistent memory as a hierarchical directory of Markdown files with YAML frontmatter. Agents start at a concise root summary (`recall("/")`) and only descend into child topics if the query demands greater detail, enabling **parent-stops** that save up to 99% of memory payload tokens.
- **Observability:** A local Cytoscape.js dashboard visualizes the exact traversal path, token meter, and step-by-step replay in real-time via Server-Sent Events (SSE).

---

## 2. Resume Bullet Points

### Single-Bullet Summary (General Software Engineering / AI)
> *"Architected **TreeMem**, an open-source MCP memory server implementing hierarchical parent-first topic descent for LLM agents; cut memory payload tokens by **82.8%** with 100.0% accuracy across 12-question benchmark suites and enforced 8 structural invariants with crash-resilient atomic file operations."*

### 3-Bullet Deep-Dive (AI Infrastructure / Systems Engineering)
> - *"Engineered a hierarchical memory MCP server in Python for autonomous LLM agents, organizing knowledge into rebuildable topic trees with append-only daily logs, and measured memory payload against a flat-dump baseline on a real LLM agent benchmark (results and limitations in the generated table above)."*
> - *"Designed a crash-resilient storage engine utilizing atomic temp-and-rename operations, root-to-leaf hierarchical mutexes, and automated health checks enforcing 8 structural invariants, surviving mid-write `SIGKILL` interruptions with zero data corruption."*
> - *"Built an X-Ray observability dashboard using FastAPI, SSE, and Cytoscape.js that streams real-time traversal paths, token efficiency meters, and interactive time-travel replays under localhost token authentication."*

---

## 3. Verified Benchmark Metrics (Committed in Repo)

<!-- BENCHMARK_TABLE_PORTFOLIO_START -->
| Metric | Measured Value | Benchmark Configuration |
|:---|:---|:---|
| **Answer Accuracy** | flat 100.0% / tree 100.0% | single run, n=12, `qwen/qwen3.8-27b` (`bench/results/llm_eval_results.json`) |
| **Memory Payload Reduction** | 82.45% | same run; payload tokens only |
| **Total API Wire Tokens** | flat 9,858 / tree 66,758 (6.8x) | same run; includes tool schemas re-sent per hop |
| **Parent-Stop Rate** | 8.3% (1/12) | same run |
| **Mean Latency** | flat 0.81s / tree 19.36s | same run |
| **Scaling Payload Savings** | 94.61% - 99.36% | synthetic vault, scripted descent (`bench/results/flat_vs_tree_tokens.json`) |
| **Descent Plumbing Latency** | p50 = 2.29 ms, p95 = 2.87 ms | in-memory traversal only (`bench/results/smoke_test_results.json`) |
| **Rate-Limit Failover** | 0 calls across 0 keys | Groq key rotation in the eval harness |
| **Test Suite** | 137 passing | `pytest tests` (concurrency, property, crash recovery, privacy) |
<!-- BENCHMARK_TABLE_PORTFOLIO_END -->

---

## 4. Key Architectural Highlights & Interview Talking Points

### 1. The "Library Catalog" Model
- **Analogy:** A library catalog card is the root parent, the floor section is a child, and the book is a leaf fact. The agent only traverses as deep as the question requires.
- **Why it beats Vector RAG:** Cosine similarity over chunked text loses topical structure, provides no deterministic drill-down control, and cannot guarantee privacy masks across hierarchical levels.

### 2. Option A: Zero-Host LLM Summarization
- TreeMem never hosts an LLM model or requires OpenAI/Anthropic API keys.
- The server generates strict compression prompts and validation rules (150-token cap, exact child list matching, zero privacy leakage). The agent writes the summary, and the server validates and commits atomically.

### 3. Concurrency & Deadlock Prevention
- Tree operations that mutate parent and child directories lock directories strictly in **root-to-leaf alphabetical order**, mathematically eliminating cyclic lock dependency deadlocks across concurrent sub-agents.
- Verified under multi-threaded stress tests with 8 concurrent workers.

### 4. Privacy & Leakage Guardrails
- Subtopics tagged `sensitivity: private` are masked in parent summaries as `"contains private details, expand to view"`.
- Summaries submitted by agents are checked against descendant token sets and substrings; any leak causes an atomic rollback and rejection.

### 5. Append-Only Ground Truth
- The physical directory tree is a derived cache. All facts are permanently logged in `log/YYYY-MM-DD.md`.
- Wiping the entire tree directory and running `treemem rebuild` restores all nodes and facts.
