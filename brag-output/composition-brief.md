# Hyperframes Composition Brief: TreeMem

## Objective
Create a short launch-style brag video for TreeMem.

## Output
- Composition directory: `brag-output/composition/`
- Rendered video: `brag-output/brag.mp4`
- Format: landscape — 1920x1080 @ 30fps
- Duration: 23s

## Source Material
- Project root: `/Users/bipinkumarrai/Desktop/EVERYTHING/CODING PROJECTS/ONGoing-PROJ/treeMem`
- Primary files read: `README.md`, `pyproject.toml`, `src/treemem/dashboard/static/{index.html,styles.css,app.js}`, `src/treemem/cli.py`, `examples/sample_memory/**`
- Product name: TreeMem
- Tagline / strongest claim: "Hierarchical, agent-writable memory for LLM agents" — 99.36% token reduction at 10,000 memories; live X-Ray dashboard
- Key UI or visual moment to recreate: the dashboard's Cytoscape graph — slate nodes, teal glowing recall path, dark `#090d16` chrome, token comparison meter, recall history list, inspector panel, health badge
- Copy that must appear verbatim:
  - "Hierarchical memory for LLM agents"
  - "MCP server" / "Markdown vault" / "X-Ray dashboard"
  - "99.36%" fewer tokens at 10,000 memories
  - "82.45%" memory-payload reduction (real LLM eval)
  - "378" tests passing
  - "Memory, organized like a library."
  - `treemem serve --demo`
  - "parent-stop"

## Creative Direction
- Tone preset: `polished`
- Creative direction: quiet technical product film for agents that finally remember
- Interpretation: fewer scenes, longer holds, restraint; one idea per scene; confident slow reveals; no hype, no ALL-CAPS shouting.
- Angle: agents can't afford to re-read their whole memory — TreeMem stores it as a Markdown tree and lets the agent descend only as far as needed, with a live dashboard that x-rays every recall.
- Hook: a wall of ledger lines = the flat dump, counter slamming to 227,941 tokens for 10,000 memories.
- Outro / punchline: TreeMem logo + "Memory, organized like a library." + `treemem serve --demo`.
- Avoid:
  - Generic SaaS language ("streamline", "supercharge")
  - Abstract filler visuals unrelated to the tree/dashboard
  - Invented metrics — every number on screen must come from README/benchmarks
  - Light-mode dashboard colors — the dashboard dark theme is the identity

## Visual Identity
- Background: `#090d16`
- Text: `#f1f5f9` primary, `#94a3b8` secondary, `#64748b` muted
- Accent: teal `#14b8a6` / read-path `#0d9488`, highlight `#2dd4bf`
- Panels: `#131d33`, borders `#1e293b`, node slate `#475569`, edge `#94a3b8`
- Dirty amber `#f59e0b`, private purple `#a855f7` (use sparingly, e.g. one private node)
- Display font: Inter or system-ui stack, heavy weights
- Body font: same stack, regular; monospace (`ui-monospace`/Menlo) for ledger lines, paths, token counts, CLI chip
- Visual references from the project: dashboard header (brand + live badge + token meter), Cytoscape tree graph, recall-history list with "parent-stop" tag, inspector panel, health dot, the tree SVG logo from `index.html`

## Storyboard
Use `brag-output/brag-plan.md` as the creative contract.

Scene summary:
1. The flat dump — 3.5s — ledger wall + counter to 227,941 tokens ("10,000 memories, flat dump")
2. Reveal — 3.5s — tree logo draws, "TreeMem" + "Hierarchical memory for LLM agents" + MCP/Markdown/X-Ray badges + small tree grows
3. The X-Ray descent — 8s — recreated dashboard; query "What's my age?"; teal recall path ignites `/` → `identity` → `age`; parent-stop flash on `/`; token meter counts down; health green
4. The numbers — 5s — three stat blocks: 99.36% / 82.45% / 378 tests, each holds to be read
5. Outro — 3s — logo + "Memory, organized like a library." + `treemem serve --demo` chip; fade on final cue

## Audio
- Audio role: warm clean bed + sparse professional accents
- Audio arc: bed enters under the token wall, lifts through the dashboard descent, accents the stats, resolves under the logo
- Music: `assets/music/happy-beats-business-moves-vol-12-by-ende-dot-app.mp3` (copied into composition)
- Music treatment: ~0.30 volume, gentle fade under final logo, fade-out last ~1.5s
- Music cue guidance: preset at `.agents/skills/brag/assets/music/cues/happy-beats-business-moves-vol-12-by-ende-dot-app.music-cues.json` — strong cues 8.74s, 13.11s, 17.47s, 18.56s, 22.93s; beats grid ~0.55s spacing. Lock dashboard descent ignition near 8.74s, stats payoff near 17.5–18.6s, final hold/fade near 22.9s.
- Audio-reactive treatment: subtle — teal path glow / dashboard presence breathe with music RMS; no waveform/equalizer visuals.
- Audio-coupled moments:
  - Scene 1 — token counter ticks; final number soft thud
  - Scene 2 — tree nodes soft drops; wordmark one medium impact
  - Scene 3 — path nodes ignite with soft ticks (beat/grid aligned); token meter ticks down
  - Scene 4 — three stats arrive on beats, hold together
  - Scene 5 — logo lands on strong cue; soft bell; music fades
- SFX selection guidance: see `.agents/skills/brag/assets/sfx/sfx-analysis.md`; prefer low/medium HF-risk files; polished = sparse.
- Exact SFX choice: Hyperframes chooses filenames/timestamps/density after animation exists.
- Audio files: music copied to `composition/assets/music/`; SFX to be copied under `composition/assets/sfx/` by Hyperframes as selected.

## Hyperframes Instructions
Load the composition-building Hyperframes skills — `hyperframes` (contract, `references/format.md`, `references/motion.md`, `references/look.md`), `hyperframes-registry`, `media-use`, `hyperframes-cli`. /brag is its own workflow: skip the storyline step (`references/types/*`, `references/story.md`, no `SPEC.md`); skip usage/history/feedback/REVIEW.md; `check` is the single gate.

Requirements:
- Show at least one real UI element from the project (the X-ray dashboard recreation in Scene 3).
- Keep all text readable in the final render.
- Keep the video at 23s (within 15-25s).
- Include the planned music/SFX layer.
- Treat audio notes as guidance, not a fixed cue sheet.
- Major reveals may move toward strong cues within ±0.15s; small entrances within ±0.10s of beats; use 1-3 strong cue locks.
- Use SFX to support motion; restraint for polished tone.
- Consider audio-reactive visuals (subtle RMS glow on teal elements).
- Use local assets for audio.
- Run `hyperframes check` before render — fix every error including WCAG contrast.
- Keep creation and rendering local.
