#!/usr/bin/env python3
"""Show HN: Kage – Shadow any website to a single binary for offline viewing — Web Dashboard
Source: [HN] https://github.com/tamnd/kage
"""

from flask import Flask, render_template_string, jsonify
import json, os, time, random

app = Flask(__name__)

DASHBOARD_HTML = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Show HN: Kage – Shadow any website to a single binary for offline viewing</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0a14;color:#ccc;font-family:monospace;padding:20px}
h1{color:#0c8;margin-bottom:10px;font-size:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin:15px 0}
.card{background:#111;border:1px solid #222;padding:12px;border-radius:4px}
.card .v{font-size:24px;font-weight:bold;color:#0cc}
.card .l{font-size:10px;color:#666;margin-top:4px}
table{width:100%;border-collapse:collapse;font-size:11px}
th,td{padding:6px 8px;text-align:left;border-bottom:1px solid #1a1a2e}
th{color:#0c8}
tr:hover{background:#111122}
button{background:#0c8;border:none;color:#000;padding:8px 16px;cursor:pointer;font-family:monospace;font-weight:bold;margin:5px}
button:hover{background:#0fa}
#status{color:#0c8;font-size:10px;margin-left:10px}
</style></head><body>
<h1>📊 Show HN: Kage – Shadow any website to a single binary for offline viewing</h1>
<div class="grid">
<div class="card"><div class="v" id="metric1">--</div><div class="l">Items</div></div>
<div class="card"><div class="v" id="metric2">--</div><div class="l">Active</div></div>
<div class="card"><div class="v" id="metric3">--</div><div class="l">Uptime</div></div>
</div>
<table><thead><tr><th>ID</th><th>Name</th><th>Status</th><th>Value</th></tr></thead><tbody id="rows"></tbody></table>
<button onclick="refresh()">🔄 Refresh</button><span id="status"></span>
<script>
async function refresh(){
  document.getElementById('status').textContent='loading...';
  let r=await fetch('/api/data');
  let d=await r.json();
  document.getElementById('metric1').textContent=d.items.length;
  document.getElementById('metric2').textContent=d.active;
  document.getElementById('metric3').textContent=d.uptime+'s';
  document.getElementById('rows').innerHTML=d.items.map((i,n)=>`<tr><td>${i.id}</td><td>${i.name}</td><td style="color:${i.status==='ok'?'#0c8':'#c33'}">${i.status}</td><td>${i.value}</td></tr>`).join('');
  document.getElementById('status').textContent='✓ refreshed';
}
refresh();
setInterval(refresh,5000);
</script></body></html>"""

@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML)

@app.route("/api/data")
def data():
    items = [{"id": i, "name": f"Node {i}", "status": random.choice(["ok","ok","ok","warn"]), 
              "value": round(random.uniform(10,99),1)} for i in range(1,8)]
    return jsonify({"items": items, "active": sum(1 for i in items if i["status"]=="ok"),
                     "uptime": int(time.time()-START)})

START = time.time()

if __name__ == "__main__":
    print(f"📊 {{title}} dashboard on :8083")
    app.run(host="0.0.0.0", port=8083)
