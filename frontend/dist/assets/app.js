const API = '/api';

const pages = {
  dashboard: ['Overview', 'Bitcoin transaction monitoring'],
  graph: ['Link Graph', 'IP, wallet and transaction connections'],
  alerts: ['Alerts', 'Full TXID, explorer links, and 120-condition explanations'],
  transactions: ['Transactions', 'All ingested records'],
  clusters: ['Clusters', 'Related wallets or similar transactions'],
  upload: ['Upload', 'Add a CSV, JSON, or XML file'],
};

function $(id) {
  return document.getElementById(id);
}

function toast(msg) {
  const el = $('toast');
  if (!el) return;
  el.textContent = msg;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 2800);
}

async function api(url, opts) {
  const res = await fetch(url, opts);
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch (e) {
    if (!res.ok) throw new Error('Request failed (' + res.status + ')');
    throw new Error('Server returned HTML instead of JSON — restart python run.py');
  }
  if (!res.ok) {
    const detail = data && data.detail;
    throw new Error(typeof detail === 'string' ? detail : (detail ? JSON.stringify(detail) : 'Request failed'));
  }
  return data;
}

function cut(str, n) {
  if (!str) return '-';
  n = n || 18;
  return str.length > n ? str.slice(0, n) + '...' : str;
}

function fmtBtc(n) {
  const x = Number(n);
  if (!Number.isFinite(x)) return '-';
  if (x >= 100) return x.toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (x >= 1) return x.toLocaleString(undefined, { maximumFractionDigits: 4 });
  if (x >= 0.0001) return x.toFixed(6);
  return x.toExponential(2);
}

function typeChip(code, label) {
  const c = code || 'cluster';
  return '<span class="type-chip ' + esc(c) + '">' + esc(label || c) + '</span>';
}

function pill(level) {
  const lv = level || 'LOW';
  return '<span class="pill ' + lv + '">' + lv + '</span>';
}

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/"/g, '&quot;');
}

function copyBtn(text) {
  return '<button type="button" class="copy-btn" data-copy="' + esc(text) + '">Copy</button>';
}

function btcTxUrl(txid) {
  return 'https://www.blockchain.com/explorer/transactions/btc/' + txid;
}
function btcAddrUrl(addr) {
  return 'https://www.blockchain.com/explorer/addresses/btc/' + addr;
}

function txBlock(t) {
  const time = t.timestamp ? new Date(t.timestamp).toLocaleString() : '-';
  const amount = t.amount_btc != null ? t.amount_btc : '-';
  const fee = t.fee_btc != null ? t.fee_btc : '-';
  const chainUrl = t.blockchain_url || btcTxUrl(t.txid);
  let html = ''
    + '<div class="detail-block">'
    + '<div class="detail-row"><span class="detail-label">TXID</span>'
    + '<code class="txid-full">' + esc(t.txid) + '</code>' + copyBtn(t.txid) + '</div>'
    + '<div class="detail-links">'
    + '<a class="ext-link primary-link" href="' + esc(chainUrl) + '" target="_blank" rel="noopener">View on blockchain.com</a>'
    + '</div>'
    + '<div class="detail-grid">'
    + '<div><span class="detail-label">Time</span><span>' + esc(time) + '</span></div>'
    + '<div><span class="detail-label">Amount</span><span>' + esc(fmtBtc(amount)) + ' BTC</span></div>'
    + '<div><span class="detail-label">Fee</span><span>' + esc(fmtBtc(fee)) + ' BTC</span></div>'
    + '<div><span class="detail-label">Script</span><span>' + esc(t.script_type || '-') + '</span></div>'
    + '<div><span class="detail-label">Src IP</span><span>' + esc(t.src_ip || '-') + (t.src_port ? ':' + t.src_port : '') + '</span></div>'
    + '<div><span class="detail-label">Dst IP</span><span>' + esc(t.dst_ip || '-') + (t.dst_port ? ':' + t.dst_port : '') + '</span></div>'
    + '<div><span class="detail-label">Country</span><span>' + esc(t.geo_country || '-') + '</span></div>'
    + '<div><span class="detail-label">ASN</span><span>' + esc(t.asn || '-') + '</span></div>'
    + '</div>';

  if (t.input_addresses && t.input_addresses.length) {
    html += '<div class="addr-section"><span class="detail-label">Inputs</span><div>'
      + t.input_addresses.slice(0, 6).map(function (a) {
        return '<a class="tag link-tag" href="' + esc(btcAddrUrl(a)) + '" target="_blank" rel="noopener">' + esc(cut(a, 20)) + '</a>';
      }).join('') + '</div></div>';
  }
  if (t.output_addresses && t.output_addresses.length) {
    html += '<div class="addr-section"><span class="detail-label">Outputs</span><div>'
      + t.output_addresses.slice(0, 6).map(function (a) {
        return '<a class="tag link-tag" href="' + esc(btcAddrUrl(a)) + '" target="_blank" rel="noopener">' + esc(cut(a, 20)) + '</a>';
      }).join('') + '</div></div>';
  }
  html += '</div>';
  return html;
}

function showTab(name) {
  if (!pages[name]) return;
  document.querySelectorAll('.nav').forEach(function (b) {
    b.classList.toggle('active', b.getAttribute('data-tab') === name);
  });
  document.querySelectorAll('.page').forEach(function (p) {
    p.classList.toggle('active', p.id === 'tab-' + name);
  });
  document.body.classList.toggle('graph-mode', name === 'graph');
  $('page-title').textContent = pages[name][0];
  $('page-desc').textContent = pages[name][1];
  if (name === 'graph') {
    // Wait a frame so graph-mode layout has real width/height, then draw
    requestAnimationFrame(function () {
      loadGraph();
    });
  }
}

function waitForGraphStage(canvas) {
  return new Promise(function (resolve) {
    const parent = canvas && canvas.parentElement;
    if (!parent) {
      resolve();
      return;
    }
    let frames = 0;
    function ready() {
      const r = parent.getBoundingClientRect();
      return r.width > 80 && r.height > 80;
    }
    if (ready()) {
      resolve();
      return;
    }
    function tick() {
      frames += 1;
      if (ready() || frames > 45) resolve();
      else requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  });
}

async function loadGraph() {
  try {
    const canvas = $('graph-canvas');
    if (typeof Graph === 'undefined' || !window.Graph || !canvas) {
      toast('Graph renderer not loaded — hard refresh the page (Cmd+Shift+R)');
      return;
    }
    await waitForGraphStage(canvas);
    const data = await api(API + '/graph');
    if (!_graphStats) {
      try { _graphStats = await api(API + '/stats'); } catch (e) { _graphStats = null; }
    }
    const meta = data.meta || {};
    renderGraphRiskStats(meta);
    renderGraphFooter(meta, _graphStats);
    const note = $('graph-note');
    if (note) {
      note.hidden = true;
      note.textContent = '';
    }
    const range = $('flt-range');
    if (range && range.type !== 'hidden') {
      const times = ((data.nodes || []).map(function (n) { return n.timestamp || n.first_seen || n.last_seen; }).filter(Boolean)).sort();
      range.value = times.length ? (times[0].slice(0, 10) + ' — ' + times[times.length - 1].slice(0, 10)) : 'All dates';
    }
    _graphCtl = window.Graph.draw(canvas, data, {
      onSelect: function (node) { renderGraphDetail(node); },
      minimap: $('graph-minimap'),
      filter: currentGraphFilter(),
    });
    if (_graphCtl && _graphCtl.getCountries) fillCountryFilter(_graphCtl.getCountries());
    // Second pass after paint — guarantees full-size canvas + visible graph
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        if (_graphCtl && _graphCtl.relayout) _graphCtl.relayout();
        else if (_graphCtl && _graphCtl.fit) _graphCtl.fit();
      });
    });
  } catch (e) {
    toast('Graph failed: ' + e.message);
  }
}

async function loadStats() {
  const s = await api(API + '/stats');
  _graphStats = s;
  const vol = Number(s.total_volume_btc || 0);
  const volText = vol >= 1000 ? vol.toLocaleString(undefined, { maximumFractionDigits: 2 }) : String(s.total_volume_btc);
  const fmt = function (n) { return Number(n || 0).toLocaleString(); };
  $('stats').innerHTML = [
    ['Unique transactions', fmt(s.total_transactions)],
    ['Network events', fmt(s.total_network_events)],
    ['Graph nodes', fmt(s.graph_nodes)],
    ['Graph edges', fmt(s.graph_edges)],
    ['Anomalies', fmt(s.anomalies_detected)],
    ['Clusters', fmt(s.clusters_found)],
    ['Alerts', fmt(s.leads_generated)],
    ['Volume BTC', volText],
  ].map(function (pair) {
    return '<div class="stat"><span>' + pair[0] + '</span><strong title="' + esc(String(pair[1])) + '">' + pair[1] + '</strong></div>';
  }).join('');

  const hint = $('hint');
  if (s.total_transactions > 0 && s.leads_generated === 0) {
    hint.style.display = 'block';
    hint.textContent = 'Data is loaded but not analyzed yet. Click "Run Analysis" to train the model and generate alerts.';
  } else {
    hint.style.display = 'none';
    hint.textContent = '';
  }
}

function alertRows(data) {
  if (Array.isArray(data)) return data;
  return (data && data.items) || [];
}

let _alertsReq = null;
function fetchAllAlerts() {
  if (!_alertsReq) _alertsReq = api(API + '/alerts?compact=1');
  return _alertsReq;
}

function renderAlertTable(el, rows, total, expandable) {
  if (!el) return;
  if (!rows.length) {
    el.innerHTML = '<p class="empty">No alerts yet. Click Run Analysis.</p>';
    return;
  }
  const head = '<p class="count-line">Showing all <strong>' + Number(total).toLocaleString()
    + '</strong> alerts from this analysis.</p>';
  const body = rows.map(function (a) {
    const tx = a.txid || '';
    const wallet = a.wallet || '';
    const linkCell = tx
      ? '<a class="txid-link" href="' + esc(btcTxUrl(tx)) + '" target="_blank" rel="noopener">' + esc(cut(tx, 16)) + '</a>'
      : (wallet
        ? '<a class="txid-link" href="' + esc(btcAddrUrl(wallet)) + '" target="_blank" rel="noopener">' + esc(cut(wallet, 16)) + '</a>'
        : '—');
    return '<tr class="alert-line" data-id="' + esc(a.id) + '">'
      + '<td class="num">' + a.rank + '</td>'
      + '<td>' + pill(a.priority) + '</td>'
      + '<td>' + esc(a.title || a.type || '-') + '</td>'
      + '<td class="num">' + (a.confidence != null ? a.confidence : '-') + '%</td>'
      + '<td class="num">' + (a.score != null ? a.score : '-') + '</td>'
      + '<td class="mono">' + linkCell + '</td>'
      + '<td class="num">' + (a.tx_count > 1 ? a.tx_count + ' txs' : (wallet && !tx ? 'wallet' : '')) + '</td>'
      + '</tr>';
  }).join('');
  el.innerHTML = head
    + '<div class="table-box tight">'
    + '<table class="alert-table">'
    + '<thead><tr><th>#</th><th>Priority</th><th>Alert</th><th>Conf</th><th>Score</th><th>TXID</th><th></th></tr></thead>'
    + '<tbody>' + body + '</tbody></table></div>';
  if (!expandable) return;
  el.querySelectorAll('tr.alert-line').forEach(function (tr) {
    tr.addEventListener('click', function (e) {
      if (e.target.closest('a, button')) return;
      toggleAlertDetail(tr);
    });
  });
}

async function toggleAlertDetail(tr) {
  const id = tr.getAttribute('data-id');
  const next = tr.nextElementSibling;
  if (next && next.classList.contains('alert-detail')) {
    next.remove();
    tr.classList.remove('is-open');
    return;
  }
  const open = tr.parentNode.querySelector('tr.alert-detail');
  if (open) {
    const prev = open.previousElementSibling;
    if (prev) prev.classList.remove('is-open');
    open.remove();
  }
  tr.classList.add('is-open');
  const hold = document.createElement('tr');
  hold.className = 'alert-detail';
  hold.innerHTML = '<td colspan="7"><div class="alert-expand"><p class="empty">Loading evidence…</p></div></td>';
  tr.parentNode.insertBefore(hold, tr.nextSibling);
  try {
    const a = await api(API + '/alert-detail?id=' + encodeURIComponent(id));
    hold.querySelector('.alert-expand').innerHTML = renderAlertCard(a);
  } catch (e) {
    hold.querySelector('.alert-expand').innerHTML =
      '<p class="empty err-inline">' + esc(e.message) + '</p>';
  }
}

async function loadDashAlerts() {
  const data = await fetchAllAlerts();
  renderAlertTable($('dash-alerts'), alertRows(data), data.total || alertRows(data).length, true);
}

async function loadDashAnomalies() {
  const rows = await api(API + '/anomalies?limit=20000');
  const el = $('dash-anomalies');
  if (!rows.length) {
    el.innerHTML = '<p class="empty">Nothing flagged yet.</p>';
    return;
  }
  el.innerHTML = '<p class="count-line">Showing all <strong>' + rows.length.toLocaleString()
    + '</strong> Isolation Forest outliers.</p>'
    + '<div class="table-box tight"><table class="alert-table">'
    + '<thead><tr><th>TXID</th><th>Amount</th><th>Severity</th><th>Conf</th><th></th></tr></thead><tbody>'
    + rows.map(function (a) {
      return '<tr>'
        + '<td class="mono"><a class="txid-link" href="' + esc(btcTxUrl(a.txid)) + '" target="_blank" rel="noopener">' + esc(cut(a.txid, 18)) + '</a></td>'
        + '<td class="num">' + fmtBtc(a.amount_btc) + ' BTC</td>'
        + '<td>' + pill(a.severity) + '</td>'
        + '<td class="num">' + a.confidence + '%</td>'
        + '<td><a class="ext-link" href="' + esc(btcTxUrl(a.txid)) + '" target="_blank" rel="noopener">explorer</a></td>'
        + '</tr>';
    }).join('')
    + '</tbody></table></div>';
}

function redFlagPanel(rf) {
  if (!rf) {
    return '<aside class="flag-panel"><p class="empty">No 120-condition match yet.</p></aside>';
  }
  let html = '<aside class="flag-panel">'
    + '<h4>Why this looks suspicious</h4>'
    + '<p class="flag-meta">Matched <strong>' + (rf.matched || 0) + '</strong> of 120 AML/KYT conditions · risk '
    + esc(rf.risk_level || '-') + ' (' + (rf.risk_points || 0) + ' pts)</p>';
  const cats = rf.categories && rf.categories.length ? rf.categories : [];
  if (!cats.length) {
    html += '<p class="empty">Not enough on-chain shape to map a red flag. Indicators are not proof of crime.</p></aside>';
    return html;
  }
  cats.forEach(function (c) {
    html += '<div class="flag-cat"><div class="flag-cat-name">' + esc(c.name) + '</div>';
    (c.flags || []).forEach(function (f) {
      html += '<div class="flag-item">'
        + '<div class="flag-id">#' + f.id + '</div>'
        + '<div><div class="flag-text">' + esc(f.condition) + '</div>'
        + '<div class="flag-why">' + esc(f.why) + '</div></div></div>';
    });
    html += '</div>';
  });
  html += '<p class="flag-note">' + esc(rf.disclaimer || '') + '</p></aside>';
  return html;
}

function renderAlertCard(a) {
  let body = '<article class="alert-card">'
    + '<header class="alert-head"><div>'
    + '<div class="item-title">#' + a.rank + ' ' + typeChip(a.typology, a.typology_label) + ' ' + esc(a.title) + '</div>'
    + '<div class="item-meta">' + esc(a.id) + ' · ' + esc(a.type) + ' · score ' + a.score + '</div>'
    + '</div><div class="alert-badges">' + pill(a.priority)
    + '<span class="conf">confidence ' + a.confidence + '%</span></div></header>'
    + '<p class="alert-summary">' + esc(a.summary) + '</p>';

  if (a.why && a.why.length) {
    body += '<ul class="why-list">' + a.why.map(function (r) { return '<li>' + esc(r) + '</li>'; }).join('') + '</ul>';
  }

  if (a.transactions && a.transactions.length) {
    body += a.transactions.filter(function (t) {
      return t.amount_btc == null || Number(t.amount_btc) > 0;
    }).map(txBlock).join('');
  } else if (a.txids && a.txids.length) {
    body += a.txids.map(function (id) {
      return txBlock({ txid: id, blockchain_url: btcTxUrl(id) });
    }).join('');
  }

  if (a.wallets && a.wallets.length && !(a.transactions && a.transactions.length)) {
    body += '<div class="addr-section"><span class="detail-label">Wallets</span><div>'
      + a.wallets.slice(0, 8).map(function (w) {
        return '<a class="tag link-tag" href="' + esc(btcAddrUrl(w)) + '" target="_blank" rel="noopener">' + esc(cut(w, 20)) + '</a>';
      }).join('') + '</div></div>';
  }
  if (a.ips && a.ips.length) {
    body += '<div class="ip-row"><span class="detail-label">IPs</span>'
      + a.ips.map(function (ip) { return '<span class="tag">' + esc(ip) + '</span>'; }).join('')
      + '</div>';
  }
  body += '</article>';
  return '<div class="alert-row">' + body + redFlagPanel(a.red_flags) + '</div>';
}

async function loadAlerts() {
  const data = await fetchAllAlerts();
  const rows = alertRows(data);
  const el = $('alert-list');
  renderAlertTable(el, rows, data.total || rows.length, true);
}

async function loadTransactions() {
  const rows = await api(API + '/transactions?limit=100');
  const body = $('tx-body');
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="8" class="empty">No data</td></tr>';
    return;
  }
  body.innerHTML = rows.map(function (t) {
    return '<tr>'
      + '<td class="mono"><a class="txid-link" href="' + esc(btcTxUrl(t.txid)) + '" target="_blank" rel="noopener">' + esc(cut(t.txid, 16)) + '</a> ' + copyBtn(t.txid) + '</td>'
      + '<td>' + (t.timestamp ? new Date(t.timestamp).toLocaleString() : '-') + '</td>'
      + '<td>' + t.amount_btc + '</td><td>' + t.fee_btc + '</td>'
      + '<td>' + esc(t.script_type) + '</td>'
      + '<td>' + esc(t.src_ip || '-') + '</td>'
      + '<td>' + esc(t.geo_country || '-') + '</td>'
      + '<td>' + esc(t.asn || '-') + '</td>'
      + '</tr>';
  }).join('');
}

async function loadClusters() {
  const rows = await api(API + '/clusters');
  const el = $('cluster-list');
  if (!rows.length) {
    el.innerHTML = '<p class="empty">No clusters found.</p>';
    return;
  }
  const groups = {};
  rows.forEach(function (r) {
    (groups[r.cluster_id] = groups[r.cluster_id] || []).push(r);
  });
  el.innerHTML = Object.keys(groups).map(function (id) {
    const members = groups[id];
    const vol = members.reduce(function (s, m) { return s + m.total_volume_btc; }, 0).toFixed(4);
    const looksTx = members[0].address && members[0].address.length >= 32;
    return '<div class="item">'
      + '<div class="item-title">Cluster ' + id + ' · ' + members.length + (looksTx ? ' transactions' : ' wallets') + ' · ' + vol + ' BTC</div>'
      + '<div class="item-meta">' + esc(members[0].entity_type) + '</div>'
      + '<div>' + members.slice(0, 6).map(function (m) {
        const href = looksTx
          ? btcTxUrl(m.address)
          : btcAddrUrl(m.address);
        return '<a class="tag link-tag" href="' + href + '" target="_blank" rel="noopener">' + esc(cut(m.address, 16)) + '</a>';
      }).join('') + '</div></div>';
  }).join('');
}

let _graphCtl = null;
let _graphStats = null;

function fmtWhen(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString();
  } catch (e) {
    return String(iso);
  }
}

function riskLegendHtml() {
  return '<div class="risk-legend">'
    + '<span><i style="background:#ff4d4d"></i>High</span>'
    + '<span><i style="background:#ff9f43"></i>Medium</span>'
    + '<span><i style="background:#28c76f"></i>Low</span>'
    + '<span><i style="background:#60a5fa"></i>Normal</span>'
    + '</div>';
}

function metaRow(label, value) {
  return '<div class="meta-row"><span class="meta-k">' + esc(label) + '</span><span class="meta-v">' + value + '</span></div>';
}

function relLabel(rel) {
  if (rel === 'src' || rel === 'dst') return 'IP observed in TX';
  if (rel === 'input') return 'Wallet input → TX';
  if (rel === 'output') return 'TX → Wallet output';
  return rel || 'linked';
}

function renderGraphDetail(node) {
  const el = $('graph-detail');
  if (!el) return;
  if (!node) {
    el.innerHTML = '<h4>Entity details</h4>'
      + '<p class="empty">Click any IP, wallet, or TX icon on the graph. Neighbours appear here as clickable evidence chips.</p>'
      + '<div class="ps-box">'
      + '<strong>What this graph answers (PS)</strong>'
      + '<ul>'
      + '<li>Which <em>IPs</em> were observed with a transaction</li>'
      + '<li>Which <em>wallets</em> funded or received that TX</li>'
      + '<li>Why ML flagged an entity (confidence + reasons)</li>'
      + '</ul></div>'
      + riskLegendHtml();
    return;
  }
  const iconClass = node.type === 'ip' ? 'gicon-ip' : node.type === 'wallet' ? 'gicon-wallet' : 'gicon-tx';
  const iconSvg = node.type === 'ip'
    ? '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="4" ry="9"/><path d="M3 12h18M12 3v18"/></svg>'
    : node.type === 'wallet'
      ? '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="6" width="18" height="13" rx="2"/><path d="M16 12h5v3h-5a1.5 1.5 0 0 1 0-3z"/></svg>'
      : '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M8 12h8M14 9l3 3-3 3"/></svg>';
  const risk = Number(node.risk_score || 0);
  const sev = (node.severity || (node.flagged ? 'HIGH' : 'NORMAL')).toUpperCase();
  const badge = node.flagged
    ? '<span class="pill ' + (sev === 'MEDIUM' ? 'MEDIUM' : sev === 'LOW' ? 'LOW' : 'HIGH') + '">'
      + (sev === 'MEDIUM' ? 'MEDIUM RISK' : sev === 'LOW' ? 'LOW RISK' : 'HIGH RISK') + '</span>'
    : '<span class="pill LOW">NORMAL</span>';
  const fullId = node.address || node.txid || node.ip || node.label || node.id;
  const typeName = node.type === 'ip' ? 'IP' : node.type === 'wallet' ? 'Wallet' : 'Transaction';

  let html = '<div class="item-kicker">'
    + '<button type="button" class="gicon ' + iconClass + ' gicon-btn" title="Selected entity">' + iconSvg + '</button>'
    + badge
    + '<span class="type-pill">' + esc(typeName) + '</span>'
    + '</div>';
  html += '<div class="item-title mono">' + esc(fullId) + copyBtn(fullId) + '</div>';
  if (node.pattern_label) {
    html += '<div class="pattern-box"><strong>' + esc(node.pattern_label) + '</strong>'
      + '<p>' + esc(node.pattern_why || 'SIH typology from fan-in / fan-out / amount shape.') + '</p></div>';
  }
  html += '<p class="layer-tag">' + esc(node.layer_label || '') + '</p>';
  html += '<div class="risk-row"><div class="risk-big">' + Math.round(risk) + '%</div>'
    + '<div class="risk-bar"><span style="width:' + Math.min(100, Math.max(0, risk)) + '%"></span></div></div>';
  html += '<p class="risk-caption">Confidence score from analysis</p>';

  html += '<div class="meta-list">';
  if (node.type === 'wallet') {
    const countries = (node.top_countries || []).slice(0, 4).join(', ') || '—';
    html += metaRow('First Seen', esc(fmtWhen(node.first_seen)));
    html += metaRow('Last Seen', esc(fmtWhen(node.last_seen)));
    html += metaRow('Total Received', esc(fmtBtc(node.total_received)) + ' BTC');
    html += metaRow('Total Sent', esc(fmtBtc(node.total_sent)) + ' BTC');
    html += metaRow('Connected IPs', String(node.connected_ips || 0));
    html += metaRow('Connected TXs', String(node.connected_txs || 0));
    html += metaRow('Top Countries', esc(countries));
  } else if (node.type === 'tx') {
    html += metaRow('Time', esc(fmtWhen(node.timestamp)));
    html += metaRow('Amount', esc(fmtBtc(node.amount_btc)) + ' BTC');
    html += metaRow('Fee', esc(fmtBtc(node.fee_btc)) + ' BTC');
    html += metaRow('Script', esc(node.script_type || '—'));
    html += metaRow('Geo / ASN', esc((node.geo_country || '—') + ' · ' + (node.asn || '—')));
    html += metaRow('Src IP', esc(node.src_ip || '—'));
    html += metaRow('Dst IP', esc(node.dst_ip || '—'));
    html += metaRow('Connected Wallets', String(node.connected_wallets || 0));
  } else {
    html += metaRow('IP', '<span class="mono">' + esc(node.ip || node.label || '—') + '</span>');
    html += metaRow('Country', esc(node.country || '—'));
    html += metaRow('ASN', esc(node.asn || '—'));
    html += metaRow('Role', esc(node.role === 'src' ? 'Source peer' : node.role === 'dst' ? 'Destination peer' : (node.role || '—')));
    html += metaRow('Connected TXs', String(node.connected_txs || 0));
    html += metaRow('Connected Wallets', String(node.connected_wallets || 0));
  }
  html += '</div>';

  const neighbors = node.neighbors || [];
  html += '<h4>Linked evidence <span class="soft-count">(' + neighbors.length + ') — click any</span></h4>';
  if (neighbors.length) {
    html += '<div class="nb-list">' + neighbors.map(function (nb) {
      const cls = 'nb-chip nb-' + esc(nb.type) + (nb.flagged ? ' nb-flag' : '');
      return '<button type="button" class="' + cls + '" data-node-id="' + esc(nb.id) + '" title="Open ' + esc(relLabel(nb.rel)) + '">'
        + '<span class="nb-type">' + esc((nb.type || '').toUpperCase()) + '</span>'
        + '<span class="nb-label">' + esc(nb.label || nb.id) + '</span>'
        + (nb.flagged ? '<span class="nb-risk">' + Math.round(nb.risk_score || 0) + '%</span>' : '')
        + '</button>';
    }).join('') + '</div>';
  } else {
    html += '<p class="empty">No linked neighbours — click another node on the graph.</p>';
  }

  const why = node.why || [];
  html += '<h4>Why this matters (SIH)</h4>';
  if (why.length) {
    html += '<ul class="why-list">' + why.map(function (w) { return '<li>' + esc(w) + '</li>'; }).join('') + '</ul>';
  } else {
    html += '<p class="empty">Select a flagged TX to see typology + model reasons.</p>';
  }

  const href = node.type === 'wallet' && node.address
    ? btcAddrUrl(node.address)
    : (node.type === 'tx' && node.txid ? btcTxUrl(node.txid) : '');
  if (href) {
    html += '<a class="btn btn-main invest-detail-btn" href="' + esc(href) + '" target="_blank" rel="noopener">View Full Details →</a>';
  }
  html += riskLegendHtml();
  el.innerHTML = html;
}

function renderGraphRiskStats(meta) {
  const el = $('graph-risk-stats');
  if (!el) return;
  const c = (meta && meta.counts) || {};
  const r = (meta && meta.risk_counts) || {};
  const total = (c.ip || 0) + (c.wallet || 0) + (c.tx || 0);
    el.innerHTML =
    '<span class="pill-stat high">High<strong>' + (r.high || 0) + '</strong></span>'
    + '<span class="pill-stat med">Med<strong>' + (r.medium || 0) + '</strong></span>'
    + '<span class="pill-stat low">Low<strong>' + (r.low || 0) + '</strong></span>'
    + '<span class="pill-stat total">Total<strong>' + total + '</strong></span>';
}

function renderGraphFooter(meta, stats) {
  const el = $('graph-footer');
  if (!el) return;
  const c = (meta && meta.counts) || {};
  const fmt = function (n) { return Number(n || 0).toLocaleString(); };
  el.innerHTML =
    '<span class="ft-item"><span class="ft-ico" style="background:#4169e1"></span>Total Transactions <strong>' + fmt(stats && stats.total_transactions != null ? stats.total_transactions : c.tx) + '</strong></span>'
    + '<span class="ft-item"><span class="ft-ico" style="background:#ff9f43"></span>Total Wallets <strong>' + fmt(c.wallet) + '</strong></span>'
    + '<span class="ft-item"><span class="ft-ico" style="background:#28c76f"></span>Total IPs <strong>' + fmt(c.ip) + '</strong></span>'
    + '<span class="ft-item"><span class="ft-ico" style="background:#ff4d4d"></span>Anomalies Detected <strong>' + fmt(stats && stats.anomalies_detected) + '</strong></span>'
    + '<span class="ft-item"><span class="ft-ico" style="background:#9b59b6"></span>Clusters Identified <strong>' + fmt(stats && stats.clusters_found) + '</strong></span>';
}

function fillCountryFilter(countries) {
  const sel = $('flt-country');
  if (!sel) return;
  const cur = sel.value || 'all';
  sel.innerHTML = '<option value="all">All</option>'
    + (countries || []).map(function (c) {
      return '<option value="' + esc(c) + '">' + esc(c) + '</option>';
    }).join('');
  sel.value = cur;
  if (sel.value !== cur) sel.value = 'all';
}

function currentGraphFilter() {
  return {
    risk: ($('flt-risk') && $('flt-risk').value) || 'all',
    type: ($('flt-type') && $('flt-type').value) || 'all',
    country: ($('flt-country') && $('flt-country').value) || 'all',
  };
}

function applyGraphFilters() {
  if (!_graphCtl || !_graphCtl.setFilter) return;
  _graphCtl.setFilter(currentGraphFilter());
  toast('Filters applied');
}

function selectGraphNode(id) {
  if (!_graphCtl || !_graphCtl.selectById) return;
  const n = _graphCtl.selectById(id);
  if (!n) toast('Entity not in current graph view — try Show all / Load sample');
}

function filterGraphByType(type) {
  const sel = $('flt-type');
  if (sel) sel.value = type || 'all';
  applyGraphFilters();
}

async function loadNetworkSample() {
  const btn = $('btn-graph-sample');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Loading…';
  }
  try {
    const res = await api(API + '/demo/network-sample', { method: 'POST' });
    toast(res.message || 'Network sample ready');
    await refresh();
    showTab('graph');
    await loadGraph();
  } catch (e) {
    toast(e.message);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Sample';
    }
  }
}

async function refresh() {
  _alertsReq = null;
  try {
    await Promise.all([
      loadStats(),
      loadDashAlerts(),
      loadDashAnomalies(),
      loadAlerts(),
      loadTransactions(),
      loadClusters(),
      loadGeoStatus(),
    ]);
    if ($('tab-graph') && $('tab-graph').classList.contains('active')) {
      await loadGraph();
    }
  } catch (e) {
    toast(e.message);
  }
}

async function runAnalysis() {
  const btn = $('btn-run');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Running...';
  }
  try {
    const res = await api(API + '/analyze', { method: 'POST' });
    var msg = 'Analysis done — ' + res.anomalies + ' anomalies, ' + res.leads + ' alerts';
    if (res.alert_export && res.alert_export.filename) {
      msg += ' · saved ' + res.alert_export.filename;
      if (res.alert_export.postgres && res.alert_export.postgres.saved) {
        msg += ' (+ Postgres)';
      }
    }
    toast(msg);
    await refresh();
  } catch (e) {
    toast(e.message);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Run Analysis';
    }
  }
}

async function uploadFile(file) {
  const msg = $('upload-msg');
  const drop = $('drop-zone');
  const progress = $('upload-progress');
  const ptext = $('upload-progress-text');
  if (msg) {
    msg.className = '';
    msg.textContent = '';
  }
  if (drop) drop.classList.add('busy');
  if (progress) progress.hidden = false;
  if (ptext) ptext.textContent = 'Uploading ' + file.name + '…';
  const form = new FormData();
  form.append('file', file);
  try {
    const res = await api(API + '/ingest', { method: 'POST', body: form });
    if (ptext) ptext.textContent = 'Loaded. Opening Overview…';
    toast('Total in database: ' + Number(res.total_in_db || 0).toLocaleString());
    await refresh();
    showTab('dashboard');
  } catch (e) {
    if (msg) {
      msg.className = 'err';
      msg.textContent = e.message;
    }
    toast(e.message);
  } finally {
    if (drop) drop.classList.remove('busy');
    if (progress) progress.hidden = true;
    if (input) input.value = '';
  }
}

async function loadGeoStatus() {
  const el = $('geo-status');
  const side = $('sidebar-status');
  try {
    const g = await api(API + '/geo/status');
    const engine = g.engine === 'db-ip-mmdb' ? 'DB-IP Lite MMDB' : 'bundled GeoIP CSV';
    if (el) {
      el.textContent = 'Engine: ' + engine + ' · country DB ' + (g.country_db ? 'yes' : 'no') + ' · ASN DB ' + (g.asn_db ? 'yes' : 'no') + ' · ' + (g.source || '');
    }
    if (side) side.textContent = 'Offline · Linux · Geo ' + (g.engine === 'db-ip-mmdb' ? 'MMDB' : 'CSV');
  } catch (e) {
    if (el) el.textContent = 'GeoIP status unavailable';
  }
}

async function downloadGeo() {
  const btn = $('btn-geo');
  const el = $('geo-status');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Downloading…';
  }
  if (el) el.textContent = 'Fetching DB-IP Lite (needs internet once)…';
  try {
    const res = await api(API + '/geo/download', { method: 'POST' });
    toast(res.message || 'GeoIP ready');
    await loadGeoStatus();
  } catch (e) {
    toast(e.message);
    if (el) el.textContent = e.message;
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Download DB-IP Lite';
    }
  }
}

async function clearData() {
  if (!confirm('Delete ALL stored data?\n\nThis removes transactions, alerts, clusters, and correlations.')) {
    return;
  }
  try {
    const res = await api(API + '/reset', { method: 'POST' });
    const d = res.deleted || {};
    toast('Cleared ' + (d.transactions || 0) + ' transactions');
    await refresh();
  } catch (e) {
    toast(e.message);
  }
}

function bind(id, event, handler) {
  const el = $(id);
  if (el) el.addEventListener(event, handler);
}

document.getElementById('main-nav').addEventListener('click', function (e) {
  const btn = e.target.closest('.nav');
  if (!btn) return;
  e.preventDefault();
  showTab(btn.getAttribute('data-tab'));
});

bind('btn-run', 'click', runAnalysis);
bind('btn-refresh', 'click', refresh);
bind('btn-clear', 'click', clearData);
bind('btn-clear-upload', 'click', clearData);
bind('btn-geo', 'click', downloadGeo);
bind('btn-graph-sample', 'click', loadNetworkSample);
bind('btn-graph-refresh', 'click', loadGraph);
bind('btn-graph-filter', 'click', applyGraphFilters);
bind('btn-graph-alerts', 'click', function () { showTab('alerts'); });
bind('btn-graph-back', 'click', function () { showTab('dashboard'); });
bind('btn-graph-zoom-in', 'click', function () { if (_graphCtl && _graphCtl.zoom) _graphCtl.zoom(1.15); });
bind('btn-graph-zoom-out', 'click', function () { if (_graphCtl && _graphCtl.zoom) _graphCtl.zoom(0.87); });
bind('btn-graph-fit', 'click', function () { if (_graphCtl && _graphCtl.fit) _graphCtl.fit(); });

document.body.addEventListener('click', function (e) {
  const leg = e.target.closest('[data-filter-type]');
  if (leg && $('tab-graph') && $('tab-graph').classList.contains('active')) {
    e.preventDefault();
    filterGraphByType(leg.getAttribute('data-filter-type'));
    return;
  }
  const chip = e.target.closest('[data-node-id]');
  if (chip) {
    e.preventDefault();
    selectGraphNode(chip.getAttribute('data-node-id'));
  }
});

document.body.addEventListener('click', function (e) {
  const btn = e.target.closest('[data-copy]');
  if (!btn) return;
  const text = btn.getAttribute('data-copy');
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(function () { toast('Copied'); }).catch(function () { toast('Copy failed'); });
  } else {
    toast('Copy not supported');
  }
});

const drop = $('drop-zone');
const input = $('file-input');
if (drop && input) {
  drop.addEventListener('click', function () { input.click(); });
  drop.addEventListener('dragover', function (e) { e.preventDefault(); });
  drop.addEventListener('drop', function (e) {
    e.preventDefault();
    if (e.dataTransfer.files[0]) uploadFile(e.dataTransfer.files[0]);
  });
  input.addEventListener('change', function () {
    if (input.files[0]) uploadFile(input.files[0]);
  });
}

refresh();
