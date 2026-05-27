"""
interface.py  Single entry point for the P2P BitTorrent client.

Just run:
    python interface.py

Then open http://localhost:8080
- The tracker starts automatically in the background
- Enter a torrent path + output dir in the UI and click Start
- Everything else is handled for you
"""

import hashlib
import os
import sys
import threading
import time

from flask import Flask, jsonify, render_template_string, request

# ── import sibling modules ────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from Peer import BitTorrentClient
from Tracker import TrackerServer

# ── config ────────────────────────────────────────────────────────────────────
TRACKER_HOST = '127.0.0.1'
TRACKER_PORT = 3000
UI_PORT      = 8080

# ── start tracker in background thread ───────────────────────────────────────
_tracker = TrackerServer(host='0.0.0.0', port=TRACKER_PORT)

def _start_tracker():
    _tracker.start()   # blocks on serve_forever()

threading.Thread(target=_start_tracker, daemon=True, name='tracker').start()
time.sleep(0.8)   # give tracker a moment to bind
print(f"✓ Tracker running on http://{TRACKER_HOST}:{TRACKER_PORT}/announce")

# ── shared UI state ───────────────────────────────────────────────────────────
_state = {
    'status':       'idle',
    'torrent_name': '',
    'is_multi_file': False,
    'total_size':   0,
    'progress': {
        'pieces_done': 0,
        'num_pieces':  0,
        'percent':     0.0,
        'speed_bps':   0.0,
        'files':       [],
    },
    'peers':      0,
    'error':      '',
    'log':        [],
    'start_time': None,
    'end_time':   None,
}
_state_lock = threading.Lock()
_client: BitTorrentClient = None


def _log(msg: str):
    ts = time.strftime('%H:%M:%S')
    line = f'[{ts}] {msg}'
    print(line)
    with _state_lock:
        _state['log'].append(line)
        if len(_state['log']) > 300:
            _state['log'].pop(0)


def _progress_callback(info: dict):
    global _client
    with _state_lock:
        _state['progress'] = info
        if _client:
            with _client.peer_lock:
                _state['peers'] = len(_client.peers)
        if info['percent'] >= 100:
            _state['status'] = 'seeding'
            _state['end_time'] = time.time()
    _log(f"Progress {info['percent']:.1f}%  "
         f"({info['pieces_done']}/{info['num_pieces']} pieces)  "
         f"{info['speed_bps']/1024:.1f} KB/s")


def _run_client(torrent_path: str, output_dir: str):
    global _client
    try:
        with _state_lock:
            _state['status'] = 'loading'
            _state['error']  = ''

        _log(f"Loading torrent: {torrent_path}")

        _client = BitTorrentClient(
            torrent_path,
            output_dir=output_dir,
            progress_callback=_progress_callback,
        )

        from Torrent import Torrent
        t = Torrent(torrent_path)
        with _state_lock:
            _state['torrent_name']  = t.file_name()
            _state['is_multi_file'] = t.is_multi_file()
            _state['total_size']    = t.file_length()
            _state['status']        = 'downloading'
            _state['start_time']    = time.time()

        _log(f"Name: {t.file_name()}  |  {t.file_length()} bytes  |  "
             f"{'multi' if t.is_multi_file() else 'single'}-file  |  "
             f"{t.num_pieces()} piece(s)")
        for f in t.files():
            _log(f"  → {f['path']}  ({f['length']} bytes)")

        _client.start()   # blocks until seeding or error

        with _state_lock:
            if _state['status'] not in ('seeding', 'error'):
                _state['status']   = 'done'
                _state['end_time'] = time.time()
        _log("Client finished.")

    except Exception as e:
        import traceback
        _log(f"ERROR: {e}\n{traceback.format_exc()}")
        with _state_lock:
            _state['status'] = 'error'
            _state['error']  = str(e)


# ── Flask UI app ──────────────────────────────────────────────────────────────
app = Flask(__name__)

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
    --bg:#0c0e14; --surface:#13161f; --border:#1e2433;
    --accent:#00e5ff; --accent2:#7b2fff; --green:#00ff94;
    --warn:#ffb300; --danger:#ff3d5a; --text:#d4daf0; --muted:#4a516a;
    --radius:8px;
  }
  *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--text);font-family:'JetBrains Mono',monospace;font-size:13px;min-height:100vh}
  .shell{display:grid;grid-template-rows:56px 1fr;grid-template-columns:270px 1fr;grid-template-areas:"header header" "sidebar main";min-height:100vh}

  /* header */
  header{grid-area:header;background:var(--surface);border-bottom:1px solid var(--border);display:flex;align-items:center;padding:0 24px;gap:14px}
  .logo{font-family:'Syne',sans-serif;font-weight:800;font-size:18px;color:var(--accent)}
  .logo span{color:var(--accent2)}
  .tracker-badge{font-size:10px;color:var(--green);border:1px solid var(--green);border-radius:20px;padding:2px 9px;letter-spacing:.6px}
  .status-pill{display:inline-flex;align-items:center;gap:6px;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.8px;padding:3px 10px;border-radius:20px;border:1px solid}
  .status-pill.idle{color:var(--muted);border-color:var(--muted)}
  .status-pill.loading{color:var(--warn);border-color:var(--warn)}
  .status-pill.downloading{color:var(--accent);border-color:var(--accent)}
  .status-pill.seeding,.status-pill.done{color:var(--green);border-color:var(--green)}
  .status-pill.error{color:var(--danger);border-color:var(--danger)}
  .dot{width:7px;height:7px;border-radius:50%;background:currentColor;animation:pulse 1.4s ease-in-out infinite}
  .status-pill.idle .dot,.status-pill.done .dot{animation:none}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}

  /* sidebar */
  aside{grid-area:sidebar;background:var(--surface);border-right:1px solid var(--border);padding:20px 16px;display:flex;flex-direction:column;gap:16px}
  .card{background:var(--bg);border:1px solid var(--border);border-radius:var(--radius);padding:16px}
  .card-title{font-family:'Syne',sans-serif;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;color:var(--muted);margin-bottom:12px}
  .metric{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px}
  .metric-label{color:var(--muted);font-size:11px}
  .metric-value{font-weight:600;color:var(--text);font-size:13px}
  .metric-value.accent{color:var(--accent)}

  /* form */
  .launch{display:flex;flex-direction:column;gap:10px}
  label{font-size:11px;color:var(--muted);margin-bottom:3px;display:block}
  input[type=text]{width:100%;background:var(--surface);border:1px solid var(--border);border-radius:4px;color:var(--text);font-family:inherit;font-size:12px;padding:7px 10px;outline:none;transition:border-color .15s}
  input[type=text]:focus{border-color:var(--accent)}
  .btn{width:100%;padding:9px;background:transparent;border:1px solid var(--accent);border-radius:4px;color:var(--accent);font-family:'Syne',sans-serif;font-weight:700;font-size:12px;letter-spacing:.5px;cursor:pointer;transition:background .15s,color .15s}
  .btn:hover{background:var(--accent);color:var(--bg)}
  .btn.danger{border-color:var(--danger);color:var(--danger)}
  .btn.danger:hover{background:var(--danger);color:#fff}

  /* tracker info */
  .tracker-info{font-size:10px;color:var(--muted);line-height:1.7;word-break:break-all}
  .tracker-info .val{color:var(--text)}

  /* main */
  main{grid-area:main;padding:24px;display:flex;flex-direction:column;gap:20px;overflow-y:auto}
  .big-progress-wrap{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:20px 24px}
  .big-progress-header{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:14px}
  .torrent-name{font-family:'Syne',sans-serif;font-size:15px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:60%}
  .pct-label{font-family:'Syne',sans-serif;font-size:28px;font-weight:800;color:var(--accent)}
  .progress-bar-track{height:10px;background:var(--border);border-radius:99px;overflow:hidden}
  .progress-bar-fill{height:100%;border-radius:99px;background:linear-gradient(90deg,var(--accent2),var(--accent));transition:width .6s ease}
  .progress-bar-fill.done{background:linear-gradient(90deg,var(--green),#00c978)}

  /* piece grid */
  .piece-section{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:16px 20px}
  .piece-section-title{font-family:'Syne',sans-serif;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;color:var(--muted);margin-bottom:12px}
  #piece-grid{display:flex;flex-wrap:wrap;gap:2px}
  .piece-cell{width:8px;height:8px;border-radius:2px;background:var(--border);transition:background .2s}
  .piece-cell.done{background:var(--accent)}
  .piece-cell.seeding{background:var(--green)}

  /* file list */
  .file-list{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:16px 20px}
  .file-list-title{font-family:'Syne',sans-serif;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;color:var(--muted);margin-bottom:14px}
  .file-row{display:grid;grid-template-columns:1fr auto;gap:10px;align-items:center;margin-bottom:12px}
  .file-name{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:12px}
  .file-pct{color:var(--accent);font-size:12px;font-weight:600;min-width:44px;text-align:right}
  .file-bar-track{grid-column:1/-1;height:4px;background:var(--border);border-radius:99px;overflow:hidden;margin-top:-6px}
  .file-bar-fill{height:100%;border-radius:99px;background:var(--accent2);transition:width .6s ease}

  /* log */
  .log-section-title{font-family:'Syne',sans-serif;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;color:var(--muted);margin-bottom:8px}
  .log-console{background:#080a10;border:1px solid var(--border);border-radius:var(--radius);padding:14px 16px;font-size:11px;line-height:1.6;height:220px;overflow-y:auto;color:#637094}
  .ln{display:block}
  .ln.ok{color:var(--green)}
  .ln.err{color:var(--danger)}
  .ln.warn{color:var(--warn)}
</style>
</head>
<body>
<div class="shell">

  <header>
    <div class="logo">P2P<span>.</span>client</div>
    <div class="tracker-badge">● tracker active</div>
    <div id="status-pill" class="status-pill idle"><div class="dot"></div><span id="status-text">idle</span></div>
  </header>

  <aside>
    <div class="card">
      <div class="card-title">Download</div>
      <div class="launch">
        <div>
          <label>Torrent file path</label>
          <input type="text" id="torrent-path" placeholder="./file.torrent">
        </div>
        <div>
          <label>Save to directory</label>
          <input type="text" id="output-dir" placeholder="./downloads" value="./downloads">
        </div>
        <button class="btn" onclick="launchDownload()">▶ Start Download</button>
      </div>
    </div>

    <div class="card">
      <div class="card-title">Stats</div>
      <div class="metric"><span class="metric-label">Speed</span><span id="stat-speed" class="metric-value accent">—</span></div>
      <div class="metric"><span class="metric-label">Peers</span><span id="stat-peers" class="metric-value">—</span></div>
      <div class="metric"><span class="metric-label">Pieces</span><span id="stat-pieces" class="metric-value">—</span></div>
      <div class="metric"><span class="metric-label">Size</span><span id="stat-size" class="metric-value">—</span></div>
      <div class="metric"><span class="metric-label">Elapsed</span><span id="stat-elapsed" class="metric-value">—</span></div>
    </div>

    <div class="card">
      <div class="card-title">Tracker</div>
      <div class="tracker-info">
        <div>URL <span class="val">localhost:3000</span></div>
        <div>Peers <span class="val" id="tracker-peers">—</span></div>
      </div>
    </div>

    <div style="margin-top:auto">
      <button class="btn danger" onclick="stopDownload()">■ Stop</button>
    </div>
  </aside>

  <main>
    <div class="big-progress-wrap">
      <div class="big-progress-header">
        <div id="torrent-name" class="torrent-name">No torrent loaded</div>
        <div id="pct-label" class="pct-label">0%</div>
      </div>
      <div class="progress-bar-track">
        <div id="progress-fill" class="progress-bar-fill" style="width:0%"></div>
      </div>
    </div>

    <div class="piece-section">
      <div class="piece-section-title">Piece map</div>
      <div id="piece-grid"></div>
    </div>

    <div class="file-list" id="file-list-section" style="display:none">
      <div class="file-list-title">Files</div>
      <div id="file-rows"></div>
    </div>

    <div>
      <div class="log-section-title">Activity log</div>
      <div id="log-console" class="log-console"></div>
    </div>
  </main>
</div>

<script>
let _pieceCount=0, _logLen=0;

const fmt={
  bytes(b){if(b<1024)return b+' B';if(b<1<<20)return(b/1024).toFixed(1)+' KB';if(b<1<<30)return(b/1<<20).toFixed(1)+' MB';return(b/1<<30).toFixed(2)+' GB'},
  speed(b){if(b<1024)return b.toFixed(0)+' B/s';if(b<1<<20)return(b/1024).toFixed(1)+' KB/s';return(b/1<<20).toFixed(2)+' MB/s'},
  time(s){const h=Math.floor(s/3600),m=Math.floor(s%3600/60),sec=Math.floor(s%60);return(h?h+'h ':'')+( m?m+'m ':'')+sec+'s'},
};

async function poll(){
  try{
    const d=await(await fetch('/api/state')).json();
    applyState(d);
  }catch(e){}
  setTimeout(poll,1200);
}

async function pollTracker(){
  try{
    const d=await(await fetch('/api/tracker_peers')).json();
    document.getElementById('tracker-peers').textContent=d.count??'—';
  }catch(e){}
  setTimeout(pollTracker,5000);
}

function applyState(d){
  const pill=document.getElementById('status-pill');
  pill.className='status-pill '+d.status;
  document.getElementById('status-text').textContent=d.status;
  document.getElementById('torrent-name').textContent=d.torrent_name||'No torrent loaded';

  const pct=d.progress.percent||0;
  document.getElementById('pct-label').textContent=pct.toFixed(1)+'%';
  const fill=document.getElementById('progress-fill');
  fill.style.width=pct+'%';
  fill.className='progress-bar-fill'+(d.status==='seeding'||d.status==='done'?' done':'');

  document.getElementById('stat-speed').textContent=fmt.speed(d.progress.speed_bps||0);
  document.getElementById('stat-peers').textContent=d.peers||'0';
  document.getElementById('stat-pieces').textContent=(d.progress.pieces_done||0)+' / '+(d.progress.num_pieces||0);
  document.getElementById('stat-size').textContent=fmt.bytes(d.total_size||0);
  if(d.start_time){
    document.getElementById('stat-elapsed').textContent=fmt.time((d.end_time||(Date.now()/1000))-d.start_time);
  }

  const np=d.progress.num_pieces||0;
  if(np!==_pieceCount){_pieceCount=np;rebuildGrid(np);}
  if(np>0&&d.piece_status){
    const cells=document.querySelectorAll('.piece-cell');
    const seed=d.status==='seeding'||d.status==='done';
    d.piece_status.forEach((v,i)=>{if(cells[i])cells[i].className='piece-cell'+(v?(seed?' seeding':' done'):'');});
  }

  const files=d.progress.files||[];
  const sec=document.getElementById('file-list-section');
  if(files.length>0){
    sec.style.display='';
    document.getElementById('file-rows').innerHTML=files.map(f=>`
      <div class="file-row">
        <div class="file-name" title="${f.path}">${f.path}</div>
        <div class="file-pct">${f.percent}%</div>
        <div class="file-bar-track"><div class="file-bar-fill" style="width:${f.percent}%"></div></div>
      </div>`).join('');
  }else{sec.style.display='none';}

  if(d.log&&d.log.length!==_logLen){
    _logLen=d.log.length;
    const el=document.getElementById('log-console');
    el.innerHTML=d.log.map(l=>{
      const c=l.includes('ERROR')?'err':l.includes('✓')||l.includes('complete')||l.includes('Seeding')?'ok':l.includes('Tracker')||l.includes('tracker')?'warn':'';
      return`<span class="ln ${c}">${esc(l)}</span>`;
    }).join('\n');
    el.scrollTop=el.scrollHeight;
  }
}

function rebuildGrid(n){
  const g=document.getElementById('piece-grid');
  g.innerHTML='';
  for(let i=0;i<n;i++){const c=document.createElement('div');c.className='piece-cell';g.appendChild(c);}
}
function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}

async function launchDownload(){
  const path=document.getElementById('torrent-path').value.trim();
  const dir=document.getElementById('output-dir').value.trim()||'./downloads';
  if(!path){alert('Enter a torrent file path');return;}
  const r=await fetch('/api/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({torrent_path:path,output_dir:dir})});
  const d=await r.json();
  if(d.error)alert('Error: '+d.error);
}

async function stopDownload(){
  await fetch('/api/stop',{method:'POST'});
}

poll();
pollTracker();
</script>
</body>
</html>
"""


@app.route('/')
def index():
    return render_template_string(HTML)


@app.route('/api/state')
def api_state():
    with _state_lock:
        pm = _client.piece_manager if _client else None
        piece_status = list(pm.piece_status) if pm else []
        data = dict(_state)
    data['piece_status'] = piece_status
    return jsonify(data)


@app.route('/api/tracker_peers')
def api_tracker_peers():
    """Return how many unique peers the tracker knows about."""
    try:
        import requests as req
        r = req.get(f'http://{TRACKER_HOST}:{TRACKER_PORT}/stats', timeout=2)
        # Tracker returns bencoded or JSON — try to count from raw response
        # Fall back to counting 'ip' occurrences in bencoded response
        count = r.text.count('"ip"') or r.content.count(b'2:ip')
        return jsonify({'count': count})
    except Exception:
        return jsonify({'count': '?'})


@app.route('/api/start', methods=['POST'])
def api_start():
    global _client
    body = request.get_json(force=True)
    torrent_path = body.get('torrent_path', '').strip()
    output_dir   = body.get('output_dir', './downloads').strip() or './downloads'

    if not torrent_path:
        return jsonify({'error': 'torrent_path required'}), 400
    if not os.path.exists(torrent_path):
        return jsonify({'error': f'File not found: {torrent_path}'}), 400

    with _state_lock:
        if _state['status'] in ('downloading', 'loading'):
            return jsonify({'error': 'Already running — stop first'}), 409

    os.makedirs(output_dir, exist_ok=True)
    threading.Thread(target=_run_client, args=(torrent_path, output_dir),
                     daemon=True).start()
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


# ── entry point ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print(f"Dashboard  →  http://localhost:{UI_PORT}")
    print("Just enter your torrent path in the UI and click Start.")
    app.run(host='0.0.0.0', port=UI_PORT, debug=False, use_reloader=False)