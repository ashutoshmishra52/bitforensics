// Simple force-layout graph renderer (no external libs)
const Graph = (() => {
  const colors = { ip: '#2563eb', wallet: '#16a34a', tx: '#ea580c' };

  function layout(nodes, edges, w, h) {
    nodes.forEach((n, i) => {
      n.x = n.x || w / 2 + Math.cos(i * 1.7) * 180;
      n.y = n.y || h / 2 + Math.sin(i * 1.7) * 160;
      n.vx = 0; n.vy = 0;
    });

    for (let step = 0; step < 80; step++) {
      nodes.forEach(a => nodes.forEach(b => {
        if (a.id === b.id) return;
        let dx = a.x - b.x, dy = a.y - b.y;
        let dist = Math.sqrt(dx * dx + dy * dy) || 1;
        let force = 800 / (dist * dist);
        a.vx += (dx / dist) * force;
        a.vy += (dy / dist) * force;
      }));

      edges.forEach(e => {
        let a = nodes.find(n => n.id === e.from);
        let b = nodes.find(n => n.id === e.to);
        if (!a || !b) return;
        let dx = b.x - a.x, dy = b.y - a.y;
        let dist = Math.sqrt(dx * dx + dy * dy) || 1;
        let force = (dist - 90) * 0.04;
        a.vx += (dx / dist) * force;
        a.vy += (dy / dist) * force;
        b.vx -= (dx / dist) * force;
        b.vy -= (dy / dist) * force;
      });

      nodes.forEach(n => {
        n.vx += (w / 2 - n.x) * 0.001;
        n.vy += (h / 2 - n.y) * 0.001;
        n.vx *= 0.85; n.vy *= 0.85;
        n.x = Math.max(30, Math.min(w - 30, n.x + n.vx));
        n.y = Math.max(30, Math.min(h - 30, n.y + n.vy));
      });
    }
  }

  function draw(canvas, data) {
    if (!canvas || !data.nodes.length) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.width, h = canvas.height;
    const nodes = data.nodes.map(n => ({ ...n }));
    layout(nodes, data.edges, w, h);

    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = '#fafafa';
    ctx.fillRect(0, 0, w, h);

    data.edges.forEach(e => {
      const a = nodes.find(n => n.id === e.from);
      const b = nodes.find(n => n.id === e.to);
      if (!a || !b) return;
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.strokeStyle = '#ddd';
      ctx.lineWidth = 1;
      ctx.stroke();
    });

    nodes.forEach(n => {
      const r = n.type === 'tx' ? 10 : 8;
      ctx.beginPath();
      ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
      ctx.fillStyle = colors[n.type] || '#888';
      ctx.fill();
      if (n.flagged) {
        ctx.strokeStyle = '#dc2626';
        ctx.lineWidth = 2.5;
        ctx.stroke();
      }
      ctx.fillStyle = '#333';
      ctx.font = '10px sans-serif';
      ctx.fillText(n.label, n.x - 30, n.y + r + 12);
    });
  }

  return { draw };
})();
