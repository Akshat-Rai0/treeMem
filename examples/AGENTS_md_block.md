# TreeMem Instruction-File Fallback (AGENTS.md block)

If the TreeMem MCP server is unavailable, you can interact with the TreeMem vault directly using standard shell commands (`ls`, `cat`) by following these rules:

## 1. Vault Location
The memory vault is located at `memory/`.

## 2. Reading Memory (Hierarchical Descent)
1. Read the root summary first:
   ```bash
   cat memory/summary.md
   ```
2. Check if the parent summary or child teasers under `## Children` answer your question. If so, **STOP** (parent-stop).
3. If more detail is required, inspect the relevant subtopic:
   ```bash
   cat memory/<topic>/summary.md
   ```
4. If the subtopic points to a leaf fact, read the leaf file:
   ```bash
   cat memory/<topic>/<subtopic>/summary.md
   ```
5. If the information cannot be found via hierarchical descent, fall back to searching:
   ```bash
   grep -rn "keyword" memory/log/ memory/*/summary.md
   ```

## 3. Writing Memory
1. Append raw facts to today's daily log file (`memory/log/YYYY-MM-DD.md`):
   ```bash
   echo "- <next_line> | $(date -u +%H:%M:%SZ) | session=agent | fact: <your fact> | hint: <topic/subtopic>" >> memory/log/$(date -u +%Y-%m-%d).md
   ```
2. Append the fact to the corresponding leaf node:
   ```bash
   echo "- <your fact> (log: $(date -u +%Y-%m-%d)#<line>)" >> memory/<topic>/<subtopic>/summary.md
   ```
3. Update the YAML frontmatter of the leaf node and all parent directories to set `dirty: true`.
