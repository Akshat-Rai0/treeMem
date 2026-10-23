# UI spec: memory x-ray dashboard

Local web page served by the memory server. Read-only in v1. Purpose: show exactly what an agent read to answer, live, and let a viewer replay it.

## 1. Principles

- Show the path, not just the tree: the highlighted recall path is the hero.
- Calm by default: collapsed tree, only the active path and its neighbors expanded.
- Everything on screen is derived from `/api/*` (see system-wiring). No hidden state.
- Memory text is untrusted: render as plain text, never as HTML.

## 2. Layout (desktop)

```
+----------------------------------------------------------------------+
| TreeMem   [live ●]   session: abc   search nodes...      token meter |
+----------------------+-----------------------------------+-----------+
| Recall list          |            GRAPH CANVAS           | Inspector |
| (newest first)       |                                   |           |
|  q-14 10:12 age?     |      (root)                       | node path |
|   depth 2  74 tok    |      /  |  \                      | summary   |
|  q-13 10:09 name     |   ident college projects          | children  |
|   depth 0  40 tok    |    |                              | meta      |
|  ...                 |   age  location                   | history   |
+----------------------+-----------------------------------+-----------+
| Replay: |<  <  ▶  >  >|    speed 1x    q-14 step 3/3     | health ●  |
+----------------------------------------------------------------------+
```

Width rules: three columns on >= 1100 px; below that, inspector becomes a drawer; below 700 px, recall list becomes a drawer and canvas fills the screen (view-only).

## 3. Views and components

### 3.1 Graph canvas
- Layout: hierarchical tree (top-down) by default; toggle to radial. Cross-links drawn as dashed edges.
- Node encoding:
  - Fill: teal = read in the selected recall; neutral = not read.
  - Border dashed = dirty (stale summary).
  - Lock glyph = sensitivity private.
  - Size = token count of the node summary (clamped min/max).
  - Label = node name; tooltip = teaser.
- Edge encoding: thick teal = traversed in selected recall; thin grey = hierarchy; dashed = wikilink.
- Collapsing: nodes deeper than depth 2 from the selected path start collapsed, shown as a "+N" badge. Click to expand.
- Zoom/pan with mouse and keyboard; "fit to path" button.
- Scale target: smooth at 1,000 visible nodes; beyond that, force collapse and show a notice.

### 3.2 Recall list (left)
- One row per query chain: time, first line of query label (if provided), depth reached, total tokens, stop marker (parent-stop or deepest node).
- Click selects the chain and highlights it on the canvas.
- Filter: all / parent-stops only / hit dirty nodes.

### 3.3 Inspector (right)
- For the selected node: path, summary text (plain), metadata (dirty, updated, tokens, sensitivity, aliases), children with teasers, backlinks (v1.5), recent events touching this node.
- Private nodes: show teaser and "private details" only; never show bodies.

### 3.4 Token meter (top right)
- Shows tokens read in the selected chain vs a flat-dump baseline (all leaf text concatenated), as a number and a small bar. Baseline calc is documented in the tooltip.

### 3.5 Replay bar (bottom)
- Step through a chain: each step lights the node read at that step. Controls: first, prev, play/pause, next, last; speed 0.5x/1x/2x.
- Replay data comes from `/api/events`; works after restart via the events files.

### 3.6 Health indicator
- Dot: green (no violations, no dirty), amber (dirty nodes exist), red (invariant violations). Click opens a panel listing paths and the violation text.

### 3.7 Live mode
- SSE stream. New recalls animate onto the canvas (path draws in over ~400 ms). `live ●` toggle pauses auto-follow without dropping events.

## 4. Interactions

| Action | Result |
|---|---|
| Click node | Select; inspector shows it |
| Double-click node | Expand/collapse its children |
| Click recall row | Highlight that chain's path |
| Space | Play/pause replay |
| Left/Right | Replay prev/next step |
| `/` | Focus node search |
| `f` | Fit to selected path |
| Esc | Clear selection |

## 5. States

| State | Behavior |
|---|---|
| Empty memory | Illustration-free message: "No nodes yet. Connect an agent and call remember." Shows the config snippet |
| Loading | Skeleton rows; canvas shows "loading tree" |
| Server unreachable | Banner with retry; last known graph stays, greyed |
| Invalid/expired token | Full-page message explaining how to get the current URL from the terminal |
| Very large tree | Notice that deep branches are collapsed; search still finds any node |
| Health red | Banner above canvas with count; canvas still usable |

## 6. Visual design

- Flat surfaces, no gradients or shadows, thin 0.5-1 px strokes, one accent (teal) for "read", one neutral ramp. Sentence case labels everywhere.
- Light and dark mode via CSS variables and `prefers-color-scheme`; every color token has both values; text on fills uses the darker stop from the same ramp.
- Typography: system sans, two weights (400, 500), two sizes in the canvas (14 px labels, 12 px secondary).
- Never rely on color alone: dashed vs solid borders and the lock glyph carry meaning too.

## 7. Accessibility

- Canvas is not the only way in: a keyboard-navigable tree list (hidden toggle "list view") mirrors the graph.
- Focus rings visible; all controls reachable by keyboard; ARIA labels on icon buttons.
- Live updates announced politely (`aria-live=polite`) as "recall: path root > identity > age, 74 tokens".
- Respect `prefers-reduced-motion`: no path-draw animation, instant highlight.

## 8. Tech choices

- Single static page (HTML/JS/CSS) served from `dashboard/static/`, no build step in v1.
- Graph library: Cytoscape.js (lean) with a tree layout extension; D3 as alternative if finer animation needed. Loaded from a vendored file, not a CDN, so it works offline.
- No framework required; small vanilla modules: `api.js`, `state.js`, `graph.js`, `inspector.js`, `replay.js`.
- State: one in-memory store; selected chain, selected node, live flag.

## 9. Data contracts used

Reads only: `/api/tree`, `/api/node`, `/api/events`, `/api/stream`, `/api/health`, `/api/metrics` as defined in system-wiring section 5.

## 10. Demo mode (for the GIF and README)

- `treemem serve --demo` loads `examples/sample_memory/` and a scripted event file so the dashboard animates a canned sequence: "what's my name" (parent-stop, depth 0), "what's my age" (depth 2), one stale-parent case with the dirty border and the compress step clearing it.
- Record this sequence as the 60-second README GIF.

## 11. Out of scope for v1 UI

Editing nodes, creating nodes, auth beyond the token, multi-memory switching, mobile-optimized editing, theming controls.

## 12. UI acceptance checklist

- [ ] Highlights the exact path of a recall within 500 ms of the event
- [ ] Private node bodies never appear in DOM or network responses
- [ ] Replay works after server restart
- [ ] Works fully offline (no CDN)
- [ ] Keyboard-only walkthrough of select, expand, replay
- [ ] Light and dark modes both legible
- [ ] 1,000-node tree stays interactive
