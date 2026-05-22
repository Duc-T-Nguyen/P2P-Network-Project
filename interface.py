import json
import os
import sys
import threading
import time
from flask import Flask, request, redirect, url_for, render_template_string, jsonify

sys.path.insert(0, os.path.dirname(__file__))
from Peer import BitTorrentClient

app = Flask(__name__)

_state={
    'status': 'idle', 
    'torrent_name': '',
    'is_multi_file': False,
    'total_size': 0,
    'progress':{
        'pieces_done': 0,
        'num_pieces': 0,
        'percent': 0.0,
        'speed_bps': 0.0,
        'files':[]

    },
    'peers': 0,
    'error': '',
    'log': [],
    'start_time': None,
    'end_time': None,
}

_state_lock = threading.Lock()
_client: BitTorrentClient = None


def _log(msg: str):
    ts = time.strftime('%H:%M:%S')

    line = f"[{ts}] {msg}"
    print(line)
    with _state_lock:
        _state['log'].append(line)
        if len(_state['log']) > 100:
            _state['log'].pop(0)
        

def _progress_callback(info: dict):
    with _state_lock:
        _state['progress'] = info
        if _client:
            with _client._peers_lock:
                _state['peers'] = len(_client._peers)
        if info['percent'] >= 100.0:
            _state['status'] = 'seeding'
            _state['end_time'] = time.time()
    _log(f"Progress {info['percent']:.1f}%  "
         f"({info['pieces_done']}/{info['num_pieces']} pieces)  "
         f"{info['speed_bps']/1024:.1f} KB/s")

def _run_client(torrent_path: str,  output_dir: str):
    global _client
    try:
        with _state_lock:
            _state['status'] = 'loading'
            _state['error']=''

        _log(f"Loading torrent file: {torrent_path}")

        _client = BitTorrentClient(torrent_path, output_dir = output_dir, progress_callback = _progress_callback)

        from Torrent import Torrent
        t = Torrent(torrent_path)
        with _state_lock:
            _state['torrent_name'] = t.file_name()
            _state['is_multi_file'] = t.is_multi_file()
            _state['total_size'] = t.file_length()
            _state['status'] = 'downloading'
            _state['start_time'] = time.time()
 
        _log(f"Name: {t.file_name()}  |  Size: {t.file_length()} bytes  |  Multi-file: {t.is_multi_file()}")
        for f in t.files():
            _log(f"  File: {f['path']}  ({f['length']} bytes)")
 
        _client.start()          # blocks until done / Ctrl-C
 
        with _state_lock:
            if _state['status'] != 'seeding':
                _state['status'] = 'done'
                _state['end_time'] = time.time()
        _log("Client finished.")
 
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        _log(f"ERROR: {e}\n{tb}")
        with _state_lock:
            _state['status'] = 'error'
            _state['error'] = str(e)
 
 
# ── HTML template ─────────────────────────────────────────────────────────────
HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>P2P Client</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Syne:wght@400;700;800&display=swap');
 
  :root {
    --bg:        #0c0e14;
    --surface:   #13161f;
    --border:    #1e2433;
    --accent:    #00e5ff;
    --accent2:   #7b2fff;
    --green:     #00ff94;
    --warn:      #ffb300;
    --danger:    #ff3d5a;
    --text:      #d4daf0;
    --muted:     #4a516a;
    --radius:    8px;
  }
 
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
 
  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'JetBrains Mono', monospace;
    font-size: 13px;
    min-height: 100vh;
  }
 
  /* ── grid layout ── */
  .shell {
    display: grid;
    grid-template-rows: 56px 1fr;
    grid-template-columns: 260px 1fr;
    grid-template-areas:
      "header  header"
      "sidebar main";
    min-height: 100vh;
  }
 
  /* ── header ── */
  header {
    grid-area: header;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    padding: 0 24px;
    gap: 14px;
  }
  header .logo {
    font-family: 'Syne', sans-serif;
    font-weight: 800;
    font-size: 18px;
    letter-spacing: -.5px;
    color: var(--accent);
  }
  header .logo span { color: var(--accent2); }
  .status-pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: .8px;
    padding: 3px 10px;
    border-radius: 20px;
    border: 1px solid;
  }
  .status-pill.idle    { color: var(--muted);  border-color: var(--muted); }
  .status-pill.loading { color: var(--warn);   border-color: var(--warn); }
  .status-pill.downloading { color: var(--accent); border-color: var(--accent); }
  .status-pill.seeding { color: var(--green);  border-color: var(--green); }
  .status-pill.done    { color: var(--green);  border-color: var(--green); }
  .status-pill.error   { color: var(--danger); border-color: var(--danger); }
  .dot {
    width: 7px; height: 7px;
    border-radius: 50%;
    background: currentColor;
    animation: pulse 1.4s ease-in-out infinite;
  }
  .status-pill.idle .dot,
  .status-pill.done .dot { animation: none; }
  @keyframes pulse {
    0%,100% { opacity: 1; }
    50%      { opacity: 0.3; }
  }
 
  /* ── sidebar ── */
  aside {
    grid-area: sidebar;
    background: var(--surface);
    border-right: 1px solid var(--border);
    padding: 20px 16px;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }
  .card {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 16px;
  }
  .card-title {
    font-family: 'Syne', sans-serif;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: var(--muted);
    margin-bottom: 12px;
  }
  .metric {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 8px;
  }
  .metric-label { color: var(--muted); font-size: 11px; }
  .metric-value { font-weight: 600; color: var(--text); font-size: 13px; }
  .metric-value.accent { color: var(--accent); }
  .metric-value.green  { color: var(--green); }
 
  /* ── launch form ── */
  form.launch { display: flex; flex-direction: column; gap: 10px; }
  label { font-size: 11px; color: var(--muted); margin-bottom: 3px; display: block; }
  input[type=text], input[type=file] {
    width: 100%;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 4px;
    color: var(--text);
    font-family: inherit;
    font-size: 12px;
    padding: 7px 10px;
    outline: none;
    transition: border-color .15s;
  }
  input[type=text]:focus, input[type=file]:focus {
    border-color: var(--accent);
  }
  button.btn {
    width: 100%;
    padding: 9px;
    background: transparent;
    border: 1px solid var(--accent);
    border-radius: 4px;
    color: var(--accent);
    font-family: 'Syne', sans-serif;
    font-weight: 700;
    font-size: 12px;
    letter-spacing: .5px;
    cursor: pointer;
    transition: background .15s, color .15s;
  }
  button.btn:hover {
    background: var(--accent);
    color: var(--bg);
  }
  button.btn.danger {
    border-color: var(--danger);
    color: var(--danger);
  }
  button.btn.danger:hover {
    background: var(--danger);
    color: #fff;
  }
 
  /* ── main area ── */
  main {
    grid-area: main;
    padding: 24px;
    display: flex;
    flex-direction: column;
    gap: 20px;
    overflow-y: auto;
  }
 
  /* ── overall progress bar ── */
  .big-progress-wrap {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 20px 24px;
  }
  .big-progress-header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 14px;
  }
  .torrent-name {
    font-family: 'Syne', sans-serif;
    font-size: 15px;
    font-weight: 700;
    color: var(--text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 60%;
  }
  .pct-label {
    font-family: 'Syne', sans-serif;
    font-size: 28px;
    font-weight: 800;
    color: var(--accent);
  }
  .progress-bar-track {
    height: 10px;
    background: var(--border);
    border-radius: 99px;
    overflow: hidden;
  }
  .progress-bar-fill {
    height: 100%;
    border-radius: 99px;
    background: linear-gradient(90deg, var(--accent2), var(--accent));
    transition: width .6s ease;
  }
  .progress-bar-fill.done {
    background: linear-gradient(90deg, var(--green), #00c978);
  }
 
  /* ── piece grid ── */
  .piece-section {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 16px 20px;
  }
  .piece-section-title {
    font-family: 'Syne', sans-serif;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: var(--muted);
    margin-bottom: 12px;
  }
  #piece-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 2px;
  }
  .piece-cell {
    width: 8px;
    height: 8px;
    border-radius: 2px;
    background: var(--border);
    transition: background .2s;
  }
  .piece-cell.done    { background: var(--accent); }
  .piece-cell.seeding { background: var(--green); }
 
  /* ── file list ── */
  .file-list {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 16px 20px;
  }
  .file-list-title {
    font-family: 'Syne', sans-serif;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: var(--muted);
    margin-bottom: 14px;
  }
  .file-row {
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 10px;
    align-items: center;
    margin-bottom: 12px;
  }
  .file-name {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    color: var(--text);
    font-size: 12px;
  }
  .file-pct { color: var(--accent); font-size: 12px; font-weight: 600; min-width: 44px; text-align: right; }
  .file-bar-track {
    grid-column: 1 / -1;
    height: 4px;
    background: var(--border);
    border-radius: 99px;
    overflow: hidden;
    margin-top: -6px;
  }
  .file-bar-fill {
    height: 100%;
    border-radius: 99px;
    background: var(--accent2);
    transition: width .6s ease;
  }
 
  /* ── log console ── */
  .log-console {
    background: #080a10;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 14px 16px;
    font-size: 11px;
    line-height: 1.6;
    height: 220px;
    overflow-y: auto;
    color: #637094;
  }
  .log-console .ln { display: block; }
  .log-console .ln.info  { color: #637094; }
  .log-console .ln.ok    { color: var(--green); }
  .log-console .ln.err   { color: var(--danger); }
  .log-section-title {
    font-family: 'Syne', sans-serif;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: var(--muted);
    margin-bottom: 8px;
  }
</style>
</head>
<body>
<div class="shell">
 
  <!-- header -->
  <header>
    <div class="logo">P2P<span>.</span>client</div>
    <div id="status-pill" class="status-pill idle"><div class="dot"></div><span id="status-text">idle</span></div>
  </header>
 
  <!-- sidebar -->
  <aside>
    <div class="card">
      <div class="card-title">Launch Download</div>
      <form class="launch" onsubmit="launchDownload(event)">
        <div>
          <label>Torrent file path</label>
          <input type="text" id="torrent-path" placeholder="./file.torrent">
        </div>
        <div>
          <label>Output directory</label>
          <input type="text" id="output-dir" placeholder="./" value="./">
        </div>
        <button type="submit" class="btn">▶ Start</button>
      </form>
    </div>
 
    <div class="card">
      <div class="card-title">Session Stats</div>
      <div class="metric"><span class="metric-label">Speed</span><span id="stat-speed" class="metric-value accent">— KB/s</span></div>
      <div class="metric"><span class="metric-label">Peers</span><span id="stat-peers" class="metric-value">—</span></div>
      <div class="metric"><span class="metric-label">Pieces</span><span id="stat-pieces" class="metric-value">—</span></div>
      <div class="metric"><span class="metric-label">Total size</span><span id="stat-size" class="metric-value">—</span></div>
      <div class="metric"><span class="metric-label">Elapsed</span><span id="stat-elapsed" class="metric-value">—</span></div>
    </div>
 
    <div style="margin-top:auto">
      <button class="btn danger" onclick="stopDownload()">■ Stop</button>
    </div>
  </aside>
 
  <!-- main -->
  <main>
    <!-- overall progress -->
    <div class="big-progress-wrap">
      <div class="big-progress-header">
        <div id="torrent-name" class="torrent-name">No torrent loaded</div>
        <div id="pct-label" class="pct-label">0%</div>
      </div>
      <div class="progress-bar-track">
        <div id="progress-fill" class="progress-bar-fill" style="width:0%"></div>
      </div>
    </div>
 
    <!-- piece visualizer -->
    <div class="piece-section">
      <div class="piece-section-title">Piece map</div>
      <div id="piece-grid"></div>
    </div>
 
    <!-- file list -->
    <div class="file-list" id="file-list-section" style="display:none">
      <div class="file-list-title">Files</div>
      <div id="file-rows"></div>
    </div>
 
    <!-- log -->
    <div>
      <div class="log-section-title">Activity log</div>
      <div id="log-console" class="log-console"></div>
    </div>
  </main>
 
</div>
 
<script>
let _pieceCount = 0;
let _seeding = false;
let _logLen = 0;
 
function fmtBytes(b) {
  if (b < 1024) return b + ' B';
  if (b < 1048576) return (b/1024).toFixed(1) + ' KB';
  if (b < 1073741824) return (b/1048576).toFixed(1) + ' MB';
  return (b/1073741824).toFixed(2) + ' GB';
}
function fmtSpeed(bps) {
  if (bps < 1024) return bps.toFixed(0) + ' B/s';
  if (bps < 1048576) return (bps/1024).toFixed(1) + ' KB/s';
  return (bps/1048576).toFixed(2) + ' MB/s';
}
function fmtElapsed(sec) {
  const h = Math.floor(sec/3600), m = Math.floor((sec%3600)/60), s = Math.floor(sec%60);
  return (h ? h+'h ' : '') + (m ? m+'m ' : '') + s+'s';
}
 
async function poll() {
  try {
    const r = await fetch('/api/state');
    const d = await r.json();
    applyState(d);
  } catch(e) {}
  setTimeout(poll, 1200);
}
 
function applyState(d) {
  // status pill
  const pill = document.getElementById('status-pill');
  pill.className = 'status-pill ' + d.status;
  document.getElementById('status-text').textContent = d.status;
 
  // name
  document.getElementById('torrent-name').textContent = d.torrent_name || 'No torrent loaded';
 
  // percent
  const pct = d.progress.percent || 0;
  document.getElementById('pct-label').textContent = pct.toFixed(1) + '%';
  const fill = document.getElementById('progress-fill');
  fill.style.width = pct + '%';
  fill.className = 'progress-bar-fill' + (d.status === 'seeding' || d.status === 'done' ? ' done' : '');
 
  // stats
  document.getElementById('stat-speed').textContent = fmtSpeed(d.progress.speed_bps || 0);
  document.getElementById('stat-peers').textContent = d.peers || '0';
  document.getElementById('stat-pieces').textContent =
    (d.progress.pieces_done || 0) + ' / ' + (d.progress.num_pieces || 0);
  document.getElementById('stat-size').textContent = fmtBytes(d.total_size || 0);
  if (d.start_time) {
    const now = d.end_time || (Date.now()/1000);
    document.getElementById('stat-elapsed').textContent = fmtElapsed(now - d.start_time);
  }
 
  // piece grid
  const np = d.progress.num_pieces || 0;
  if (np !== _pieceCount) {
    _pieceCount = np;
    rebuildPieceGrid(np);
  }
  if (np > 0 && d.piece_status) {
    const cells = document.querySelectorAll('.piece-cell');
    const seeding = d.status === 'seeding' || d.status === 'done';
    d.piece_status.forEach((v, i) => {
      if (cells[i]) {
        cells[i].className = 'piece-cell' + (v ? (seeding ? ' seeding' : ' done') : '');
      }
    });
  }
 
  // file list
  const files = d.progress.files || [];
  const section = document.getElementById('file-list-section');
  if (files.length > 0) {
    section.style.display = '';
    const rows = document.getElementById('file-rows');
    rows.innerHTML = files.map(f => `
      <div class="file-row">
        <div class="file-name" title="${f.path}">${f.path}</div>
        <div class="file-pct">${f.percent}%</div>
        <div class="file-bar-track"><div class="file-bar-fill" style="width:${f.percent}%"></div></div>
      </div>
    `).join('');
  } else {
    section.style.display = 'none';
  }
 
  // log
  if (d.log && d.log.length !== _logLen) {
    _logLen = d.log.length;
    const el = document.getElementById('log-console');
    el.innerHTML = d.log.map(l => {
      const cls = l.includes('ERROR') ? 'err' : l.includes('✓') ? 'ok' : 'info';
      return `<span class="ln ${cls}">${escHtml(l)}</span>`;
    }).join('\n');
    el.scrollTop = el.scrollHeight;
  }
}
 
function rebuildPieceGrid(n) {
  const grid = document.getElementById('piece-grid');
  grid.innerHTML = '';
  for (let i = 0; i < n; i++) {
    const c = document.createElement('div');
    c.className = 'piece-cell';
    grid.appendChild(c);
  }
}
 
function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
 
async function launchDownload(e) {
  e.preventDefault();
  const path = document.getElementById('torrent-path').value.trim();
  const dir  = document.getElementById('output-dir').value.trim() || './';
  if (!path) return alert('Enter a torrent file path');
  await fetch('/api/start', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ torrent_path: path, output_dir: dir }),
  });
}
 
async function stopDownload() {
  await fetch('/api/stop', { method: 'POST' });
}
 
poll();
</script>
</body>
</html>
"""
 
# ── Flask routes ──────────────────────────────────────────────────────────────
 
@app.route('/')
def index():
    return render_template_string(HTML)
 
 
@app.route('/api/state')
def api_state():
    with _state_lock:
        # include piece_status for the piece-map visualiser
        pm = _client.piece_manager if _client else None
        piece_status = list(pm.piece_status) if pm else []
        data = dict(_state)
    data['piece_status'] = piece_status
    return jsonify(data)
 
 
@app.route('/api/start', methods=['POST'])
def api_start():
    global _client
    body = request.get_json(force=True)
    torrent_path = body.get('torrent_path', '').strip()
    output_dir = body.get('output_dir', '.').strip() or '.'
 
    if not torrent_path:
        return jsonify({'error': 'torrent_path required'}), 400
 
    with _state_lock:
        if _state['status'] in ('downloading', 'loading'):
            return jsonify({'error': 'already running'}), 409
 
    threading.Thread(
        target=_run_client,
        args=(torrent_path, output_dir),
        daemon=True,
    ).start()
    return jsonify({'ok': True})
 
 
@app.route('/api/stop', methods=['POST'])
def api_stop():
    global _client
    if _client:
        try:
            _client.cleanup()
        except Exception:
            pass
        _client = None
    with _state_lock:
        _state['status'] = 'idle'
    _log("Stopped by user.")
    return jsonify({'ok': True})
 
 
# ── main ──────────────────────────────────────────────────────────────────────
 
if __name__ == '__main__':
    # Optional: auto-start if torrent path passed as CLI arg
    if len(sys.argv) >= 2:
        torrent_arg = sys.argv[1]
        output_arg = sys.argv[2] if len(sys.argv) >= 3 else '.'
        threading.Thread(
            target=_run_client,
            args=(torrent_arg, output_arg),
            daemon=True,
        ).start()
 
    print("Dashboard →  http://localhost:8080")
    app.run(host='0.0.0.0', port=8080, debug=False, use_reloader=False)