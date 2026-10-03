"""
NOVA SENTINEL - Live monitoring of up to 3 freely configurable number points.

Flow:
  1. Click the "+" button in the web app to add an observation point (max 3).
  2. On the PC, a small single-button toolbar opens ("SELECT NUMBER AREA").
     Click it, then drag a rectangle around the number on screen. ESC cancels
     only that selection and returns to the toolbar.
  3. The new point starts in preview mode (reads live, no alarm) so you can
     check recognition. Set its name, alert type and thresholds in the app.
  4. Press "Start" in the app to arm all points. Alerts can optionally also
     be sent to your phone via a webhook URL (Discord, Slack, ntfy, etc. -
     your choice of messenger, see README).

Installation (Windows):
  1. Install Tesseract OCR: https://github.com/UB-Mannheim/tesseract/wiki
  2. pip install mss pillow pytesseract cryptography
Start: python zahl_warner_app.py
"""
import io
import json
import os
import re
import socket
import ssl
import threading
import time
import tkinter as tk
import urllib.request
import winsound
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import mss
import pytesseract
from PIL import Image, ImageOps, ImageTk

try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE, important for display scaling
except Exception:
    pass  # not Windows, or an older Windows version without this function

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# ---- SETTINGS ----
MAX_PUNKTE = 3
INTERVAL = 1.0
WIEDERHOLUNG = 60
PORT = 8787
ALARM_TON = True
USE_HTTPS = True
# -----------------------
SCHEMA = "https" if USE_HTTPS else "http"

lock = threading.Lock()
state = {
    "punkte": [],          # list of observation points, see neuer_punkt()
    "naechste_id": 1,
    "modus": "auswahl",    # auswahl | vorschau | aktiv | gestoppt
    "pick_requested": False,
    "picking": False,
    "webhook_url": "",
    "telegram_token": "",
    "telegram_chat_id": "",
    "ntfy_topic": "",
}


def neuer_punkt(pid, region):
    return {
        "id": pid, "name": f"Point {pid[1:]}", "region": region,
        "wert": None, "max": None, "typ": "unten",
        "schwelle": 30, "gelb": 70, "rot": 85,
        "history": [], "png": b"", "max_auto_pending": True,
    }


def ip_lokal():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def sicherstelle_zertifikat():
    cert_pfad = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nova_cert.pem")
    key_pfad = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nova_key.pem")
    if os.path.exists(cert_pfad) and os.path.exists(key_pfad):
        return cert_pfad, key_pfad

    import datetime
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    schluessel = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "NOVA Sentinel")])
    jetzt = datetime.datetime.utcnow()
    zertifikat = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(schluessel.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(jetzt)
        .not_valid_after(jetzt + datetime.timedelta(days=3650))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.IPAddress(__import__("ipaddress").ip_address(ip_lokal())),
            ]),
            critical=False,
        )
        .sign(schluessel, hashes.SHA256())
    )
    with open(cert_pfad, "wb") as f:
        f.write(zertifikat.public_bytes(serialization.Encoding.PEM))
    with open(key_pfad, "wb") as f:
        f.write(schluessel.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ))
    return cert_pfad, key_pfad


def sende_webhook(url, text):
    if not url:
        return

    def lauf():
        try:
            data = json.dumps({"content": text, "text": text, "message": text}).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            print("Webhook error:", e)

    threading.Thread(target=lauf, daemon=True).start()


def sende_ntfy(topic, text):
    if not topic:
        return

    def lauf():
        try:
            url = f"https://ntfy.sh/{topic}"
            req = urllib.request.Request(
                url, data=text.encode("utf-8"),
                headers={"Title": "NOVA Sentinel", "Priority": "urgent", "Tags": "warning"},
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            print("ntfy error:", e)

    threading.Thread(target=lauf, daemon=True).start()


def sende_telegram(token, chat_id, text):
    if not token or not chat_id:
        return

    def lauf():
        try:
            from urllib.parse import urlencode
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            data = urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")
            req = urllib.request.Request(url, data=data)
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            print("Telegram error:", e)

    threading.Thread(target=lauf, daemon=True).start()


HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NOVA Sentinel</title><style>
:root{color-scheme:dark}
body{margin:0;background:#0a1a33;color:#eee;font-family:system-ui,sans-serif}
.win{max-width:420px;margin:14px auto;border:1px solid #1f4e8c;border-radius:10px;
 overflow:hidden;box-shadow:0 8px 30px #0008}
.bar{background:linear-gradient(90deg,#0d47a1,#08306b);padding:8px 12px;
 font-weight:700;display:flex;align-items:center;gap:8px;
 letter-spacing:2px;font-size:13px;color:#cfe3ff}
.body{padding:16px}
.row{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:10px}
label{font-size:13px;color:#9ec2ee}
input[type=number],input[type=text],select{background:#0f2a4d;border:1px solid #2f6fbf;color:#fff;
 border-radius:6px;padding:6px;font-size:13px}
input[type=number]{width:64px}
input[type=text]{width:100%}
button{background:#1565c0;color:#fff;border:none;border-radius:6px;padding:7px 14px;
 font-size:13px;cursor:pointer}
button:active{background:#0d47a1}
button:disabled{opacity:.4;cursor:not-allowed}
.status{text-align:center;font-size:13px;font-weight:700;padding:8px;border-radius:8px;margin-bottom:14px}
.status.auswahl{background:#10306b;color:#8ab4f8}
.status.vorschau{background:#4a3b1a;color:#ffc23d}
.status.aktiv{background:#173a24;color:#3ddc73}
.status.gestoppt{background:#3a1a1a;color:#ff8a8a}
.dot{width:9px;height:9px;border-radius:50%;background:#666}
.dot.on{background:#5ad16a}
.footer{text-align:center;font-size:11px;color:#4a76ac;margin-top:16px;
 padding-top:10px;border-top:1px solid #16305c;letter-spacing:.5px}
.footer b{color:#7fb3ff}
.card{border:1px solid #2f6fbf;border-radius:10px;padding:12px;margin-bottom:12px;
 background:#0f2341;transition:box-shadow .4s,border-color .4s}
.card.ok{border-color:#3ddc73;box-shadow:0 0 16px 1px #3ddc7366}
.card.warn{border-color:#ffc23d;box-shadow:0 0 16px 1px #ffc23d66}
.card.low{border-color:#ff3b3b;animation:glow 1s infinite alternate}
@keyframes glow{from{box-shadow:0 0 10px 1px #ff3b3b55}to{box-shadow:0 0 30px 6px #ff3b3b}}
.card-top{display:flex;align-items:center;gap:10px;margin-bottom:8px}
.thumb{position:relative;width:52px;height:52px;flex-shrink:0}
.thumb img{width:100%;height:100%;object-fit:cover;border-radius:8px;background:#000}
.thumb .num{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
 font-size:13px;font-weight:800;color:#fff;text-shadow:0 0 4px #000}
.card-name{font-weight:700;font-size:14px;flex:1}
.card-name input{font-weight:700;font-size:14px;background:transparent;border:none;color:#fff;width:100%}
.card-val{font-size:26px;font-weight:800;color:#ffd76a}
.ptrack{background:#081a33;border-radius:8px;height:12px;overflow:hidden;margin:6px 0}
.pfill{height:100%;border-radius:8px;transition:.4s}
.psub{font-size:11px;color:#8ab4f8;display:flex;justify-content:space-between}
.settings-row{display:flex;gap:6px;align-items:center;margin-top:8px;flex-wrap:wrap}
.settings-row label{font-size:11px}
.settings-row input{width:54px}
.remove-btn{background:#3a1a1a;color:#ff8a8a;padding:4px 8px;font-size:11px}
.add-btn{width:100%;background:#1f6b3f;border:1px solid #3ddc73;padding:10px;font-size:14px;margin-bottom:12px}
.collapse-toggle{display:flex;justify-content:center;margin-top:8px}
.collapse-toggle button{background:#0f2a4d;border:1px solid #2f6fbf;padding:4px 16px;border-radius:20px}
.advanced{overflow:hidden;max-height:0;transition:max-height .3s ease}
.advanced.open{max-height:300px}
.hint{font-size:11px;color:#7fa8d9;margin:2px 0 10px}
</style></head><body>
<div class="win" id="win">
<div class="bar"><span id="dot" class="dot"></span> <span>NOVA SENTINEL</span></div>
<div class="body">
 <div class="status" id="statusbox">Initializing ...</div>
 <div id="punkte-liste"></div>
 <button class="add-btn" id="addBtn" onclick="addPunkt()">&#10133; Add observation point</button>
 <div class="log" id="log" style="font-size:12px;color:#7fa8d9;margin-bottom:4px">Waiting for data ...</div>
 <div class="ip" id="ip" style="font-size:11px;color:#5a86b8"></div>

 <div class="advanced" id="advanced">
  <div class="row" style="margin-top:14px">
   <label>Notification Webhook URL</label>
  </div>
  <div style="display:flex;gap:8px;margin-bottom:4px">
   <input type="text" id="webhook" placeholder="https://discord.com/api/webhooks/...">
   <button onclick="setWebhook()">OK</button>
  </div>
  <div class="hint">Works with Discord/Slack-style webhooks out of the box.
   Leave empty to disable phone notifications.</div>

  <div class="row" style="margin-top:4px">
   <label>Telegram Bot Token</label>
  </div>
  <div style="display:flex;gap:8px;margin-bottom:4px">
   <input type="text" id="tgtoken" placeholder="123456:ABC-DEF...">
  </div>
  <div class="row">
   <label>Telegram Chat ID</label>
  </div>
  <div style="display:flex;gap:8px;margin-bottom:4px">
   <input type="text" id="tgchat" placeholder="e.g. 123456789">
   <button onclick="setTelegram()">OK</button>
  </div>
  <div class="hint">
   1) Message <b>@BotFather</b> on Telegram, send <b>/newbot</b>, copy the token.<br>
   2) Message your new bot once (anything).<br>
   3) Open <b>https://api.telegram.org/bot&lt;TOKEN&gt;/getUpdates</b> in a browser
      to find your Chat ID in the reply.
  </div>
  <div class="row" style="margin-top:4px">
   <label>ntfy.sh Topic</label>
  </div>
  <div style="display:flex;gap:8px;margin-bottom:4px">
   <input type="text" id="ntfytopic" placeholder="e.g. nova-sentinel-x7k2q9">
   <button onclick="setNtfy()">OK</button>
  </div>
  <div class="hint">
   1) Install the free <b>ntfy</b> app (iOS/Android) or use ntfy.sh in a browser.<br>
   2) Subscribe to a topic name of your choice — make it long and random
      so strangers can't guess it (anyone who knows the topic can read it).<br>
   3) Enter the same topic name here. No account needed.
  </div>

  <div class="row">
   <button onclick="testNotify()" style="flex:1">Send Test Notification</button>
  </div>

  <div class="row" style="margin-top:8px">
   <button id="btnStart" onclick="steuere('start')" style="flex:1">Start</button>
   <button onclick="steuere('stop')" style="flex:1">Stop</button>
  </div>
 </div>
 <div class="collapse-toggle"><button onclick="toggleAdvanced()" id="toggleBtn">&#9650;</button></div>

 <div class="footer">by <b>Grigorios Gkisios</b> ~ Hobby Developer</div>
</div></div>
<script>
let advOpen=false, webhookBearbeitet=false, tgBearbeitet=false, ntfyBearbeitet=false, bekannteIds=null;
function toggleAdvanced(){
 advOpen=!advOpen;
 document.getElementById("advanced").className="advanced"+(advOpen?" open":"");
 document.getElementById("toggleBtn").innerHTML = advOpen ? "&#9660;" : "&#9650;";
}
function fmtZeit(min){
 if(min===null)return "unknown";
 if(min<1)return "< 1 min";
 if(min<60)return min.toFixed(0)+" min";
 return (min/60).toFixed(1)+" h";
}
function kartenHTML(p){
 return `
  <div class="card-top">
   <div class="thumb"><img id="img-${p.id}" src="/img/${p.id}.png?t=0" alt="">
    <div class="num" id="num-${p.id}">?</div></div>
   <div class="card-name"><input type="text" id="name-${p.id}" value="${p.name}"
     onchange="setFeld('${p.id}','name',this.value)"></div>
   <button class="remove-btn" onclick="entfernen('${p.id}')">&#10005;</button>
  </div>
  <div class="card-val" id="val-${p.id}">-</div>
  <div class="ptrack"><div class="pfill" id="fill-${p.id}" style="width:0%"></div></div>
  <div class="psub"><span id="sub-${p.id}"></span><span id="rate-${p.id}"></span></div>
  <div class="settings-row">
   <label>Alert type</label>
   <select id="typ-${p.id}" onchange="setFeld('${p.id}','typ',this.value)">
    <option value="unten" ${p.typ==='unten'?'selected':''}>Warn when LOW</option>
    <option value="oben" ${p.typ==='oben'?'selected':''}>Warn when HIGH (%)</option>
   </select>
  </div>
  <div class="settings-row" id="felder-unten-${p.id}" style="${p.typ!=='unten'?'display:none':''}">
   <label>Warn at</label><input type="number" id="schwelle-${p.id}" value="${p.schwelle}"
     onchange="setFeld('${p.id}','schwelle',this.value)">
   <label>Max</label><input type="number" id="max-${p.id}" value="${p.max===null?'':p.max}"
     onchange="setFeld('${p.id}','max',this.value)">
  </div>
  <div class="settings-row" id="felder-oben-${p.id}" style="${p.typ!=='oben'?'display:none':''}">
   <label>Yellow %</label><input type="number" id="gelb-${p.id}" value="${p.gelb}"
     onchange="setFeld('${p.id}','gelb',this.value)">
   <label>Red %</label><input type="number" id="rot-${p.id}" value="${p.rot}"
     onchange="setFeld('${p.id}','rot',this.value)">
   <label>Max</label><input type="number" id="maxo-${p.id}" value="${p.max===null?'':p.max}"
     onchange="setFeld('${p.id}','max',this.value)">
  </div>`;
}
function faerben(card, zustand){
  card.className="card"+(zustand?" "+zustand:"");
}
async function tick(){
 try{
  const d=await (await fetch("/state.json")).json();
  document.getElementById("dot").className="dot"+(d.modus==="aktiv"?" on":"");
  const sbox=document.getElementById("statusbox");
  sbox.className="status "+d.modus;
  const TEXTE={auswahl:"NO POINTS YET - Add one below",vorschau:"PREVIEW - testing recognition (no alarm)",
    aktiv:"ACTIVE - monitoring running",gestoppt:"STOPPED"};
  sbox.textContent = TEXTE[d.modus]||d.modus;
  document.getElementById("btnStart").disabled = (d.punkte.length===0);
  document.getElementById("addBtn").disabled = (d.punkte.length>=3 || d.picking);
  document.getElementById("addBtn").style.opacity = (d.punkte.length>=3)?0.4:1;

  const idsJetzt = d.punkte.map(p=>p.id).join(",");
  if(idsJetzt!==bekannteIds){
    document.getElementById("punkte-liste").innerHTML =
      d.punkte.map(p=>`<div class="card" id="card-${p.id}">${kartenHTML(p)}</div>`).join("");
    bekannteIds=idsJetzt;
  }

  d.punkte.forEach(p=>{
    const card=document.getElementById("card-"+p.id);
    if(!card)return;
    document.getElementById("img-"+p.id).src="/img/"+p.id+".png?"+Date.now();
    document.getElementById("num-"+p.id).textContent = p.wert===null?"?":p.wert;
    document.getElementById("val-"+p.id).textContent = p.wert===null?"-":p.wert;
    document.getElementById("felder-unten-"+p.id).style.display = p.typ==='unten'?'':'none';
    document.getElementById("felder-oben-"+p.id).style.display = p.typ==='oben'?'':'none';

    let proz=0, zustand="";
    if(p.max && p.wert!==null){ proz=Math.min(100,(p.wert/p.max)*100); }
    if(p.typ==='unten'){
      document.getElementById("fill-"+p.id).style.background =
        p.wert!==null && p.wert<=p.schwelle ? "#ff5a5a" : (proz<50?"#f3a83c":"#5ad16a");
      document.getElementById("sub-"+p.id).textContent = (p.wert===null?"-":p.wert)+" / "+(p.max===null?"?":p.max);
      document.getElementById("rate-"+p.id).textContent = p.rate_pro_min
        ? "Time left: ~"+fmtZeit(p.restzeit_min) : "";
      if(d.modus==="aktiv" && p.wert!==null){
        zustand = p.wert<=p.schwelle ? "low" : (proz<50 ? "warn" : "ok");
      }
    } else {
      document.getElementById("fill-"+p.id).style.background =
        proz<p.gelb ? "#5ad16a" : (proz<p.rot ? "#f3a83c" : "#ff5a5a");
      document.getElementById("sub-"+p.id).textContent = (p.wert===null?"-":p.wert)+" / "+(p.max===null?"?":p.max)+" ("+proz.toFixed(0)+"%)";
      document.getElementById("rate-"+p.id).textContent="";
      if(d.modus==="aktiv" && p.wert!==null && p.max){
        zustand = proz>=p.rot ? "low" : (proz>=p.gelb ? "warn" : "ok");
      }
    }
    document.getElementById("fill-"+p.id).style.width=proz.toFixed(1)+"%";
    faerben(card, zustand);
  });

  if(!webhookBearbeitet){document.getElementById("webhook").value=d.webhook_url;}
  if(!tgBearbeitet){
    document.getElementById("tgtoken").value=d.telegram_token;
    document.getElementById("tgchat").value=d.telegram_chat_id;
  }
  if(!ntfyBearbeitet){document.getElementById("ntfytopic").value=d.ntfy_topic;}
  const zeit=new Date(d.updated*1000).toLocaleTimeString();
  document.getElementById("log").textContent = d.picking
    ? "Selection active - please drag a rectangle on the PC ..."
    : (d.punkte.length ? "Last update: "+zeit : "No observation points yet");
  document.getElementById("ip").textContent=d.url;
 }catch(e){document.getElementById("log").textContent="No connection to PC";}
}
async function addPunkt(){ await fetch("/pick_region",{method:"POST"}); }
async function entfernen(id){ await fetch("/remove_point?id="+id,{method:"POST"}); bekannteIds=null; }
async function setFeld(id, feld, wert){
 await fetch("/set_point?id="+id+"&feld="+feld+"&wert="+encodeURIComponent(wert),{method:"POST"});
}
async function setWebhook(){
 webhookBearbeitet=true;
 await fetch("/set_webhook?url="+encodeURIComponent(document.getElementById("webhook").value),{method:"POST"});
}
async function setTelegram(){
 tgBearbeitet=true;
 const token=document.getElementById("tgtoken").value;
 const chat=document.getElementById("tgchat").value;
 await fetch("/set_telegram?token="+encodeURIComponent(token)+"&chat_id="+encodeURIComponent(chat),{method:"POST"});
}
async function setNtfy(){
 ntfyBearbeitet=true;
 await fetch("/set_ntfy?topic="+encodeURIComponent(document.getElementById("ntfytopic").value),{method:"POST"});
}
async function testNotify(){ await fetch("/test_notify",{method:"POST"}); }
async function steuere(aktion){ await fetch("/control?aktion="+aktion,{method:"POST"}); }
tick();setInterval(tick,1000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, ctype, body, code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _rate_und_restzeit(self, punkt):
        jetzt = time.time()
        fenster = [h for h in punkt["history"] if jetzt - h["t"] < 900 and h["nach"] < h["von"]]
        verbrauch = sum(h["von"] - h["nach"] for h in fenster)
        minuten = min(15.0, (jetzt - fenster[0]["t"]) / 60) if fenster else 0
        rate = verbrauch / minuten if minuten > 0.2 else 0.0
        restzeit = (punkt["wert"] / rate) if (rate > 0 and punkt["wert"] is not None) else None
        return rate, restzeit

    def do_GET(self):
        pfad = self.path.split("?")[0]
        if pfad == "/":
            self._send("text/html; charset=utf-8", HTML.encode("utf-8"))
        elif pfad.startswith("/img/") and pfad.endswith(".png"):
            pid = pfad[len("/img/"):-len(".png")]
            with lock:
                punkt = next((p for p in state["punkte"] if p["id"] == pid), None)
                self._send("image/png", punkt["png"] if punkt else b"")
        elif pfad == "/state.json":
            with lock:
                punkte_out = []
                for p in state["punkte"]:
                    rate, restzeit = self._rate_und_restzeit(p)
                    punkte_out.append({
                        "id": p["id"], "name": p["name"], "wert": p["wert"], "max": p["max"],
                        "typ": p["typ"], "schwelle": p["schwelle"], "gelb": p["gelb"], "rot": p["rot"],
                        "rate_pro_min": rate, "restzeit_min": restzeit,
                    })
                daten = {
                    "punkte": punkte_out, "modus": state["modus"], "picking": state["picking"],
                    "webhook_url": state["webhook_url"],
                    "telegram_token": state["telegram_token"],
                    "telegram_chat_id": state["telegram_chat_id"],
                    "ntfy_topic": state["ntfy_topic"],
                    "updated": time.time(),
                    "url": f"{SCHEMA}://{ip_lokal()}:{PORT}/",
                }
            self._send("application/json", json.dumps(daten).encode())
        else:
            self.send_error(404)

    def do_POST(self):
        pfad = self.path.split("?")[0]
        qs = self.path.split("?", 1)[1] if "?" in self.path else ""
        params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
        from urllib.parse import unquote

        if pfad == "/pick_region":
            with lock:
                if len(state["punkte"]) < MAX_PUNKTE:
                    state["pick_requested"] = True
            self._send("application/json", b'{"ok":true}')
        elif pfad == "/remove_point":
            pid = unquote(params.get("id", ""))
            with lock:
                state["punkte"] = [p for p in state["punkte"] if p["id"] != pid]
                if not state["punkte"]:
                    state["modus"] = "auswahl"
            self._send("application/json", b'{"ok":true}')
        elif pfad == "/set_point":
            pid = unquote(params.get("id", ""))
            feld = params.get("feld", "")
            wert = unquote(params.get("wert", ""))
            with lock:
                punkt = next((p for p in state["punkte"] if p["id"] == pid), None)
                if punkt and feld in ("name", "typ", "schwelle", "gelb", "rot", "max"):
                    if feld in ("schwelle", "gelb", "rot", "max"):
                        try:
                            punkt[feld] = int(wert) if wert != "" else None
                        except ValueError:
                            pass
                    else:
                        punkt[feld] = wert
            self._send("application/json", b'{"ok":true}')
        elif pfad == "/set_webhook":
            with lock:
                state["webhook_url"] = unquote(params.get("url", ""))
            self._send("application/json", b'{"ok":true}')
        elif pfad == "/set_telegram":
            with lock:
                state["telegram_token"] = unquote(params.get("token", ""))
                state["telegram_chat_id"] = unquote(params.get("chat_id", ""))
            self._send("application/json", b'{"ok":true}')
        elif pfad == "/set_ntfy":
            with lock:
                state["ntfy_topic"] = unquote(params.get("topic", ""))
            self._send("application/json", b'{"ok":true}')
        elif pfad == "/test_notify":
            with lock:
                webhook_url = state["webhook_url"]
                tg_token = state["telegram_token"]
                tg_chat = state["telegram_chat_id"]
                ntfy_topic = state["ntfy_topic"]
            sende_webhook(webhook_url, "NOVA Sentinel: this is a test notification.")
            sende_telegram(tg_token, tg_chat, "NOVA Sentinel: this is a test notification.")
            sende_ntfy(ntfy_topic, "NOVA Sentinel: this is a test notification.")
            self._send("application/json", b'{"ok":true}')
        elif pfad == "/control":
            with lock:
                if params.get("aktion") == "start" and state["punkte"]:
                    state["modus"] = "aktiv"
                elif params.get("aktion") == "stop":
                    state["modus"] = "gestoppt"
            self._send("application/json", b'{"ok":true}')
        else:
            self.send_error(404)


def lese_zahl(bild):
    """Reads a number from the image. Tries both normal AND inverted (for light
    text on a dark background), each converted to black and white."""
    grau = ImageOps.grayscale(bild)
    grau = grau.resize((grau.width * 6, grau.height * 6), Image.LANCZOS)
    grau = ImageOps.autocontrast(grau, cutoff=2)
    schwarzweiss = grau.point(lambda p: 255 if p > 140 else 0)

    for kandidat in (schwarzweiss, ImageOps.invert(schwarzweiss)):
        text = pytesseract.image_to_string(
            kandidat, config="--psm 7 -c tessedit_char_whitelist=0123456789")
        treffer = re.search(r"\d+", text)
        if treffer:
            return int(treffer.group())
    return None


def fullscreen_auswahl(root):
    """Fullscreen rectangle selection for one number. ESC cancels just this selection."""
    with mss.mss() as sct:
        monitor = sct.monitors[0]
        shot = sct.grab(monitor)
        vollbild = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

    win = tk.Toplevel(root)
    win.attributes("-fullscreen", True)
    win.attributes("-topmost", True)

    bild_tk = ImageTk.PhotoImage(vollbild)
    canvas = tk.Canvas(win, cursor="cross", width=vollbild.width, height=vollbild.height,
                        highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    canvas.create_image(0, 0, image=bild_tk, anchor="nw")
    info = tk.Label(win, text="Drag a rectangle around the number   (ESC = back to menu)",
                     fg="#3ddc73", bg="black", font=("Consolas", 16, "bold"))
    info.place(x=12, y=12)

    start = {}
    rechteck = {"id": None}
    ergebnis = {}

    def runter(e):
        start["x"], start["y"] = e.x, e.y
        if rechteck["id"]:
            canvas.delete(rechteck["id"])

    def ziehen(e):
        if rechteck["id"]:
            canvas.delete(rechteck["id"])
        rechteck["id"] = canvas.create_rectangle(
            start["x"], start["y"], e.x, e.y, outline="#3ddc73", width=3)

    def los(e):
        x0, y0, x1, y1 = start["x"], start["y"], e.x, e.y
        left, top = min(x0, x1), min(y0, y1)
        w, h = abs(x1 - x0), abs(y1 - y0)
        if w > 3 and h > 3:
            ergebnis["region"] = {"left": left, "top": top, "width": w, "height": h}
            win.after(150, win.destroy)

    canvas.bind("<ButtonPress-1>", runter)
    canvas.bind("<B1-Motion>", ziehen)
    canvas.bind("<ButtonRelease-1>", los)
    win.bind("<Escape>", lambda e: win.destroy())
    win.focus_force()
    win.wait_window()
    return ergebnis.get("region")


def einzel_ziel_wahl():
    """Small single-button hover toolbar at the top of the screen."""
    root = tk.Tk()
    root.withdraw()
    ergebnis = {"region": None}

    toolbar = tk.Toplevel(root)
    toolbar.attributes("-topmost", True)
    toolbar.overrideredirect(True)
    sw = toolbar.winfo_screenwidth()
    bar_w, bar_h = 300, 70
    toolbar.geometry(f"{bar_w}x{bar_h}+{(sw - bar_w) // 2}+16")
    toolbar.configure(bg="#08306b", highlightbackground="#1f4e8c", highlightthickness=2)

    def waehlen():
        toolbar.withdraw()
        region = fullscreen_auswahl(root)
        if region:
            ergebnis["region"] = region
            root.quit()
        else:
            toolbar.deiconify()
            toolbar.lift()
            toolbar.attributes("-topmost", True)

    tk.Label(toolbar, text="NOVA SENTINEL", bg="#08306b", fg="#cfe3ff",
             font=("Segoe UI", 9, "bold")).pack(pady=(8, 2))
    tk.Button(toolbar, text="\U0001F3AF SELECT NUMBER AREA", command=waehlen,
              bg="#1565c0", fg="white", activebackground="#0d47a1").pack()

    toolbar.protocol("WM_DELETE_WINDOW", lambda: None)
    root.mainloop()
    root.destroy()
    return ergebnis["region"]


def melodie_gelb():
    for freq, dauer in [(660, 120), (880, 120), (660, 120), (990, 220)]:
        winsound.Beep(freq, dauer)


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    if USE_HTTPS:
        cert_pfad, key_pfad = sicherstelle_zertifikat()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert_pfad, key_pfad)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"Open at: {SCHEMA}://{ip_lokal()}:{PORT}/")
    if USE_HTTPS:
        print("Note: the browser will show a certificate warning on first visit,")
        print("that's normal for a self-signed certificate. See chat for the steps.")
    print("Press Ctrl+C to stop.")

    laufzeit = {}  # id -> {"letzter_roh":..., "a1":timestamp, "a2":timestamp}

    with mss.mss() as sct:
        while True:
            with lock:
                pick = state["pick_requested"]
                modus = state["modus"]
                punkte_ids = [p["id"] for p in state["punkte"]]
                webhook_url = state["webhook_url"]
                tg_token = state["telegram_token"]
                tg_chat = state["telegram_chat_id"]
                ntfy_topic = state["ntfy_topic"]

            if pick:
                with lock:
                    state["pick_requested"] = False
                    state["picking"] = True
                region = einzel_ziel_wahl()
                with lock:
                    state["picking"] = False
                    if region and len(state["punkte"]) < MAX_PUNKTE:
                        pid = f"p{state['naechste_id']}"
                        state["naechste_id"] += 1
                        state["punkte"].append(neuer_punkt(pid, region))
                        state["modus"] = "vorschau"
                continue

            if not punkte_ids or modus in ("auswahl", "gestoppt"):
                time.sleep(INTERVAL)
                continue

            for pid in punkte_ids:
                with lock:
                    punkt = next((p for p in state["punkte"] if p["id"] == pid), None)
                    region = dict(punkt["region"]) if punkt else None
                if punkt is None or region is None:
                    continue

                shot = sct.grab(region)
                bild = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
                puffer = io.BytesIO()
                bild.resize((bild.width * 3, bild.height * 3)).save(puffer, "PNG")
                roh = lese_zahl(bild)

                lz = laufzeit.setdefault(pid, {"letzter_roh": None, "a1": 0.0, "a2": 0.0})

                with lock:
                    punkt = next((p for p in state["punkte"] if p["id"] == pid), None)
                    if punkt is None:
                        continue
                    punkt["png"] = puffer.getvalue()
                    if roh is not None and roh == lz["letzter_roh"] and roh != punkt["wert"]:
                        if punkt["wert"] is not None:
                            punkt["history"].append(
                                {"t": time.time(), "von": punkt["wert"], "nach": roh})
                        punkt["wert"] = roh
                        if punkt["max_auto_pending"]:
                            punkt["max"] = roh
                            punkt["max_auto_pending"] = False
                    wert, max_, typ = punkt["wert"], punkt["max"], punkt["typ"]
                    schwelle, gelb, rot, name = punkt["schwelle"], punkt["gelb"], punkt["rot"], punkt["name"]
                lz["letzter_roh"] = roh

                if modus == "aktiv" and wert is not None:
                    if typ == "unten":
                        if wert <= schwelle:
                            if ALARM_TON and time.time() - lz["a1"] >= WIEDERHOLUNG:
                                for _ in range(3):
                                    winsound.Beep(1500, 400)
                                nachricht = f"NOVA Sentinel: {name} is at {wert} (<= {schwelle})"
                                sende_webhook(webhook_url, nachricht)
                                sende_telegram(tg_token, tg_chat, nachricht)
                                sende_ntfy(ntfy_topic, nachricht)
                                lz["a1"] = time.time()
                        else:
                            lz["a1"] = 0.0
                    else:
                        if max_:
                            proz = wert / max_ * 100
                            if proz >= rot:
                                if ALARM_TON and time.time() - lz["a2"] >= WIEDERHOLUNG:
                                    for _ in range(3):
                                        winsound.Beep(1200, 350)
                                    nachricht = f"NOVA Sentinel: {name} critical at {proz:.0f}%"
                                    sende_webhook(webhook_url, nachricht)
                                    sende_telegram(tg_token, tg_chat, nachricht)
                                    sende_ntfy(ntfy_topic, nachricht)
                                    lz["a2"] = time.time()
                                lz["a1"] = 0.0
                            elif proz >= gelb:
                                if ALARM_TON and time.time() - lz["a1"] >= WIEDERHOLUNG:
                                    melodie_gelb()
                                    nachricht = f"NOVA Sentinel: {name} warning at {proz:.0f}%"
                                    sende_webhook(webhook_url, nachricht)
                                    sende_telegram(tg_token, tg_chat, nachricht)
                                    sende_ntfy(ntfy_topic, nachricht)
                                    lz["a1"] = time.time()
                                lz["a2"] = 0.0
                            else:
                                lz["a1"] = lz["a2"] = 0.0

            time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
