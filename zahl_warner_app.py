"""
NOVA SENTINEL - Live-Ueberwachung von Item-Menge UND Traggewicht.

Ablauf:
  1. Beim Start (oder per TARGET LOCK-Knopf in der App) oeffnet sich ein
     kleines Hover-Menue oben am PC-Bildschirm mit 3 Knoepfen:
       1) Item-Menge Ziel setzen
       2) Traggewicht Ziel setzen
       3) Uebernehmen (erst aktiv, wenn beide gesetzt sind)
     ESC waehrend einer Rechteck-Auswahl bricht nur DIESE Auswahl ab und
     kehrt zum Hover-Menue zurueck, es schliesst nicht alles.
  2. Nach "Uebernehmen" liest das Programm live und dauerhaft beide Werte
     (Vorschau, kein Alarm), damit man die Erkennung pruefen kann.
  3. Erst nach Druck auf "Start" in der App wird der Alarm scharf geschaltet.

Installation (Windows):
  1. Tesseract OCR installieren: https://github.com/UB-Mannheim/tesseract/wiki
  2. pip install mss pillow pytesseract
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
import winsound
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import mss
import pytesseract
from PIL import Image, ImageOps, ImageTk

try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE, wichtig bei Skalierung
except Exception:
    pass  # nicht Windows, oder aeltere Windows-Version ohne diese Funktion

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# ---- EINSTELLUNGEN ----
LOW = 30                  # Warnschwelle Item-Menge (auch in der App aenderbar)
OK = 50
MAXWERT = 3110             # Fortschrittsbalken-Maximum fuer die Item-Menge
MAX_GEWICHT = 3110         # Start-Maximalgewicht (in der App aenderbar)
GEWICHT_GELB = 70          # ab % gelb + Melodie
GEWICHT_ROT = 85           # ab % rot + Alarmton
INTERVAL = 1.0
WIEDERHOLUNG = 60
PORT = 8787
ITEM_NAME = "Ware"
ALARM_TON = True
USE_HTTPS = True   # selbstsigniertes Zertifikat, Browser zeigt trotzdem eine Warnung (siehe Chat)
# -----------------------
SCHEMA = "https" if USE_HTTPS else "http"

lock = threading.Lock()
state = {
    "wert": None, "png": b"", "history": [], "updated": 0.0,
    "low": LOW, "region": None, "max": MAXWERT, "debug_png": b"",
    "wert_gewicht": None, "png_gewicht": b"", "region_gewicht": None,
    "max_gewicht": MAX_GEWICHT, "debug_png_gewicht": b"",
    # modus: "auswahl" (kein Ziel gewaehlt) | "vorschau" (liest live, kein Alarm)
    #      | "aktiv" (Alarm scharf) | "gestoppt" (angehalten)
    "modus": "auswahl",
    "pick_requested": True,   # startet automatisch mit dem Hover-Menue
    "picking": False,
    "max_auto_pending": False,
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
    """Erzeugt beim ersten Start ein selbstsigniertes Zertifikat und speichert
    es lokal, damit es bei spaeteren Starts wiederverwendet wird."""
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
        .subject_name(name)
        .issuer_name(name)
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


HTML = """<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NOVA Sentinel</title><style>
:root{color-scheme:dark}
body{margin:0;background:#0a1a33;color:#eee;font-family:system-ui,sans-serif}
.win{max-width:380px;margin:14px auto;border:1px solid #1f4e8c;border-radius:10px;
 overflow:hidden;box-shadow:0 8px 30px #0008;transition:.5s}
.bar{background:linear-gradient(90deg,#0d47a1,#08306b);padding:8px 12px;
 font-weight:700;display:flex;align-items:center;gap:8px;
 letter-spacing:2px;font-size:13px;color:#cfe3ff}
.body{padding:16px}
.row{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:14px}
label{font-size:13px;color:#9ec2ee}
input[type=number]{width:64px;background:#0f2a4d;border:1px solid #2f6fbf;color:#fff;
 border-radius:6px;padding:6px;font-size:14px}
button{background:#1565c0;color:#fff;border:none;border-radius:6px;padding:7px 14px;
 font-size:13px;cursor:pointer}
button:active{background:#0d47a1}
button:disabled{opacity:.4;cursor:not-allowed}
.big{font-size:44px;font-weight:800;color:#ffd76a;text-align:center;margin:2px 0}
.sub{text-align:center;color:#7fb3ff;font-size:13px;margin-bottom:14px}
.status{text-align:center;font-size:13px;font-weight:700;padding:8px;border-radius:8px;margin-bottom:14px}
.status.auswahl{background:#10306b;color:#8ab4f8}
.status.vorschau{background:#4a3b1a;color:#ffc23d}
.status.aktiv{background:#173a24;color:#3ddc73}
.status.gestoppt{background:#3a1a1a;color:#ff8a8a}
.progwrap{margin:14px 0}
.plabel{display:flex;justify-content:space-between;font-size:12px;color:#8ab4f8;margin-bottom:4px}
.ptrack{background:#0f2a4d;border-radius:8px;height:14px;overflow:hidden;
 border:1px solid #1f4e8c}
.pfill{height:100%;border-radius:8px;transition:.4s}
.thumbwrap{display:flex;justify-content:center;margin:16px 0}
.thumb{position:relative;width:96px;height:96px}
.thumb img{width:100%;height:100%;object-fit:cover;border-radius:10px;background:#000}
.thumb .num{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
 font-size:26px;font-weight:800;color:#fff;text-shadow:0 0 6px #000,0 0 6px #000}
.log{font-size:12px;color:#7fa8d9;line-height:1.5}
.ip{font-size:11px;color:#5a86b8;margin-top:10px}
.btns{display:flex;gap:8px;margin-top:10px}
.btns button{flex:1}
.state-ok .win{border-color:#3ddc73;box-shadow:0 0 22px 2px #3ddc7399}
.state-warn .win{border-color:#ffc23d;box-shadow:0 0 22px 2px #ffc23d99}
.state-low .win{border-color:#ff3b3b;animation:glow 1s infinite alternate}
.state-low .big{color:#ff5a5a}
@keyframes glow{from{box-shadow:0 0 12px 1px #ff3b3b77}to{box-shadow:0 0 40px 8px #ff3b3b}}
.dot{width:9px;height:9px;border-radius:50%;background:#666}
.dot.on{background:#5ad16a}
.footer{text-align:center;font-size:11px;color:#4a76ac;margin-top:16px;
 padding-top:10px;border-top:1px solid #16305c;letter-spacing:.5px}
.footer b{color:#7fb3ff}

/* Traggewicht-Sektion, RO-artiger Rahmen mit Ornament-Ecken */
.gewicht-box{margin-top:18px;border:2px solid #a9863f;border-radius:10px;
 background:linear-gradient(180deg,#1a2f52,#122140);padding:12px;position:relative}
.gewicht-titel{text-align:center;font-size:12px;letter-spacing:2px;color:#e8c874;
 font-weight:700;margin-bottom:8px}
.gewicht-row{display:flex;align-items:center;gap:12px}
.gtrack{flex:1;background:#0f2a4d;border:1px solid #a9863f;border-radius:8px;height:16px;overflow:hidden}
.gfill{height:100%;transition:.5s}
.gproz{width:48px;text-align:right;font-weight:700;font-size:13px}
.blob{width:46px;height:46px;flex-shrink:0}
.gsub{text-align:center;font-size:11px;color:#c9b183;margin-top:6px}
.collapse-toggle{display:flex;justify-content:center;margin-top:12px}
.collapse-toggle button{background:#0f2a4d;border:1px solid #2f6fbf;padding:4px 16px;
 border-radius:20px;font-size:14px}
.advanced{overflow:hidden;max-height:0;transition:max-height .3s ease}
.advanced.open{max-height:300px}
</style></head><body>
<div class="win" id="win">
<div class="bar"><span id="dot" class="dot"></span> <span>NOVA SENTINEL</span></div>
<div class="body">
 <div class="status" id="statusbox">Initialisiere ...</div>

 <div class="big" id="wert">-</div>
 <div class="sub" id="name"></div>
 <div class="sub" id="rate"></div>
 <div class="progwrap">
  <div class="plabel"><span>BESTAND</span><span id="pproz">-</span></div>
  <div class="ptrack"><div class="pfill" id="pfill" style="width:0%"></div></div>
  <div class="plabel"><span id="pzahlen"></span><span></span></div>
 </div>
 <div class="thumbwrap"><div class="thumb">
  <img id="img" alt="">
  <div class="num" id="imgnum"></div>
 </div></div>

 <div class="gewicht-box">
  <div class="gewicht-titel">TRAGGEWICHT</div>
  <div class="gewicht-row">
   <svg class="blob" id="blobsvg" viewBox="0 0 100 100">
    <ellipse cx="50" cy="58" rx="34" ry="30" id="blobBody" fill="#5ad16a"/>
    <circle cx="38" cy="52" r="5" fill="#08306b"/>
    <circle cx="62" cy="52" r="5" fill="#08306b"/>
    <path id="blobMund" d="M40 68 Q50 76 60 68" stroke="#08306b" stroke-width="3" fill="none" stroke-linecap="round"/>
    <circle id="halo" cx="50" cy="20" r="9" fill="none" stroke="#ffe98a" stroke-width="3"/>
    <path id="hornL" d="M32 34 L26 18 L38 30 Z" fill="#c0392b" style="display:none"/>
    <path id="hornR" d="M68 34 L74 18 L62 30 Z" fill="#c0392b" style="display:none"/>
   </svg>
   <div class="gtrack"><div class="gfill" id="gfill" style="width:0%"></div></div>
   <div class="gproz" id="gproz">-</div>
  </div>
  <div class="gsub" id="gsub">Ziel noch nicht kalibriert</div>
 </div>

 <div class="log" id="log">Warte auf Daten ...</div>
 <div class="ip" id="ip"></div>

 <div class="advanced" id="advanced">
  <div class="row" style="margin-top:14px">
   <label>Max. Bestand</label>
   <div style="display:flex;gap:8px">
    <input type="number" id="maxbestand">
    <button onclick="setMaxBestand()">OK</button>
   </div>
  </div>
  <div style="font-size:11px;color:#7fa8d9;margin:-8px 0 10px">
   Wird bei TARGET LOCK automatisch aus der ersten erkannten Zahl gesetzt.
   Nur eintragen, wenn du den Bestand zwischendurch wieder aufgefuellt hast.
  </div>
  <div class="row">
   <label>Warnen bei (Item)</label>
   <div style="display:flex;gap:8px">
    <input type="number" id="schwelle">
    <button onclick="setSchwelle()">OK</button>
   </div>
  </div>
  <div class="row">
   <label>Max. Traggewicht</label>
   <div style="display:flex;gap:8px">
    <input type="number" id="maxgewicht">
    <button onclick="setMaxGewicht()">OK</button>
   </div>
  </div>
  <div class="btns">
   <button id="btnStart" onclick="steuere('start')">Start</button>
   <button onclick="steuere('stop')">Stopp</button>
  </div>
  <div class="btns">
   <button onclick="zielLock()" style="flex:1;background:#1f6b3f;border:1px solid #3ddc73">&#127919; TARGET LOCK</button>
  </div>
 </div>
 <div class="collapse-toggle"><button onclick="toggleAdvanced()" id="toggleBtn">&#9650;</button></div>

 <div class="footer">by <b>Grigorios Gkisios</b> ~ Hobby Developer</div>
</div></div>
<script>
let letzteSchwelle=null, letzterMaxGewicht=null, maxBestandBearbeitet=false;
const TEXTE={
 auswahl:"KEIN ZIEL GEWAEHLT - Bitte TARGET LOCK nutzen",
 vorschau:"VORSCHAU - Erkennung wird getestet (kein Alarm)",
 aktiv:"AKTIV - Ueberwachung laeuft",
 gestoppt:"ANGEHALTEN",
};
let advOpen=false;
function toggleAdvanced(){
 advOpen=!advOpen;
 document.getElementById("advanced").className="advanced"+(advOpen?" open":"");
 document.getElementById("toggleBtn").innerHTML = advOpen ? "&#9660;" : "&#9650;";
}
function fmtZeit(min){
 if(min===null)return "unbekannt";
 if(min<1)return "< 1 Min.";
 if(min<60)return min.toFixed(0)+" Min.";
 return (min/60).toFixed(1)+" Std.";
}
function updateBlob(proz){
  const body=document.getElementById("blobBody"), mund=document.getElementById("blobMund"),
        halo=document.getElementById("halo"), hL=document.getElementById("hornL"), hR=document.getElementById("hornR");
  if(proz===null){body.setAttribute("fill","#555");halo.style.display="none";hL.style.display="none";hR.style.display="none";return;}
  if(proz<70){
    body.setAttribute("fill","#5ad16a"); halo.style.display="inline"; hL.style.display="none"; hR.style.display="none";
    mund.setAttribute("d","M40 68 Q50 76 60 68");
  } else if(proz<85){
    body.setAttribute("fill","#e0a83c"); halo.style.display="none"; hL.style.display="inline"; hR.style.display="none";
    mund.setAttribute("d","M40 70 Q50 64 60 70");
  } else {
    body.setAttribute("fill","#c0392b"); halo.style.display="none"; hL.style.display="inline"; hR.style.display="inline";
    mund.setAttribute("d","M38 72 L44 64 L50 72 L56 64 L62 72");
  }
}
async function tick(){
 try{
  const d=await (await fetch("/state.json")).json();
  document.getElementById("dot").className="dot"+(d.modus==="aktiv"?" on":"");
  document.getElementById("name").textContent=d.item;
  document.getElementById("img").src="/img.png?"+Date.now();
  document.getElementById("imgnum").textContent=d.wert===null?"?":d.wert;
  document.getElementById("wert").textContent=(d.wert===null?"-":d.wert)+" "+d.item;
  if(letzteSchwelle===null){document.getElementById("schwelle").value=d.low;letzteSchwelle=d.low;}
  if(letzterMaxGewicht===null){document.getElementById("maxgewicht").value=d.max_gewicht;letzterMaxGewicht=d.max_gewicht;}
  if(!maxBestandBearbeitet){document.getElementById("maxbestand").value=d.max;}

  const sbox=document.getElementById("statusbox");
  sbox.className="status "+d.modus;
  let statusText=TEXTE[d.modus]||d.modus;
  if(d.modus==="vorschau"){
    statusText = (d.wert!==null && d.gewicht!==null)
      ? "VORSCHAU - Item: "+d.wert+" | Gewicht: "+d.gewicht+" \\u2713 Bereit zum Start"
      : "VORSCHAU - Erkennung laeuft, bitte pruefen";
  }
  sbox.textContent=statusText;
  document.getElementById("btnStart").disabled = (d.modus==="auswahl"||d.modus==="picking");

  let zustand="";
  if(d.modus==="aktiv" && d.wert!==null){
    if(d.wert<=d.low) zustand="state-low";
    else if(d.wert<d.ok) zustand="state-warn";
    else zustand="state-ok";
  }
  document.getElementById("win").parentElement.className = zustand;

  const proz = d.max ? Math.min(100,(d.wert||0)/d.max*100) : 0;
  document.getElementById("pfill").style.width=proz.toFixed(1)+"%";
  document.getElementById("pfill").style.background = proz<20 ? "#ff5a5a" : (proz<50 ? "#f3a83c" : "#5ad16a");
  document.getElementById("pproz").textContent=proz.toFixed(1)+" %";
  document.getElementById("pzahlen").textContent=(d.wert===null?"-":d.wert)+" / "+d.max;
  document.getElementById("rate").textContent =
    "Verbrauch: "+d.rate_pro_min.toFixed(1)+" / Min. \\u00b7 Restzeit bis leer: ca. "+fmtZeit(d.restzeit_min);

  let gproz=null;
  if(d.gewicht!==null && d.max_gewicht){
    gproz=Math.min(100,(d.gewicht/d.max_gewicht)*100);
  }
  const gfill=document.getElementById("gfill");
  if(gproz===null){
    gfill.style.width="0%"; document.getElementById("gproz").textContent="-";
    document.getElementById("gsub").textContent = d.region_gewicht ? "Warte auf Erkennung ..." : "Ziel noch nicht kalibriert";
  } else {
    gfill.style.width=gproz.toFixed(1)+"%";
    gfill.style.background = gproz<70 ? "#3ddc73" : (gproz<85 ? "#e0a83c" : "#ff3b3b");
    document.getElementById("gproz").textContent=gproz.toFixed(0)+"%";
    document.getElementById("gsub").textContent=d.gewicht+" / "+d.max_gewicht;
  }
  updateBlob(gproz);

  const zeit=new Date(d.updated*1000).toLocaleTimeString();
  document.getElementById("log").textContent = d.picking
    ? "HOVER-MENUE aktiv - bitte am PC die Ziele setzen ..."
    : "Zuletzt erkannt: "+zeit;
  document.getElementById("ip").textContent=d.url;
 }catch(e){document.getElementById("log").textContent="Keine Verbindung zum PC";}
}
async function zielLock(){
 await fetch("/pick_region",{method:"POST"});
}
async function setSchwelle(){
 const v=document.getElementById("schwelle").value;
 letzteSchwelle=v;
 await fetch("/set_threshold?wert="+encodeURIComponent(v),{method:"POST"});
}
async function setMaxBestand(){
 const v=document.getElementById("maxbestand").value;
 maxBestandBearbeitet=true;
 await fetch("/set_maxbestand?wert="+encodeURIComponent(v),{method:"POST"});
}
async function setMaxGewicht(){
 const v=document.getElementById("maxgewicht").value;
 letzterMaxGewicht=v;
 await fetch("/set_maxgewicht?wert="+encodeURIComponent(v),{method:"POST"});
}
async function steuere(aktion){
 await fetch("/control?aktion="+aktion,{method:"POST"});
}
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

    def _rate_und_restzeit(self):
        jetzt = time.time()
        fenster = [h for h in state["history"] if jetzt - h["t"] < 900 and h["nach"] < h["von"]]
        verbrauch = sum(h["von"] - h["nach"] for h in fenster)
        minuten = min(15.0, (jetzt - fenster[0]["t"]) / 60) if fenster else 0
        rate = verbrauch / minuten if minuten > 0.2 else 0.0
        restzeit = (state["wert"] / rate) if (rate > 0 and state["wert"] is not None) else None
        return rate, restzeit

    def do_GET(self):
        pfad = self.path.split("?")[0]
        if pfad == "/":
            self._send("text/html; charset=utf-8", HTML.encode("utf-8"))
        elif pfad == "/img.png":
            with lock:
                self._send("image/png", state["png"])
        elif pfad == "/debug_item.png":
            with lock:
                self._send("image/png", state["debug_png"])
        elif pfad == "/debug_gewicht.png":
            with lock:
                self._send("image/png", state["debug_png_gewicht"])
        elif pfad == "/state.json":
            with lock:
                rate, restzeit = self._rate_und_restzeit()
                daten = {
                    "item": ITEM_NAME, "wert": state["wert"], "low": state["low"],
                    "ok": OK, "max": state["max"], "history": state["history"][-30:],
                    "updated": state["updated"], "now": time.time(),
                    "modus": state["modus"], "picking": state["picking"],
                    "rate_pro_min": rate, "restzeit_min": restzeit,
                    "url": f"{SCHEMA}://{ip_lokal()}:{PORT}/",
                    "gewicht": state["wert_gewicht"], "max_gewicht": state["max_gewicht"],
                    "region_gewicht": state["region_gewicht"] is not None,
                }
            self._send("application/json", json.dumps(daten).encode())
        else:
            self.send_error(404)

    def do_POST(self):
        pfad = self.path.split("?")[0]
        qs = self.path.split("?", 1)[1] if "?" in self.path else ""
        params = dict(p.split("=") for p in qs.split("&") if "=" in p)
        if pfad == "/set_threshold":
            try:
                with lock:
                    state["low"] = int(params.get("wert", state["low"]))
                self._send("application/json", b'{"ok":true}')
            except ValueError:
                self._send("application/json", b'{"ok":false}', 400)
        elif pfad == "/set_maxbestand":
            try:
                with lock:
                    state["max"] = int(params.get("wert", state["max"]))
                self._send("application/json", b'{"ok":true}')
            except ValueError:
                self._send("application/json", b'{"ok":false}', 400)
        elif pfad == "/set_maxgewicht":
            try:
                with lock:
                    state["max_gewicht"] = int(params.get("wert", state["max_gewicht"]))
                self._send("application/json", b'{"ok":true}')
            except ValueError:
                self._send("application/json", b'{"ok":false}', 400)
        elif pfad == "/control":
            with lock:
                if params.get("aktion") == "start" and state["modus"] in ("vorschau", "gestoppt", "aktiv"):
                    state["modus"] = "aktiv"
                elif params.get("aktion") == "stop":
                    state["modus"] = "gestoppt"
            self._send("application/json", b'{"ok":true}')
        elif pfad == "/pick_region":
            with lock:
                state["pick_requested"] = True
            self._send("application/json", b'{"ok":true}')
        else:
            self.send_error(404)


def lese_zahl(bild):
    """Liest eine Zahl aus dem Bild. Probiert normal UND invertiert (fuer helle
    Schrift auf dunklem Hintergrund), jeweils schwarz-weiss umgewandelt."""
    grau = ImageOps.grayscale(bild)
    grau = grau.resize((grau.width * 6, grau.height * 6), Image.LANCZOS)
    grau = ImageOps.autocontrast(grau, cutoff=2)
    schwarzweiss = grau.point(lambda p: 255 if p > 140 else 0)

    for kandidat in (schwarzweiss, ImageOps.invert(schwarzweiss)):
        text = pytesseract.image_to_string(
            kandidat, config="--psm 7 -c tessedit_char_whitelist=0123456789")
        treffer = re.search(r"\d+", text)
        if treffer:
            return int(treffer.group()), kandidat
    return None, schwarzweiss


def fullscreen_auswahl(root, art):
    """Vollbild-Rechteckauswahl fuer EIN Ziel. ESC bricht nur diese Auswahl ab."""
    with mss.mss() as sct:
        monitor = sct.monitors[0]
        shot = sct.grab(monitor)
        vollbild = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

    win = tk.Toplevel(root)
    win.attributes("-fullscreen", True)
    win.attributes("-topmost", True)
    titel = "ITEM-MENGE" if art == "item" else "TRAGGEWICHT"
    farbe = "#3ddc73" if art == "item" else "#4fa8ff"

    bild_tk = ImageTk.PhotoImage(vollbild)
    canvas = tk.Canvas(win, cursor="cross", width=vollbild.width, height=vollbild.height,
                        highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    canvas.create_image(0, 0, image=bild_tk, anchor="nw")
    info = tk.Label(win, text=f"Rechteck um {titel} ziehen   (ESC = zurueck zum Menue)",
                     fg=farbe, bg="black", font=("Consolas", 16, "bold"))
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
            start["x"], start["y"], e.x, e.y, outline=farbe, width=3)

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


def ziel_menu():
    """Hover-Menue am oberen Bildschirmrand mit 3 Knoepfen fuer die Doppel-Kalibrierung."""
    root = tk.Tk()
    root.withdraw()
    ergebnis = {"item": None, "gewicht": None}

    toolbar = tk.Toplevel(root)
    toolbar.attributes("-topmost", True)
    toolbar.overrideredirect(True)
    sw = toolbar.winfo_screenwidth()
    bar_w, bar_h = 500, 78
    toolbar.geometry(f"{bar_w}x{bar_h}+{(sw - bar_w) // 2}+16")
    toolbar.configure(bg="#08306b", highlightbackground="#1f4e8c", highlightthickness=2)

    tk.Label(toolbar, text="NOVA SENTINEL  \u2014  Ziele setzen, dann Uebernehmen",
             bg="#08306b", fg="#cfe3ff", font=("Segoe UI", 9, "bold")).pack(pady=(8, 4))
    row = tk.Frame(toolbar, bg="#08306b")
    row.pack()

    def stil(btn, fertig):
        if fertig:
            btn.configure(bg="#2ecc71", fg="#08306b", activebackground="#27ae60")
        else:
            btn.configure(bg="#1565c0", fg="white", activebackground="#0d47a1")

    def waehlen(art, btn):
        toolbar.withdraw()
        region = fullscreen_auswahl(root, art)
        if region:
            ergebnis[art] = region
            stil(btn, True)
            if ergebnis["item"] and ergebnis["gewicht"]:
                btn3.configure(state="normal")
                stil(btn3, True)
        toolbar.deiconify()
        toolbar.lift()
        toolbar.attributes("-topmost", True)

    btn1 = tk.Button(row, text="1) Item-Menge", width=15, command=lambda: waehlen("item", btn1))
    btn2 = tk.Button(row, text="2) Traggewicht", width=15, command=lambda: waehlen("gewicht", btn2))
    btn3 = tk.Button(row, text="Uebernehmen", width=13, state="disabled", command=root.quit)
    stil(btn1, False)
    stil(btn2, False)
    btn3.configure(bg="#274060", fg="#7fa8d9")
    btn1.grid(row=0, column=0, padx=5, pady=6)
    btn2.grid(row=0, column=1, padx=5, pady=6)
    btn3.grid(row=0, column=2, padx=5, pady=6)

    toolbar.protocol("WM_DELETE_WINDOW", lambda: None)  # kein sofortiges Schliessen per X
    root.mainloop()
    root.destroy()
    return ergebnis["item"], ergebnis["gewicht"]


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
    print(f"Oeffnen unter: {SCHEMA}://{ip_lokal()}:{PORT}/")
    if USE_HTTPS:
        print("Hinweis: Der Browser zeigt beim ersten Aufruf eine Zertifikatswarnung,")
        print("das ist normal bei einem selbstsignierten Zertifikat. Siehe Chat fuer die Schritte.")
    print("Beenden mit Strg+C.")

    letzter_roh, letzter_alarm = None, 0.0
    letzter_roh_g, letzter_alarm_gelb, letzter_alarm_rot = None, 0.0, 0.0

    with mss.mss() as sct:
        while True:
            with lock:
                pick = state["pick_requested"]
                modus = state["modus"]
                region = dict(state["region"]) if state["region"] else None
                region_g = dict(state["region_gewicht"]) if state["region_gewicht"] else None
                schwelle = state["low"]
                max_gewicht = state["max_gewicht"]

            if pick:
                with lock:
                    state["pick_requested"] = False
                    state["picking"] = True
                neu_item, neu_gewicht = ziel_menu()
                with lock:
                    state["picking"] = False
                    if neu_item and neu_gewicht:
                        state["region"] = neu_item
                        state["region_gewicht"] = neu_gewicht
                        state["wert"] = None
                        state["history"] = []
                        state["wert_gewicht"] = None
                        state["modus"] = "vorschau"
                        state["max_auto_pending"] = True
                        print("Neue Ziele gesetzt:", neu_item, neu_gewicht)
                    elif state["region"] is None:
                        state["modus"] = "auswahl"
                continue

            if region is None or region_g is None or modus in ("auswahl", "gestoppt"):
                time.sleep(INTERVAL)
                continue

            # --- Item-Menge lesen ---
            shot = sct.grab(region)
            bild = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
            puffer = io.BytesIO()
            bild.resize((bild.width * 3, bild.height * 3)).save(puffer, "PNG")
            roh, debug_bild = lese_zahl(bild)
            debug_puffer = io.BytesIO()
            debug_bild.save(debug_puffer, "PNG")

            with lock:
                state["png"] = puffer.getvalue()
                state["debug_png"] = debug_puffer.getvalue()
                state["updated"] = time.time()
                if roh is not None and roh == letzter_roh and roh != state["wert"]:
                    if state["wert"] is not None:
                        state["history"].append(
                            {"t": time.time(), "von": state["wert"], "nach": roh})
                    state["wert"] = roh
                    if state["max_auto_pending"]:
                        state["max"] = roh
                        state["max_auto_pending"] = False
                        print("Max. Bestand automatisch gesetzt auf:", roh)
                wert = state["wert"]
            letzter_roh = roh

            # --- Traggewicht lesen ---
            shot_g = sct.grab(region_g)
            bild_g = Image.frombytes("RGB", shot_g.size, shot_g.bgra, "raw", "BGRX")
            roh_g, debug_bild_g = lese_zahl(bild_g)
            debug_puffer_g = io.BytesIO()
            debug_bild_g.save(debug_puffer_g, "PNG")
            with lock:
                state["debug_png_gewicht"] = debug_puffer_g.getvalue()
                if roh_g is not None and roh_g == letzter_roh_g:
                    state["wert_gewicht"] = roh_g
                wert_g = state["wert_gewicht"]
            letzter_roh_g = roh_g

            print("Item:", roh, "| gueltig:", wert, " -- Gewicht:", roh_g, "| gueltig:", wert_g,
                  "| Modus:", modus)

            if modus == "aktiv":
                # Item-Alarm
                if wert is not None and wert <= schwelle:
                    if ALARM_TON and time.time() - letzter_alarm >= WIEDERHOLUNG:
                        for _ in range(3):
                            winsound.Beep(1500, 400)
                        letzter_alarm = time.time()
                else:
                    letzter_alarm = 0.0

                # Traggewicht-Alarm
                if wert_g is not None and max_gewicht:
                    proz = wert_g / max_gewicht * 100
                    if proz >= GEWICHT_ROT:
                        if ALARM_TON and time.time() - letzter_alarm_rot >= WIEDERHOLUNG:
                            for _ in range(3):
                                winsound.Beep(1200, 350)
                            letzter_alarm_rot = time.time()
                        letzter_alarm_gelb = 0.0
                    elif proz >= GEWICHT_GELB:
                        if ALARM_TON and time.time() - letzter_alarm_gelb >= WIEDERHOLUNG:
                            melodie_gelb()
                            letzter_alarm_gelb = time.time()
                        letzter_alarm_rot = 0.0
                    else:
                        letzter_alarm_gelb = 0.0
                        letzter_alarm_rot = 0.0
            else:
                letzter_alarm = letzter_alarm_gelb = letzter_alarm_rot = 0.0

            time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
