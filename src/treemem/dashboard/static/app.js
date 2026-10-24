// TreeMem Dashboard Client Application
(function () {
  const urlParams = new URLSearchParams(window.location.search);
  const token = urlParams.get("t") || localStorage.getItem("treemem_token") || "";
  if (urlParams.get("t")) {
    localStorage.setItem("treemem_token", urlParams.get("t"));
  }

  // App State
  const state = {
    token: token,
    live: true,
    layout: "tree", // "tree" | "radial"
    view: "canvas", // "canvas" | "list"
    selectedPath: "",
    selectedRecallIndex: -1,
    recalls: [],
    events: [],
    metrics: null,
    replayActive: false,
    replayTimer: null,
    replayStep: 0,
    replaySpeed: 1.0,
  };

  // Helper fetch with token
  async function apiFetch(endpoint, options = {}) {
    const url = new URL(endpoint, window.location.origin);
    if (state.token) {
      url.searchParams.set("t", state.token);
    }
    const headers = options.headers || {};
    if (state.token) {
      headers["Authorization"] = `Bearer ${state.token}`;
    }
    const res = await fetch(url.toString(), { ...options, headers });
    if (res.status === 401) {
      document.body.innerHTML = `
        <div style="padding: 40px; font-family: sans-serif; text-align: center;">
          <h2>401 Unauthorized</h2>
          <p>Invalid or missing token. Check your terminal output where TreeMem was started for the dashboard URL with <code>?t=&lt;token&gt;</code>.</p>
        </div>
      `;
      throw new Error("Unauthorized");
    }
    return res.json();
  }

  // Cytoscape initialization
  let cy = null;

  function initCytoscape() {
    cy = cytoscape({
      container: document.getElementById("cy"),
      style: [
        {
          selector: "node",
          style: {
            "label": "data(label)",
            "text-valign": "center",
            "text-halign": "center",
            "color": "#ffffff",
            "font-size": "11px",
            "font-family": "-apple-system, sans-serif",
            "background-color": "#475569",
            "width": "mapData(tokens, 0, 150, 28, 56)",
            "height": "mapData(tokens, 0, 150, 28, 56)",
            "border-width": 1.5,
            "border-color": "#334155",
            "text-outline-width": 1.5,
            "text-outline-color": "#334155",
          },
        },
        {
          selector: "node[dirty]",
          style: {
            "border-style": "dashed",
            "border-color": "#f59e0b",
            "border-width": 2.5,
          },
        },
        {
          selector: "node[sensitivity = 'private']",
          style: {
            "border-color": "#a855f7",
            "border-width": 2.5,
          },
        },
        {
          selector: "node.read",
          style: {
            "background-color": "#0d9488",
            "border-color": "#115e59",
            "text-outline-color": "#115e59",
            "border-width": 3,
          },
        },
        {
          selector: "node:selected",
          style: {
            "border-color": "#38bdf8",
            "border-width": 4,
          },
        },
        {
          selector: "edge",
          style: {
            "width": 1.5,
            "line-color": "#94a3b8",
            "curve-style": "bezier",
            "target-arrow-shape": "triangle",
            "target-arrow-color": "#94a3b8",
            "arrow-scale": 0.8,
          },
        },
        {
          selector: "edge[type = 'wikilink']",
          style: {
            "line-style": "dashed",
            "line-color": "#cbd5e1",
            "target-arrow-shape": "none",
            "width": 1,
          },
        },
        {
          selector: "edge.traversed",
          style: {
            "line-color": "#0d9488",
            "target-arrow-color": "#0d9488",
            "width": 3.5,
          },
        },
      ],
      layout: {
        name: "breadthfirst",
        directed: true,
        padding: 40,
        spacingFactor: 1.25,
      },
      wheelSensitivity: 0.25,
    });

    cy.on("tap", "node", function (evt) {
      const node = evt.target;
      const path = node.data("path") || (node.id() === "root" ? "/" : node.id());
      inspectNode(path);
    });
  }

  // Layout runner
  function applyLayout() {
    if (!cy) return;
    if (state.layout === "tree") {
      cy.layout({
        name: "breadthfirst",
        directed: true,
        padding: 50,
        roots: cy.nodes("[id = 'root']"),
        spacingFactor: 1.3,
      }).run();
    } else {
      cy.layout({
        name: "concentric",
        padding: 50,
        minNodeSpacing: 50,
        concentric: function (node) {
          return 10 - (node.data("depth") || 0);
        },
        levelWidth: function () { return 1; },
      }).run();
    }
  }

  // Load Tree Data
  async function loadTree() {
    try {
      const data = await apiFetch("/api/tree");
      if (!cy) initCytoscape();

      const cyElements = [];
      data.nodes.forEach((n) => {
        cyElements.push({
          group: "nodes",
          data: {
            id: n.id,
            path: n.path,
            label: n.label,
            tokens: n.tokens || 10,
            dirty: n.dirty,
            sensitivity: n.sensitivity,
            depth: n.depth,
          },
        });
      });

      data.edges.forEach((e) => {
        cyElements.push({
          group: "edges",
          data: {
            id: e.id,
            source: e.source,
            target: e.target,
            type: e.type,
          },
        });
      });

      cy.elements().remove();
      cy.add(cyElements);
      applyLayout();

      // Render accessible list view
      renderListView(data.nodes);
    } catch (e) {
      console.error("Failed to load tree:", e);
    }
  }

  // Render Accessible List View
  function renderListView(nodes) {
    const container = document.getElementById("list-view");
    if (!container) return;
    container.innerHTML = `
      <h3 style="margin-bottom: 12px;">Memory Tree Hierarchy (Accessible View)</h3>
      <ul style="list-style-type: none; line-height: 1.8;">
        ${nodes.map((n) => `
          <li style="margin-left: ${(n.depth || 0) * 20}px;">
            <button class="btn" style="text-align: left; margin: 2px 0;" onclick="window.inspectNode('${n.path}')">
              📁 <strong>${n.label}</strong> (${n.tokens} tok) ${n.dirty ? '⚠️ [stale]' : ''} ${n.sensitivity === 'private' ? '🔒 [private]' : ''}
            </button>
          </li>
        `).join("")}
      </ul>
    `;
  }

  // Inspector
  async function inspectNode(path) {
    state.selectedPath = path;
    try {
      const node = await apiFetch(`/api/node?path=${encodeURIComponent(path)}`);
      document.getElementById("insp-path").textContent = node.path;
      document.getElementById("insp-summary").textContent = node.summary || "(No summary written)";
      document.getElementById("insp-tokens").textContent = node.tokens;
      document.getElementById("insp-dirty").textContent = node.dirty ? "true (stale)" : "false (clean)";
      document.getElementById("insp-dirty").style.color = node.dirty ? "var(--color-dirty)" : "inherit";
      document.getElementById("insp-sensitivity").textContent = node.sensitivity;
      document.getElementById("insp-aliases").textContent = (node.aliases && node.aliases.length) ? node.aliases.join(", ") : "none";
      document.getElementById("insp-updated").textContent = node.updated ? node.updated.slice(0, 19).replace("T", " ") : "-";
      document.getElementById("insp-facts").textContent = node.fact_count || 0;

      // Inspector action buttons
      const compressBtn = document.getElementById("insp-btn-compress");
      const editBtn = document.getElementById("insp-btn-edit");
      if (compressBtn) {
        compressBtn.style.display = node.dirty ? "inline-flex" : "none";
        compressBtn.onclick = () => handleAutoCompress(node.path);
      }
      if (editBtn) {
        editBtn.onclick = () => openEditModal(node.path, node.summary || "");
      }

      const childrenList = document.getElementById("insp-children");
      childrenList.innerHTML = "";
      if (node.children && node.children.length > 0) {
        node.children.forEach((c) => {
          const li = document.createElement("li");
          li.className = "children-item";
          const subPath = path === "/" ? c.label : `${path}/${c.label}`;
          li.innerHTML = `
            <div class="children-item-link" onclick="window.inspectNode('${subPath}')">[[${c.label}]]</div>
            <div class="children-item-teaser">${c.teaser || ""}</div>
          `;
          childrenList.appendChild(li);
        });
      } else {
        childrenList.innerHTML = `<li class="children-item-teaser">No children (leaf node).</li>`;
      }
    } catch (e) {
      console.error("Failed to inspect node:", e);
    }
  }
  window.inspectNode = inspectNode;

  // Auto-Compress handler
  async function handleAutoCompress(path) {
    const btn = document.getElementById("insp-btn-compress");
    const statusEl = document.getElementById("insp-action-status");
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Compressing…";
    }
    if (statusEl) statusEl.textContent = "";

    try {
      const res = await apiFetch("/api/node/compress", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
      if (res.ok) {
        if (statusEl) {
          statusEl.textContent = "✅ Compressed successfully.";
          statusEl.style.color = "var(--color-success, #10b981)";
        }
        await loadTree();
        await loadHealth();
        await inspectNode(path);
      } else {
        if (statusEl) {
          statusEl.textContent = `❌ Error: ${res.detail || "Compression failed."}`;
          statusEl.style.color = "var(--color-dirty, #f59e0b)";
        }
      }
    } catch (e) {
      if (statusEl) {
        statusEl.textContent = `❌ ${e.message}`;
        statusEl.style.color = "var(--color-dirty, #f59e0b)";
      }
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = "⚡ Auto-Compress";
      }
    }
  }

  // Open Edit Summary Modal
  function openEditModal(path, currentSummary) {
    const modal = document.getElementById("edit-modal");
    const textarea = document.getElementById("edit-modal-textarea");
    const pathLabel = document.getElementById("edit-modal-path");
    const errEl = document.getElementById("edit-modal-error");
    if (!modal || !textarea) return;

    if (pathLabel) pathLabel.textContent = path;
    textarea.value = currentSummary;
    if (errEl) errEl.textContent = "";
    modal.classList.add("open");

    document.getElementById("edit-modal-submit").onclick = async () => {
      await handleEditSummary(path, textarea.value);
    };
  }

  // Edit Summary POST handler
  async function handleEditSummary(path, text) {
    const errEl = document.getElementById("edit-modal-error");
    const submitBtn = document.getElementById("edit-modal-submit");
    if (errEl) errEl.textContent = "";
    if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = "Saving…"; }

    try {
      const res = await apiFetch("/api/node/summary", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, text }),
      });
      if (res.ok) {
        document.getElementById("edit-modal").classList.remove("open");
        await loadTree();
        await loadHealth();
        await inspectNode(path);
      } else {
        if (errEl) {
          errEl.textContent = res.detail || "Save failed. Check summary length.";
          errEl.style.color = "var(--color-dirty, #f59e0b)";
        }
      }
    } catch (e) {
      if (errEl) {
        errEl.textContent = e.message;
        errEl.style.color = "var(--color-dirty, #f59e0b)";
      }
    } finally {
      if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = "Save"; }
    }
  }

  // Load Recalls and Events
  async function loadEvents() {
    try {
      const data = await apiFetch("/api/events?limit=200");
      state.events = data.events || [];

      // Extract recall chains
      const recallEvents = state.events.filter((e) => e.type === "recall");
      state.recalls = recallEvents.reverse(); // newest first
      renderRecallList();
    } catch (e) {
      console.error("Failed to load events:", e);
    }
  }

  // Render Recall History List
  function renderRecallList() {
    const listEl = document.getElementById("recall-list");
    const filter = document.getElementById("recall-filter").value;
    listEl.innerHTML = "";

    const filtered = state.recalls.filter((r) => {
      if (filter === "parent-stop") return r.depth === 0;
      if (filter === "dirty") return r.dirty;
      return true;
    });

    if (filtered.length === 0) {
      listEl.innerHTML = `<div style="padding: 16px; color: var(--text-muted); text-align: center;">No recall events recorded yet.</div>`;
      return;
    }

    filtered.forEach((r, idx) => {
      const item = document.createElement("div");
      item.className = `recall-item ${idx === state.selectedRecallIndex ? "active" : ""}`;
      const isParentStop = (r.depth === 0);
      const timeStr = r.ts ? r.ts.slice(11, 19) : "";

      item.innerHTML = `
        <div class="recall-item-top">
          <span class="recall-time">${timeStr}</span>
          <span class="recall-tag ${isParentStop ? 'parent-stop' : ''}">${isParentStop ? 'parent-stop' : `depth ${r.depth}`}</span>
        </div>
        <div class="recall-path">${r.path}</div>
        <div class="recall-meta">
          <span>${r.tokens} tokens</span>
          ${r.dirty ? '<span style="color: var(--color-dirty)">• hit dirty</span>' : ''}
        </div>
      `;

      item.addEventListener("click", () => {
        state.selectedRecallIndex = idx;
        renderRecallList();
        highlightRecall(r);
      });

      listEl.appendChild(item);
    });
  }

  // Highlight Recall Path on Canvas
  function highlightRecall(recall) {
    if (!cy) return;

    // Reset styles
    cy.nodes().removeClass("read");
    cy.edges().removeClass("traversed");

    const path = recall.path === "/" ? "root" : recall.path;
    const parts = path === "root" ? ["root"] : path.split("/");

    const traversedNodeIds = [];
    let curr = "";
    parts.forEach((p, i) => {
      if (p === "root") {
        curr = "root";
      } else {
        curr = curr === "root" || !curr ? p : `${curr}/${p}`;
      }
      traversedNodeIds.push(curr);
    });

    // Mark nodes
    traversedNodeIds.forEach((id) => {
      const node = cy.getElementById(id);
      if (node && node.length) {
        node.addClass("read");
      }
    });

    // Mark edges between sequential steps
    for (let i = 0; i < traversedNodeIds.length - 1; i++) {
      const src = traversedNodeIds[i];
      const tgt = traversedNodeIds[i + 1];
      const edge = cy.edges(`[source = '${src}'][target = '${tgt}']`);
      if (edge && edge.length) {
        edge.addClass("traversed");
      }
    }

    // Update Token Meter
    updateTokenMeter(recall.tokens);

    // Announce for accessibility
    const announcer = document.getElementById("live-announcer");
    if (announcer) {
      announcer.textContent = `Recall: path ${recall.path}, ${recall.tokens} tokens, depth ${recall.depth}.`;
    }

    inspectNode(recall.path);
  }

  // Update Token Meter
  async function updateTokenMeter(tokensRead) {
    try {
      const metrics = await apiFetch("/api/metrics");
      state.metrics = metrics;
      const baseline = metrics.baseline_flat_dump_tokens || 100;
      document.getElementById("meter-tokens").textContent = tokensRead || 0;
      document.getElementById("meter-baseline").textContent = baseline;

      const pct = Math.min(100, Math.round(((tokensRead || 0) / baseline) * 100));
      document.getElementById("meter-bar-fill").style.width = `${pct}%`;
    } catch (e) {
      console.error("Failed to update token meter:", e);
    }
  }

  // Health check
  async function loadHealth() {
    try {
      const health = await apiFetch("/api/health");
      const dot = document.getElementById("health-dot");
      const text = document.getElementById("health-text");

      dot.className = "health-dot";
      if (!health.ok) {
        dot.classList.add("health-red");
        text.textContent = `Health: ${health.violations.length} violations`;
      } else if (health.dirty_count > 0) {
        dot.classList.add("health-amber");
        text.textContent = `Health: ${health.dirty_count} stale`;
      } else {
        dot.classList.add("health-green");
        text.textContent = "Health: OK";
      }

      // Populate modal
      document.getElementById("health-modal-summary").textContent =
        `Total nodes: ${health.total_nodes} | Total facts: ${health.total_facts} | Dirty nodes: ${health.dirty_count}`;
      const vList = document.getElementById("health-violations");
      if (health.violations && health.violations.length > 0) {
        vList.innerHTML = health.violations
          .map((v) => `<div class="violation-row"><strong>[Invariant ${v.invariant}]</strong> ${v.path}: ${v.message}</div>`)
          .join("");
      } else {
        vList.innerHTML = `<div style="color: var(--color-success); padding: 8px;">All invariants satisfied. System healthy.</div>`;
      }
    } catch (e) {
      console.error("Failed to load health:", e);
    }
  }

  // Live SSE stream connection
  function connectSSE() {
    const streamUrl = `/api/stream?t=${encodeURIComponent(state.token)}`;
    const eventSource = new EventSource(streamUrl);

    eventSource.addEventListener("treemem_event", (e) => {
      try {
        const payload = JSON.parse(e.data);
        state.events.push(payload);

        if (payload.type === "recall") {
          state.recalls.unshift(payload);
          renderRecallList();
          if (state.live) {
            highlightRecall(payload);
          }
        } else if (payload.type === "write" || payload.type === "summary") {
          loadTree();
          loadHealth();
        }
      } catch (err) {
        console.error("Error processing SSE message:", err);
      }
    });

    eventSource.onerror = () => {
      // Reconnect after brief pause
      eventSource.close();
      setTimeout(connectSSE, 3000);
    };
  }

  // Replay Controller
  function stepReplay(stepIndex) {
    if (!state.recalls.length) return;
    const clamped = Math.max(0, Math.min(stepIndex, state.recalls.length - 1));
    state.replayStep = clamped;
    const recall = state.recalls[state.recalls.length - 1 - clamped]; // chronological order
    if (recall) {
      highlightRecall(recall);
      document.getElementById("replay-status").textContent = `Step ${clamped + 1}/${state.recalls.length}: ${recall.path}`;
    }
  }

  function playReplay() {
    if (state.replayTimer) {
      clearInterval(state.replayTimer);
      state.replayTimer = null;
      document.getElementById("btn-play-pause").textContent = "▶";
      return;
    }

    document.getElementById("btn-play-pause").textContent = "⏸";
    const speed = parseFloat(document.getElementById("replay-speed").value) || 1.0;
    const interval = Math.max(300, 1500 / speed);

    state.replayTimer = setInterval(() => {
      if (state.replayStep >= state.recalls.length - 1) {
        clearInterval(state.replayTimer);
        state.replayTimer = null;
        document.getElementById("btn-play-pause").textContent = "▶";
      } else {
        stepReplay(state.replayStep + 1);
      }
    }, interval);
  }

  // Event Listeners
  function setupListeners() {
    // Live toggle
    document.getElementById("live-toggle").addEventListener("click", () => {
      state.live = !state.live;
      const el = document.getElementById("live-toggle");
      const txt = document.getElementById("live-text");
      if (state.live) {
        el.className = "badge badge-live";
        txt.textContent = "live";
      } else {
        el.className = "badge badge-live paused";
        txt.textContent = "paused";
      }
    });

    // Filter recall list
    document.getElementById("recall-filter").addEventListener("change", renderRecallList);

    // Fit canvas
    document.getElementById("btn-fit").addEventListener("click", () => {
      if (cy) cy.fit(null, 40);
    });

    // Toggle Layout
    document.getElementById("btn-toggle-layout").addEventListener("click", () => {
      state.layout = state.layout === "tree" ? "radial" : "tree";
      document.getElementById("btn-toggle-layout").textContent = `Layout: ${state.layout === "tree" ? "Tree" : "Radial"}`;
      applyLayout();
    });

    // Toggle List / Canvas View
    document.getElementById("btn-toggle-view").addEventListener("click", () => {
      state.view = state.view === "canvas" ? "list" : "canvas";
      const cyEl = document.getElementById("cy");
      const listEl = document.getElementById("list-view");
      if (state.view === "list") {
        cyEl.style.display = "none";
        listEl.style.display = "block";
        document.getElementById("btn-toggle-view").textContent = "Canvas view";
      } else {
        cyEl.style.display = "block";
        listEl.style.display = "none";
        document.getElementById("btn-toggle-view").textContent = "List view";
        if (cy) cy.resize();
      }
    });

    // Node Search
    const searchInput = document.getElementById("node-search");
    searchInput.addEventListener("input", (e) => {
      const q = e.target.value.toLowerCase().trim();
      if (!cy) return;
      if (!q) {
        cy.nodes().style("opacity", 1);
        return;
      }
      cy.nodes().forEach((n) => {
        const lbl = (n.data("label") || "").toLowerCase();
        const p = (n.data("path") || "").toLowerCase();
        if (lbl.includes(q) || p.includes(q)) {
          n.style("opacity", 1);
        } else {
          n.style("opacity", 0.2);
        }
      });
    });

    // Replay buttons
    document.getElementById("btn-step-first").addEventListener("click", () => stepReplay(0));
    document.getElementById("btn-step-prev").addEventListener("click", () => stepReplay(state.replayStep - 1));
    document.getElementById("btn-play-pause").addEventListener("click", playReplay);
    document.getElementById("btn-step-next").addEventListener("click", () => stepReplay(state.replayStep + 1));
    document.getElementById("btn-step-last").addEventListener("click", () => stepReplay(state.recalls.length - 1));

    // Health modal
    const modal = document.getElementById("health-modal");
    document.getElementById("health-btn").addEventListener("click", () => modal.classList.add("open"));
    document.getElementById("btn-close-modal").addEventListener("click", () => modal.classList.remove("open"));

    // Edit Summary modal
    const editModal = document.getElementById("edit-modal");
    const btnCloseEdit = document.getElementById("btn-close-edit-modal");
    if (btnCloseEdit && editModal) {
      btnCloseEdit.addEventListener("click", () => editModal.classList.remove("open"));
    }

    // Keyboard Shortcuts
    window.addEventListener("keydown", (e) => {
      if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT" || e.target.tagName === "TEXTAREA") {
        if (e.key === "Escape") e.target.blur();
        return;
      }
      if (e.key === "/") {
        e.preventDefault();
        searchInput.focus();
      } else if (e.key === "f" || e.key === "F") {
        if (cy) cy.fit(null, 40);
      } else if (e.key === "Escape") {
        modal.classList.remove("open");
        if (editModal) editModal.classList.remove("open");
        if (cy) cy.elements().unselect();
      } else if (e.code === "Space") {
        e.preventDefault();
        playReplay();
      } else if (e.key === "ArrowLeft") {
        stepReplay(state.replayStep - 1);
      } else if (e.key === "ArrowRight") {
        stepReplay(state.replayStep + 1);
      }
    });
  }

  // Initialization
  async function init() {
    setupListeners();
    await loadTree();
    await loadEvents();
    await loadHealth();
    connectSSE();
  }

  window.addEventListener("DOMContentLoaded", init);
})();
