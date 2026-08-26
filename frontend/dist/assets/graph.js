/**
 * BIT-Forensics investigation graph — mockup look, real /api/graph data.
 * Colors: IP green, Wallet purple, TX blue, flagged red glow.
 */
const Graph = (() => {
  const COLORS = { ip: "#3d8b6e", wallet: "#7a6a9e", tx: "#4a6fa5" };
  const EDGE_COLORS = {
    src: "#3d8b6e",
    dst: "#3d8b6e",
    input: "#7a6a9e",
    output: "#4a6fa5",
  };

  let state = null;
  let moveHandler = null;
  let upHandler = null;

  function emptyState(canvas) {
    return {
      canvas,
      ctx: canvas.getContext("2d"),
      mini: null,
      miniCtx: null,
      allNodes: [],
      allEdges: [],
      nodes: [],
      edges: [],
      byId: {},
      selectedId: null,
      scale: 1,
      panX: 0,
      panY: 0,
      dragging: null,
      panning: false,
      lastX: 0,
      lastY: 0,
      running: false,
      simulating: false,
      onSelect: null,
      filter: { risk: "all", type: "all", country: "all" },
      dpr: 1,
      cssW: 900,
      cssH: 560,
    };
  }

  function resize(st) {
    const canvas = st.canvas;
    const parent = canvas.parentElement;
    // Measure the stage after it is visible — never paint into a 0×0 tab
    let cssW = 0;
    let cssH = 0;
    if (parent) {
      const pr = parent.getBoundingClientRect();
      cssW = Math.floor(pr.width);
      cssH = Math.floor(pr.height);
      const guide = parent.querySelector(".invest-guide, .invest-note");
      if (guide && !guide.hidden && guide.offsetParent !== null) {
        cssH = Math.max(0, cssH - Math.ceil(guide.getBoundingClientRect().height));
      }
    }
    if (cssW < 40) cssW = Math.max(320, Math.floor(window.innerWidth * 0.55));
    if (cssH < 40) cssH = Math.max(280, Math.floor(window.innerHeight * 0.62));
    st.dpr = window.devicePixelRatio || 1;
    canvas.width = Math.floor(cssW * st.dpr);
    canvas.height = Math.floor(cssH * st.dpr);
    // Explicit px so the bitmap always matches what the user sees
    canvas.style.width = cssW + "px";
    canvas.style.height = cssH + "px";
    st.ctx.setTransform(st.dpr, 0, 0, st.dpr, 0, 0);
    st.cssW = cssW;
    st.cssH = cssH;
  }

  function nodeCountry(n) {
    return (n.country || n.geo_country || "").trim();
  }

  function passesFilter(n, f) {
    if (f.type !== "all" && n.type !== f.type) return false;
    if (f.country !== "all") {
      const c = nodeCountry(n);
      if (!c || c.toLowerCase() !== f.country.toLowerCase()) return false;
    }
    if (f.risk === "flagged" && !n.flagged) return false;
    if (f.risk === "high" && !(n.flagged && /CRITICAL|HIGH/i.test(n.severity || ""))) return false;
    if (f.risk === "normal" && n.flagged) return false;
    return true;
  }

  function applyFilter(st) {
    const keep = {};
    st.nodes = st.allNodes.filter((n) => {
      const ok = passesFilter(n, st.filter);
      if (ok) keep[n.id] = true;
      return ok;
    });
    // Keep neighbors of kept nodes for readable network
    if (st.filter.type !== "all" || st.filter.country !== "all" || st.filter.risk !== "all") {
      const extra = {};
      st.allEdges.forEach((e) => {
        if (keep[e.from] || keep[e.to]) {
          extra[e.from] = true;
          extra[e.to] = true;
        }
      });
      st.nodes = st.allNodes.filter((n) => keep[n.id] || extra[n.id]);
      st.nodes.forEach((n) => { keep[n.id] = true; });
    }
    st.byId = {};
    st.nodes.forEach((n) => { st.byId[n.id] = n; });
    st.edges = st.allEdges.filter((e) => keep[e.from] && keep[e.to]);
  }

  function initPositions(nodes, w, h, edges, focusId) {
    // Layered forensic layout: IP (left) → TX (center) → wallet (right)
    const byId = {};
    nodes.forEach((node) => {
      byId[node.id] = node;
      node.vx = 0;
      node.vy = 0;
      const base = node.type === "wallet" ? 13 : node.type === "tx" ? 14 : 12;
      node.r = node.flagged ? base + 2 : base;
      node.x = null;
      node.y = null;
    });

    const ips = nodes.filter((n) => n.type === "ip");
    const txs = nodes.filter((n) => n.type === "tx");
    const wallets = nodes.filter((n) => n.type === "wallet");
    const other = nodes.filter((n) => !["ip", "tx", "wallet"].includes(n.type));

    function placeCol(arr, x) {
      const n = arr.length;
      if (!n) return;
      const gap = Math.min(78, Math.max(48, (h * 0.78) / Math.max(n, 1)));
      const span = gap * (n - 1);
      const y0 = (h - span) / 2;
      arr.forEach((node, i) => {
        node.x = x;
        node.y = n === 1 ? h / 2 : y0 + i * gap;
      });
    }

    // Sort so flagged / focus sit near vertical center
    function rank(a, b) {
      const af = a.id === focusId ? 2 : a.flagged ? 1 : 0;
      const bf = b.id === focusId ? 2 : b.flagged ? 1 : 0;
      if (bf !== af) return bf - af;
      return (b.risk_score || 0) - (a.risk_score || 0);
    }
    ips.sort(rank);
    txs.sort(rank);
    wallets.sort(rank);

    const left = w * 0.16;
    const mid = w * 0.48;
    const right = w * 0.82;
    placeCol(ips, left);
    placeCol(txs, mid);
    placeCol(wallets, right);
    placeCol(other, mid + 40);

    // Nudge seed toward vertical center
    if (focusId && byId[focusId]) {
      const f = byId[focusId];
      f.y = f.y * 0.35 + (h / 2) * 0.65;
    }
  }

  function stepForces(st) {
    // Light settle only — layered layout already spaces columns; avoid tangle
    const nodes = st.nodes;
    const n = nodes.length;
    if (!n) return;
    const cy = st.cssH / 2;

    for (let i = 0; i < n; i++) {
      const a = nodes[i];
      for (let j = i + 1; j < n; j++) {
        const b = nodes[j];
        // Same-column collision only (keep IP/TX/wallet lanes)
        if (a.type !== b.type) continue;
        let dx = a.x - b.x;
        let dy = a.y - b.y;
        let dist2 = dx * dx + dy * dy;
        if (dist2 < 1) {
          dx = 0.1;
          dy = (i - j) || 0.2;
          dist2 = dx * dx + dy * dy;
        }
        const dist = Math.sqrt(dist2);
        const minDist = a.r + b.r + 36;
        if (dist >= minDist) continue;
        const force = (minDist - dist) * 0.55;
        a.vy += (dy / dist) * force;
        b.vy -= (dy / dist) * force;
      }
    }

    for (let i = 0; i < n; i++) {
      const node = nodes[i];
      if (st.dragging && st.dragging.id === node.id) {
        node.vx = 0;
        node.vy = 0;
        continue;
      }
      // Keep X locked to lane; soft Y toward center band
      node.vx = 0;
      node.vy += (cy - node.y) * 0.008;
      node.vy *= 0.72;
      if (Math.abs(node.vy) > 8) node.vy = node.vy > 0 ? 8 : -8;
      node.y += node.vy;
      const m = 28;
      if (node.y < m) node.y = m;
      if (node.y > st.cssH - m) node.y = st.cssH - m;
    }
  }

  function shortLabel(n) {
    if (n.type === "ip") {
      const c = nodeCountry(n);
      return c && c !== "LOCAL" && c !== "UNK" ? (n.label || "") + " · " + c : (n.label || "");
    }
    if (n.type === "tx") {
      const amt = n.amount_btc != null ? Number(n.amount_btc).toFixed(2) + " BTC" : "";
      return amt || (n.label || "TX").slice(0, 12);
    }
    const a = n.label || "";
    return a.length > 14 ? a.slice(0, 12) + "…" : a;
  }

  function fitView(st, pad) {
    pad = pad == null ? 48 : pad;
    if (!st.nodes.length) {
      st.scale = 1;
      st.panX = 0;
      st.panY = 0;
      return;
    }
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    st.nodes.forEach((n) => {
      if (!Number.isFinite(n.x) || !Number.isFinite(n.y)) return;
      minX = Math.min(minX, n.x - n.r);
      minY = Math.min(minY, n.y - n.r);
      maxX = Math.max(maxX, n.x + n.r);
      maxY = Math.max(maxY, n.y + n.r);
    });
    if (!Number.isFinite(minX) || !Number.isFinite(maxX)) {
      st.scale = 1;
      st.panX = 0;
      st.panY = 0;
      return;
    }
    const bw = Math.max(maxX - minX, 40);
    const bh = Math.max(maxY - minY, 40);
    const sx = (st.cssW - pad * 2) / bw;
    const sy = (st.cssH - pad * 2) / bh;
    let scale = Math.min(sx, sy);
    if (!Number.isFinite(scale) || scale <= 0) scale = 1;
    st.scale = Math.max(0.2, Math.min(1.8, scale));
    st.panX = (st.cssW - (minX + maxX) * st.scale) / 2;
    st.panY = (st.cssH - (minY + maxY) * st.scale) / 2;
  }

  function settleLayout(st, focusId) {
    initPositions(st.nodes, st.cssW, st.cssH, st.edges, focusId || st.selectedId);
    for (let i = 0; i < 36; i++) stepForces(st);
    freezeNodes(st);
    fitView(st, 48);
  }

  function screenToWorld(st, sx, sy) {
    return { x: (sx - st.panX) / st.scale, y: (sy - st.panY) / st.scale };
  }

  function hitTest(st, sx, sy) {
    const p = screenToWorld(st, sx, sy);
    let best = null, bestD = Infinity;
    const pad = 22 / Math.max(st.scale, 0.35);
    for (let i = st.nodes.length - 1; i >= 0; i--) {
      const n = st.nodes[i];
      const d = Math.hypot(p.x - n.x, p.y - n.y);
      if (d <= n.r + pad && d < bestD) {
        best = n;
        bestD = d;
      }
    }
    return best;
  }

  function selectNode(st, node) {
    if (!node) return null;
    st.selectedId = node.id;
    if (st.onSelect) st.onSelect(node);
    paint(st);
    return node;
  }

  function drawIcon(ctx, type, x, y, r) {
    ctx.save();
    ctx.translate(x, y);
    ctx.strokeStyle = "#fff";
    ctx.fillStyle = "#fff";
    ctx.lineWidth = Math.max(1.3, r * 0.11);
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    const s = r * 0.52;
    if (type === "ip") {
      ctx.beginPath();
      ctx.arc(0, 0, s, 0, Math.PI * 2);
      ctx.stroke();
      ctx.beginPath();
      ctx.ellipse(0, 0, s * 0.42, s, 0, 0, Math.PI * 2);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(-s, 0);
      ctx.lineTo(s, 0);
      ctx.moveTo(0, -s);
      ctx.lineTo(0, s);
      ctx.stroke();
    } else if (type === "wallet") {
      const w = s * 1.55, h = s * 1.05;
      ctx.beginPath();
      if (ctx.roundRect) ctx.roundRect(-w / 2, -h / 2, w, h, 2);
      else {
        ctx.rect(-w / 2, -h / 2, w, h);
      }
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(w * 0.08, -h * 0.12);
      ctx.lineTo(w / 2, -h * 0.12);
      ctx.lineTo(w / 2, h * 0.28);
      ctx.lineTo(w * 0.08, h * 0.28);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(w * 0.3, h * 0.08, s * 0.16, 0, Math.PI * 2);
      ctx.fill();
    } else {
      ctx.font = "bold " + Math.max(8, Math.floor(r * 0.7)) + "px sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText("TX", 0, 1);
    }
    ctx.restore();
  }

  function drawEdge(ctx, a, b, rel, thick) {
    const dx = b.x - a.x, dy = b.y - a.y;
    const dist = Math.hypot(dx, dy) || 1;
    const ux = dx / dist, uy = dy / dist;
    const sx = a.x + ux * (a.r + 1);
    const sy = a.y + uy * (a.r + 1);
    const ex = b.x - ux * (b.r + 1);
    const ey = b.y - uy * (b.r + 1);
    const col = EDGE_COLORS[rel] || "#64748b";
    // Soft curve — fewer crossing “hairballs”
    const mx = (sx + ex) / 2;
    const my = (sy + ey) / 2 + (a.y < b.y ? -12 : 12) * (thick ? 0.4 : 0.25);
    ctx.beginPath();
    ctx.moveTo(sx, sy);
    ctx.quadraticCurveTo(mx, my, ex, ey);
    ctx.strokeStyle = col;
    ctx.lineWidth = thick ? 2 : 1;
    ctx.globalAlpha = thick ? 0.85 : 0.28;
    if (rel === "src" || rel === "dst") ctx.setLineDash([4, 4]);
    else ctx.setLineDash([]);
    ctx.stroke();
    ctx.setLineDash([]);
    // Tiny open chevron (no filled “point” blobs)
    if (thick) {
      const ah = 5;
      const tx = ex - ux * ah;
      const ty = ey - uy * ah;
      ctx.beginPath();
      ctx.moveTo(tx - uy * ah * 0.55, ty + ux * ah * 0.55);
      ctx.lineTo(ex, ey);
      ctx.lineTo(tx + uy * ah * 0.55, ty - ux * ah * 0.55);
      ctx.strokeStyle = col;
      ctx.lineWidth = 1.4;
      ctx.globalAlpha = 0.9;
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
  }

  function paintMini(st) {
    if (!st.mini || !st.miniCtx) return;
    const ctx = st.miniCtx;
    const w = st.mini.width;
    const h = st.mini.height;
    ctx.fillStyle = "#0f1419";
    ctx.fillRect(0, 0, w, h);
    if (!st.nodes.length) return;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    st.nodes.forEach((n) => {
      minX = Math.min(minX, n.x);
      minY = Math.min(minY, n.y);
      maxX = Math.max(maxX, n.x);
      maxY = Math.max(maxY, n.y);
    });
    const bw = Math.max(maxX - minX, 1);
    const bh = Math.max(maxY - minY, 1);
    const sc = Math.min((w - 12) / bw, (h - 12) / bh);
    const ox = (w - bw * sc) / 2 - minX * sc;
    const oy = (h - bh * sc) / 2 - minY * sc;
    ctx.strokeStyle = "#334155";
    st.edges.forEach((e) => {
      const a = st.byId[e.from], b = st.byId[e.to];
      if (!a || !b) return;
      ctx.beginPath();
      ctx.moveTo(a.x * sc + ox, a.y * sc + oy);
      ctx.lineTo(b.x * sc + ox, b.y * sc + oy);
      ctx.stroke();
    });
    st.nodes.forEach((n) => {
      ctx.beginPath();
      ctx.arc(n.x * sc + ox, n.y * sc + oy, n.flagged ? 2.4 : 1.8, 0, Math.PI * 2);
      ctx.fillStyle = COLORS[n.type] || "#94a3b8";
      ctx.fill();
    });
    // viewport
    const vx = (-st.panX / st.scale) * sc + ox;
    const vy = (-st.panY / st.scale) * sc + oy;
    const vw = (st.cssW / st.scale) * sc;
    const vh = (st.cssH / st.scale) * sc;
    ctx.strokeStyle = "#60a5fa";
    ctx.lineWidth = 1;
    ctx.strokeRect(vx, vy, vw, vh);
  }

  function paint(st) {
    const ctx = st.ctx;
    const w = st.cssW, h = st.cssH;
    ctx.fillStyle = "#0f1419";
    ctx.fillRect(0, 0, w, h);
    // Subtle grid — operational / map feel, not neon
    ctx.strokeStyle = "rgba(255,255,255,0.03)";
    ctx.lineWidth = 1;
    const step = 40;
    for (let x = 0; x < w; x += step) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
    }
    for (let y = 0; y < h; y += step) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
    }

    if (!st.nodes.length) {
      ctx.fillStyle = "#94a3b8";
      ctx.font = "13px sans-serif";
      ctx.textAlign = "left";
      ctx.fillText("No graph nodes. Click “Load sample” for a full IP ↔ wallet ↔ TX network.", 18, 32);
      paintMini(st);
      return;
    }

    ctx.save();
    ctx.translate(st.panX, st.panY);
    ctx.scale(st.scale, st.scale);

    const linkedIds = {};
    if (st.selectedId) {
      linkedIds[st.selectedId] = true;
      st.edges.forEach((e) => {
        if (e.from === st.selectedId) linkedIds[e.to] = true;
        if (e.to === st.selectedId) linkedIds[e.from] = true;
      });
    }

    // Dim edges first, then hot edges on top
    st.edges.forEach((e) => {
      const a = st.byId[e.from], b = st.byId[e.to];
      if (!a || !b) return;
      const hot = st.selectedId && (e.from === st.selectedId || e.to === st.selectedId);
      if (st.selectedId && !hot) {
        drawEdge(ctx, a, b, e.rel, false);
        return;
      }
      drawEdge(ctx, a, b, e.rel, !!hot || !st.selectedId);
    });

    const ordered = st.nodes.slice().sort((a, b) => {
      const al = !st.selectedId || linkedIds[a.id] ? 1 : 0;
      const bl = !st.selectedId || linkedIds[b.id] ? 1 : 0;
      return al - bl;
    });

    ordered.forEach((n) => {
      const selected = n.id === st.selectedId;
      const linked = !st.selectedId || linkedIds[n.id];
      const dim = st.selectedId && !linked;

      ctx.globalAlpha = dim ? 0.22 : 1;
      const col = COLORS[n.type] || "#64748b";
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
      ctx.fillStyle = col;
      ctx.fill();
      if (n.flagged && !dim) {
        ctx.strokeStyle = "#c45c5c";
        ctx.lineWidth = 1.8;
        ctx.stroke();
      }
      if (selected) {
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r + 4, 0, Math.PI * 2);
        ctx.strokeStyle = "#e5e7eb";
        ctx.lineWidth = 1.6;
        ctx.stroke();
      }
      drawIcon(ctx, n.type, n.x, n.y, n.r);

      // Labels only on selected (+ short flag tip) — kills overlap clutter
      if (selected) {
        let label = shortLabel(n);
        if (label.length > 18) label = label.slice(0, 16) + "…";
        ctx.fillStyle = "#e5e7eb";
        ctx.font = "600 11px ui-sans-serif, system-ui, sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        ctx.fillText(label, n.x, n.y + n.r + 6);
        if (n.flagged) {
          const tip = "Flagged · " + Math.round(n.risk_score || 0) + "%";
          ctx.font = "600 10px ui-sans-serif, system-ui, sans-serif";
          const tw = ctx.measureText(tip).width + 12;
          const tx = n.x - tw / 2;
          const ty = n.y - n.r - 24;
          ctx.fillStyle = "#1a1515";
          ctx.strokeStyle = "#6b3a3a";
          ctx.lineWidth = 1;
          ctx.beginPath();
          if (ctx.roundRect) ctx.roundRect(tx, ty, tw, 17, 3);
          else ctx.rect(tx, ty, tw, 17);
          ctx.fill();
          ctx.stroke();
          ctx.fillStyle = "#e57373";
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          ctx.fillText(tip, n.x, ty + 8.5);
        }
      }
      ctx.globalAlpha = 1;
    });
    ctx.restore();
    paintMini(st);
  }

  function energy(st) {
    let e = 0;
    for (let i = 0; i < st.nodes.length; i++) {
      const n = st.nodes[i];
      e += (n.vx || 0) * (n.vx || 0) + (n.vy || 0) * (n.vy || 0);
    }
    return e;
  }

  function freezeNodes(st) {
    st.nodes.forEach((n) => {
      n.vx = 0;
      n.vy = 0;
    });
    st.simulating = false;
  }

  function tick() {
    if (!state || !state.running) return;
    const st = state;
    // Only simulate while settling or dragging — never forever (that causes shake)
    if (st.simulating || st.dragging) {
      stepForces(st);
      st._simFrames = (st._simFrames || 0) + 1;
      if (!st.dragging && (st._simFrames > 90 || energy(st) < 0.15)) {
        freezeNodes(st);
      }
      paint(st);
      requestAnimationFrame(tick);
      return;
    }
    // Idle: no force loop — graph stays still
    st.running = false;
  }

  function startSim(st, frames) {
    st.simulating = true;
    st._simFrames = 0;
    st._simMax = frames || 90;
    if (!st.running) {
      st.running = true;
      requestAnimationFrame(tick);
    }
  }

  function canvasPoint(st, evt) {
    const rect = st.canvas.getBoundingClientRect();
    return { x: evt.clientX - rect.left, y: evt.clientY - rect.top };
  }

  function unbindWindow() {
    if (moveHandler) window.removeEventListener("mousemove", moveHandler);
    if (upHandler) window.removeEventListener("mouseup", upHandler);
    moveHandler = null;
    upHandler = null;
  }

  function bind(st) {
    const c = st.canvas;
    c.style.cursor = "grab";
    c.style.touchAction = "none";
    unbindWindow();
    let downX = 0, downY = 0, moved = false, downHit = null;

    c.onwheel = (evt) => {
      evt.preventDefault();
      const p = canvasPoint(st, evt);
      const before = screenToWorld(st, p.x, p.y);
      st.scale = Math.max(0.22, Math.min(3.2, st.scale * (evt.deltaY < 0 ? 1.1 : 0.9)));
      st.panX = p.x - before.x * st.scale;
      st.panY = p.y - before.y * st.scale;
      paint(st);
    };
    c.onmousemove = (evt) => {
      if (st.dragging || st.panning) return;
      const p = canvasPoint(st, evt);
      c.style.cursor = hitTest(st, p.x, p.y) ? "pointer" : "grab";
    };
    c.onmousedown = (evt) => {
      if (evt.button !== 0) return;
      evt.preventDefault();
      const p = canvasPoint(st, evt);
      downX = p.x;
      downY = p.y;
      moved = false;
      downHit = hitTest(st, p.x, p.y);
      if (downHit) {
        selectNode(st, downHit);
        st.dragging = downHit;
        downHit.vx = 0;
        downHit.vy = 0;
        c.style.cursor = "pointer";
      } else {
        st.panning = true;
        st.lastX = p.x;
        st.lastY = p.y;
        c.style.cursor = "grabbing";
      }
    };
    moveHandler = (evt) => {
      if (!state || state !== st) return;
      const p = canvasPoint(st, evt);
      if (Math.hypot(p.x - downX, p.y - downY) > 5) moved = true;
      if (st.dragging) {
        const world = screenToWorld(st, p.x, p.y);
        st.dragging.x = world.x;
        st.dragging.y = world.y;
        st.dragging.vx = 0;
        st.dragging.vy = 0;
        paint(st);
      } else if (st.panning) {
        st.panX += p.x - st.lastX;
        st.panY += p.y - st.lastY;
        st.lastX = p.x;
        st.lastY = p.y;
        paint(st);
      }
    };
    upHandler = (evt) => {
      if (!state || state !== st) return;
      const p = canvasPoint(st, evt || { clientX: 0, clientY: 0 });
      if (downHit && !moved) {
        selectNode(st, downHit);
      }
      const wasDrag = !!st.dragging && moved;
      st.dragging = null;
      st.panning = false;
      downHit = null;
      st.canvas.style.cursor = hitTest(st, p.x, p.y) ? "pointer" : "grab";
      // After a real drag, briefly re-settle then freeze (no endless shake)
      if (wasDrag) {
        startSim(st, 40);
      }
    };
    window.addEventListener("mousemove", moveHandler);
    window.addEventListener("mouseup", upHandler);
  }

  function draw(canvas, data, opts) {
    if (!canvas) return null;
    opts = opts || {};
    if (state && state.canvas === canvas) {
      state.running = false;
      if (state._ro) {
        try { state._ro.disconnect(); } catch (e) { /* ignore */ }
      }
      if (state._onWinResize) {
        window.removeEventListener("resize", state._onWinResize);
      }
    }
    const st = emptyState(canvas);
    state = st;
    st.onSelect = opts.onSelect || null;
    st.mini = opts.minimap || null;
    st.miniCtx = st.mini ? st.mini.getContext("2d") : null;
    if (st.mini) {
      st.mini.width = st.mini.clientWidth || 160;
      st.mini.height = st.mini.clientHeight || 100;
    }
    resize(st);

    st.allNodes = ((data && data.nodes) || []).map((n) => Object.assign({}, n));
    st.allEdges = ((data && data.edges) || []).map((e) => Object.assign({}, e));
    st.filter = opts.filter || { risk: "all", type: "all", country: "all" };
    applyFilter(st);
    // Prefer flagged TX as radial center
    let focus = null;
    st.nodes.forEach((n) => {
      if (!n.flagged) return;
      if (n.type !== "tx" && focus && focus.type === "tx") return;
      if (!focus || (n.risk_score || 0) > (focus.risk_score || 0) || (n.type === "tx" && focus.type !== "tx")) {
        focus = n;
      }
    });
    if (!focus) {
      st.nodes.forEach((n) => {
        if (n.type === "tx" && (!focus || (n.degree || 0) > (focus.degree || 0))) focus = n;
      });
    }
    if (!focus) {
      st.nodes.forEach((n) => {
        if (!focus || (n.degree || 0) > (focus.degree || 0)) focus = n;
      });
    }
    initPositions(st.nodes, st.cssW, st.cssH, st.edges, focus ? focus.id : null);
    for (let i = 0; i < 40; i++) stepForces(st);
    freezeNodes(st);
    fitView(st, 48);
    st.selectedId = focus ? focus.id : null;
    if (st.onSelect) st.onSelect(focus || null);
    bind(st);

    // Keep graph aligned to the stage frame on window / layout resize
    if (st._ro) {
      try { st._ro.disconnect(); } catch (e) { /* ignore */ }
    }
    let refitTimer = null;
    const refit = () => {
      if (!state || state !== st) return;
      const prevW = st.cssW, prevH = st.cssH;
      resize(st);
      const grew = Math.abs(st.cssW - prevW) > 2 || Math.abs(st.cssH - prevH) > 2;
      if (grew) {
        settleLayout(st, st.selectedId);
      } else {
        fitView(st, 40);
      }
      paint(st);
    };
    if (typeof ResizeObserver !== "undefined" && st.canvas.parentElement) {
      st._ro = new ResizeObserver(() => {
        clearTimeout(refitTimer);
        refitTimer = setTimeout(refit, 40);
      });
      st._ro.observe(st.canvas.parentElement);
    }
    window.addEventListener("resize", refit);
    st._onWinResize = refit;

    st.running = false;
    st.simulating = false;
    paint(st);
    return {
      setFilter(f) {
        st.filter = Object.assign({}, st.filter, f || {});
        applyFilter(st);
        settleLayout(st, st.selectedId);
        paint(st);
      },
      getCountries() {
        const set = {};
        st.allNodes.forEach((n) => {
          const c = nodeCountry(n);
          if (c && c !== "LOCAL" && c !== "UNK") set[c] = true;
        });
        return Object.keys(set).sort();
      },
      getSelected() {
        return st.selectedId ? st.byId[st.selectedId] : null;
      },
      selectById(id) {
        let live = st.byId[id];
        if (!live && st.allNodes.some((x) => x.id === id)) {
          st.filter = { risk: "all", type: "all", country: "all" };
          applyFilter(st);
          settleLayout(st, id);
          live = st.byId[id];
        }
        if (!live) return null;
        return selectNode(st, live);
      },
      zoom(factor) {
        const cx = st.cssW / 2, cy = st.cssH / 2;
        const before = screenToWorld(st, cx, cy);
        st.scale = Math.max(0.22, Math.min(3.2, st.scale * factor));
        st.panX = cx - before.x * st.scale;
        st.panY = cy - before.y * st.scale;
        paint(st);
      },
      fit() {
        resize(st);
        fitView(st, 48);
        paint(st);
      },
      relayout() {
        resize(st);
        settleLayout(st, st.selectedId);
        paint(st);
      },
    };
  }

  return { draw };
})();

window.Graph = Graph;
