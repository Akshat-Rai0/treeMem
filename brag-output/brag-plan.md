# Brag Plan: TreeMem

## What is this app?
TreeMem is hierarchical, agent-writable memory for LLM agents — an MCP server that stores memories as a tree of plain Markdown files and ships a live local "X-Ray" dashboard that visualizes every recall path in real time.

## The angle
Agents forget everything between sessions, so they either dump the whole vault into context (token suicide) or reach for black-box vector RAG. TreeMem turns memory into an actual tree: parents hold summaries, children hold detail, and the agent descends only as far as it needs — often stopping at the root. The video plays this straight: it's a real, measured systems result (99.36% token reduction at 10k memories), not a startup fantasy. The dashboard X-ray is the proof you can watch.

## Hook (first 2-3 seconds)
A dense wall of memory lines — the flat dump — with the counter landing on **227,941 tokens** for 10,000 memories. Line: "Your agent remembers everything. It just can't afford to read it." (hook copy is connective framing; the number is the grounded claim.)

## Key moments (the middle)
- The X-ray dashboard: a tree of topic nodes (identity, career, projects, education, finance…) where a recall path ignites teal as it descends `/` → `projects` → `treemem`, while the token meter counts down toward the tree cost.
- The parent-stop idea: the agent reads the root summary and *stops* — "O(log N) descent" made visible.
- Hard numbers: 99.36% fewer tokens at 10,000 memories; 82.45% memory-payload reduction on a real LLM eval; 378 tests passing.

## Outro / punchline
TreeMem logo + "Memory, organized like a library." + the real demo command `treemem serve --demo`. Quiet confidence, no exclamation.

## User flow worth showing
`remember` a fact → `place` it under a topic → `recall("/")` descends the tree (root summary → child teasers → leaf only if needed) → the dashboard paints the traversed path teal live. Centerpiece scene is this descent inside the recreated X-ray dashboard.

## Tone
- Preset: `polished`
- Creative direction: quiet technical product film for agents that finally remember
- Interpretation: fewer scenes, longer holds, restraint as the creative choice; one feature per scene; slow confident reveals; no hype.

## Format: landscape — 1920x1080
## Duration: 23s

## Visual identity (from the project)
- Background: `#090d16` (dashboard dark theme)
- Panel / surface: `#131d33`, borders `#1e293b`
- Text: `#f1f5f9` primary, `#94a3b8` secondary, `#64748b` muted
- Accent: teal `#14b8a6` (dark-mode accent) / `#0d9488` (read-path nodes), light `#2dd4bf`
- Supporting colors: dirty amber `#f59e0b`, private purple `#a855f7`, node slate `#475569`, edge `#94a3b8`
- Display font: system-ui stack (`-apple-system, "Segoe UI", Roboto…`) — use Inter or system fallback, heavy weights for display
- Body font: same stack, regular
- Strongest visual element: the Cytoscape X-ray graph — slate nodes, teal glowing recall path, dashed amber dirty borders, purple private locks, token comparison meter

## Share copy (draft)
Your agent forgets everything between sessions. TreeMem gives it a memory tree it can actually read — 99.36% fewer tokens at 10,000 memories, visualized live in an X-ray dashboard.

## Audio direction
- Role: warm clean bed with sparse professional accents
- Music: `happy-beats-business-moves-vol-12-by-ende-dot-app.mp3` (steady, clean — the polished pick)
- Music treatment: start at 0, ~0.30 volume, gentle fade under the final logo, full fade-out in last ~1.5s
- Music cue guidance: bundled preset read — strong cues at 8.74s, 13.11s, 17.47s/18.56s, 22.93s. Plan locks: dashboard descent ignition near 8.74s; stats payoff near 17.47–18.56s; final logo/hold lands on 22.93s.
- Audio-reactive treatment: subtle — teal recall-path glow and dashboard presence breathe gently with music RMS; no waveform/equalizer visuals.
- SFX posture: sparse — soft drop for node arrivals, one medium impact for the TreeMem reveal, quiet key ticks optional on the token counter, one bell under the logo.
- Audio-coupled moments: token counter ticks down in Scene 1; recall path ignites node-by-node in Scene 3; stat cards arrive in Scene 4; logo lands in Scene 5.
- Restraint rule: nothing loud or comic; SFX must stay under the music bed's politeness; no sound on every cut.

## Storyboard

### Scene 1 — The flat dump — 3.5s
A dark screen fills with dense lines of memory facts (monospace ledger style, like `log/YYYY-MM-DD.md`), scrolling fast. A token counter on the right ticks up and slams to **227,941 tokens** with the caption "10,000 memories, flat dump". Then the wall dims.
Sequential/interaction: yes — ledger lines cascade in rapidly, counter counts up.
Audio intent: low, slightly tense bed; a rising tick on the counter.
Audio-coupled idea: counter ticks with keyboard-ish soft ticks; final number lands with a soft thud.
Music: vol-12 enters quietly.
Transition mood: clean → Scene 2

### Scene 2 — Reveal — 3.5s
The TreeMem mark (the dashboard's tree SVG logo) draws in, then "TreeMem" wordmark and the grounded line: "Hierarchical memory for LLM agents". Small badge row: "MCP server" · "Markdown vault" · "X-Ray dashboard". A small tree diagram grows one node at a time beside the type.
Sequential/interaction: yes — tree nodes appear one by one.
Audio intent: the bed lifts; first confident accent on the logo.
Audio-coupled idea: node arrivals get soft drop ticks; wordmark gets one medium impact.
Music: vol-12, mid energy.
Transition mood: clean → Scene 3

### Scene 3 — The X-Ray descent — 8s
Recreated dashboard (dark `#090d16` UI): header with TreeMem brand + live badge + token meter; left recall-history list; center Cytoscape-style graph of ~15 nodes (root, identity, career, projects, education, finance, preferences, hobbies, and leaves); right inspector panel. A query chip "What's my age?" → recall path ignites teal node-by-node `/` → `identity` → `age` (parent-stop variant flashes on `/` first). Token meter counts down 227,941 → 1,465-ish scale; "parent-stop" tag appears in the recall list; health dot stays green.
Sequential/interaction: yes — path ignites node by node; inspector fills on arrival.
Audio intent: the centerpiece — bed swells slightly; each node ignition is a soft tick.
Audio-coupled idea: teal path nodes ignite sequentially with drop/click ticks; token meter counts down with subtle ticks; beat-lock the first descent step near the 8.74s strong cue.
Music: vol-12 peak presence.
Transition mood: clean → Scene 4

### Scene 4 — The numbers — 5s
Three proof points land as restrained stat blocks (grounded, verbatim-ish):
1. "99.36%" — fewer tokens at 10,000 memories (synthetic scaling study)
2. "82.45%" — memory-payload reduction on a real LLM eval
3. "378" — tests passing
Each holds long enough to read; a thin teal rule draws under each.
Sequential/interaction: yes — three stats arrive one by one then hold together.
Audio intent: confident, clean; each stat gets one soft accent, last one rings slightly.
Audio-coupled idea: stats snap to nearby beats; hold the full row ~1.5s before transition.
Music: vol-12.
Transition mood: clean → Scene 5

### Scene 5 — Outro — 3s
TreeMem logo centered, "Memory, organized like a library." then a terminal-style chip: `treemem serve --demo`. Hold. Gentle fade to black on the 22.93s strong cue.
Sequential/interaction: none — one calm landing.
Audio intent: resolve; one soft bell under the logo; music fades out.
Audio-coupled idea: logo lands near a strong beat; music tail fades under the hold.
Music: vol-12 fade-out.
Transition mood: — (end)

**Music mood for this video:** steady clean bed (polished)
**Audio summary:** vol-12 enters under the token wall, lifts through the dashboard descent, accents three stats, and resolves under the logo with a soft bell and fade-out.
