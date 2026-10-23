# Harness Integration Notes (Phase 0)

## 1. Antigravity MCP Support
- **Transport**: Stdio transport via MCP configuration in plugin manifests (`mcp_config.json`) or direct configuration.
- **Execution Model**: Antigravity launches the configured command (e.g. `treemem serve --mcp` or `python -m treemem.mcp_layer`) with bidirectional stdin/stdout JSON-RPC communication.
- **Plugin Packaging**: Supported via `~/.gemini/config/plugins/<name>/` with `plugin.json` and `mcp_config.json`.
- **Fallback**: Instruction-file fallback mode using `AGENTS.md` block where an agent directly navigates the markdown folders using shell commands (`ls`, `cat`) if MCP is unavailable.

## 2. Devin & Other Agent Harnesses
- **Transport**: Stdio or local HTTP SSE transport.
- **Configuration**: Typically configured in harness workspace settings (e.g. `.devin.json` or MCP settings dialog).
- **Environment**: Single-process server binding to stdio or local port (`127.0.0.1`).
- **Instruction-file fallback**: Devin's shell execution capability can also parse and navigate the plain markdown vault.
