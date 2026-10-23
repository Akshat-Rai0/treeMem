# Prior Art & How TreeMem Differs (Phase 0)

## 1. Existing Paradigms

### A. Flat Notes / Direct Append Logs
- **Examples**: Simple `memory.md` scratchpads, chronological daily notes.
- **Drawbacks**: As facts accumulate, the entire file must be read into context, exploding prompt tokens ($O(N)$ token scaling). When truncated, critical context is lost.

### B. Vector Database / Top-K Semantic Search
- **Examples**: Standard RAG setups, Chroma/Qdrant-backed agent memory plugins.
- **Drawbacks**: Misses high-level relational context. Vector distance does not preserve topical hierarchies or allow an agent to control drill-down depth. No transparent audit path for what was read.

### C. Tree-based Summaries (e.g. RAPTOR, OptMem)
- **RAPTOR**: Builds recursive clusters and summaries from text chunks for retrieval, but does so offline and is not designed as an interactive, agent-writable hierarchical memory.
- **OptMem**: Constructs a binary merge tree chronologically over conversational logs, compressing older epochs. However, it does not allow the agent to choose topic descent dynamically per query, nor does it provide a clean inspectable file format.

## 2. How TreeMem Differs

1. **Agent-Controlled Descent**: Recalling the root gives a parent summary and child teasers. The agent chooses when the parent summary is sufficient ("parent-stop") or when to step down into a child branch (`recall`/`expand`).
2. **Transparent, Zero-Lock-In Storage**: The memory vault is a standard Obsidian-compatible folder of human-readable Markdown files with YAML frontmatter.
3. **Append-Only Ground Truth**: `log/YYYY-MM-DD.md` retains every fact ever recorded. The hierarchical tree is a derived, rebuildable cache.
4. **Agent-Written Summaries (Zero Server Model Hosting)**: The server never hosts an LLM. It generates compression prompts, validates the agent's summary against token caps and child lists, and commits atomically.
5. **Staleness Tracking**: Modifications mark descendants and all ancestors `dirty`, preventing silent hallucinations from outdated parent summaries.
6. **Privacy Enforcement**: Private nodes are sanitized from ancestor summaries by automated token overlap and substring validation.
7. **Live X-Ray Dashboard**: Real-time visual verification showing the exact traversal path, token count, and parent-stops of every agent recall.
