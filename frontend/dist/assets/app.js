const API = '/api';

const pages = {
  dashboard: ['Overview', 'Bitcoin transaction monitoring'],
  graph: ['Link Graph', 'IP, wallet and transaction connections'],
  alerts: ['Alerts', 'Full TXID, explorer links, and model reasons'],
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
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const detail = err.detail;
    throw new Error(typeof detail === 'string' ? detail : (detail ? JSON.stringify(detail) : 'Request failed'));
  }
  return res.json();
}

function cut(str, n) {
  if (!str) return '-';
  n = n || 18;
  return str.length > n ? str.slice(0, n) + '...' : str;
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
    + '<div><span class="detail-label">Amount</span><span>' + esc(amount) + ' BTC</span></div>'
    + '<div><span class="detail-label">Fee</span><span>' + esc(fee) + ' BTC</span></div>'
    + '<div><span class="detail-label">Script</span><span>' + esc(t.script_type || '-') + '</span></div>'
    + '<div><span class="detail-label">Src IP</span><span>' + esc(t.src_ip || '-') + '</span></div>'
    + '<div><span class="detail-label">Dst IP</span><span>' + esc(t.dst_ip || '-') + '</span></div>'
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
  $('page-title').textContent = pages[name][0];
  $('page-desc').textContent = pages[name][1];
  if (name === 'graph') loadGraph();
}

async function loadStats() {
  const s = await api(API + '/stats');
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
  const parts = [];
  if (s.sources && Object.keys(s.sources).length) {
    const src = Object.keys(s.sources).map(function (name) {
      return name + ': ' + fmt(s.sources[name]);
    }).join(' · ');
    parts.push('Loaded from ' + src + '. Same TXID in two files counts once (no row limit).');
  }
  if (s.total_transactions > 0 && s.leads_generated === 0) {
    parts.push('Data is loaded but not analyzed yet. Click "Run Analysis" to train the model and generate alerts.');
  }
  if (parts.length) {
    hint.style.display = 'block';
    hint.textContent = parts.join(' ');
  } else {
    hint.style.display = 'none';
  }
}

async function loadDashAlerts() {
  const rows = await api(API + '/alerts');
  const el = $('dash-alerts');
  if (!rows.length) {
    el.innerHTML = '<p class="empty">No alerts yet. Click Run Analysis.</p>';
    return;
  }
  el.innerHTML = rows.slice(0, 8).map(function (a) {
    const tx = (a.transactions && a.transactions[0]) || null;
    return '<div class="item">'
      + '<div class="item-title">#' + a.rank + ' ' + esc(a.title) + '</div>'
      + '<div class="item-meta">' + pill(a.priority) + ' confidence ' + a.confidence + '%</div>'
      + (tx ? '<div class="item-meta mono">' + esc(cut(tx.txid, 28)) + '</div>' : '')
      + '</div>';
  }).join('');
}

async function loadDashAnomalies() {
  const rows = await api(API + '/anomalies');
  const el = $('dash-anomalies');
  if (!rows.length) {
    el.innerHTML = '<p class="empty">Nothing flagged yet.</p>';
    return;
  }
  el.innerHTML = rows.slice(0, 8).map(function (a) {
    return '<div class="item">'
      + '<div class="item-title mono">' + esc(cut(a.txid, 28)) + ' · ' + a.amount_btc + ' BTC</div>'
      + '<div class="item-meta">' + pill(a.severity) + ' confidence ' + a.confidence + '%</div>'
      + '<div class="detail-links compact"><a class="ext-link primary-link" href="' + esc(btcTxUrl(a.txid)) + '" target="_blank" rel="noopener">blockchain.com</a></div>'
      + '</div>';
  }).join('');
}

async function loadAlerts() {
  const rows = await api(API + '/alerts');
  const el = $('alert-list');
  if (!rows.length) {
    el.innerHTML = '<p class="empty">No alerts yet. Upload data and click Run Analysis.</p>';
    return;
  }
  el.innerHTML = rows.map(function (a) {
    let body = '<article class="alert-card">'
      + '<header class="alert-head"><div>'
      + '<div class="item-title">#' + a.rank + ' ' + esc(a.title) + '</div>'
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
        return txBlock({
          txid: id,
          blockchain_url: btcTxUrl(id),
        });
      }).join('');
    }

    if (a.ips && a.ips.length) {
      body += '<div class="ip-row"><span class="detail-label">IPs</span>'
        + a.ips.map(function (ip) { return '<span class="tag">' + esc(ip) + '</span>'; }).join('')
        + '</div>';
    }
    body += '</article>';
    return body;
  }).join('');
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

async function loadGraph() {
  try {
    const data = await api(API + '/graph');
    if (window.Graph && $('graph-canvas')) Graph.draw($('graph-canvas'), data);
  } catch (e) {
    toast('Graph failed: ' + e.message);
  }
}

async function refresh() {
  try {
    await Promise.all([
      loadStats(),
      loadDashAlerts(),
      loadDashAnomalies(),
      loadAlerts(),
      loadTransactions(),
      loadClusters(),
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
    toast('Analysis done — ' + res.anomalies + ' anomalies, ' + res.leads + ' alerts');
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
  if (msg) {
    msg.className = '';
    msg.textContent = 'Uploading ' + file.name + '...';
  }
  const form = new FormData();
  form.append('file', file);
  try {
    const res = await api(API + '/ingest', { method: 'POST', body: form });
    if (msg) {
      msg.className = 'ok';
      msg.textContent = res.message;
      if (res.skipped_duplicates) {
        msg.textContent += ' Duplicate TXIDs are merged — total unique rows: ' + Number(res.total_in_db || 0).toLocaleString() + '.';
      }
    }
    toast('Total in database: ' + Number(res.total_in_db || 0).toLocaleString());
    await refresh();
  } catch (e) {
    if (msg) {
      msg.className = 'err';
      msg.textContent = e.message;
    }
    toast(e.message);
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
