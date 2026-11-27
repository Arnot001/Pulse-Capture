import json
import re
import time
import secrets
import threading
import urllib.request
import urllib.parse
import urllib.error
import webbrowser
import shutil
import subprocess
import tempfile
import html
import uuid
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import os

BASE = Path(os.environ["LOCALAPPDATA"]) / "PulseMemeStudio"
BASE.mkdir(parents=True, exist_ok=True)
LIB = BASE / "Library"
FAV = BASE / "favourites.json"
LIB.mkdir(exist_ok=True)

TOKEN = secrets.token_urlsafe(24)
PREFIX = "/" + TOKEN + "/"
API = "https://api.clipkaboom.com"
LOCK = threading.Lock()
LAST = 0
BLOCKED = 0

def valid(c):
    return (
        isinstance(c, dict)
        and isinstance(c.get("id"), str)
        and re.fullmatch(r"[A-Za-z0-9_-]{1,200}", c["id"])
    )

def favourites():
    try:
        data = json.loads(FAV.read_text(encoding="utf-8"))
        return [c for c in data if valid(c)]
    except Exception:
        return []

def library():
    return [
        {"title": p.stem.removeprefix("clipkaboom-").removesuffix("-sd").replace("-", " ").capitalize(), "name": p.name,
         "path": str(p), "local": True}
        for p in sorted(LIB.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        if p.is_file() and not p.is_symlink()
        and p.suffix.lower() == ".mp4"
    ]

def search(params):
    global LAST, BLOCKED
    with LOCK:
        now = time.monotonic()
        if now < max(LAST + 3, BLOCKED):
            raise ValueError("Please wait before searching again.")
        LAST = now

    endpoint = "/v1/featured" if params.get("mode") == "trending" else "/v1/search"
    query = {"limit": 24}
    for key in ("q", "category", "tag", "cursor"):
        if params.get(key):
            query[key] = params[key][:300]

    url = API + endpoint + "?" + urllib.parse.urlencode(query)
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "PulseMemeStudio/0.5"
    })

    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            with LOCK:
                try:
                    delay = int(exc.headers.get("Retry-After", "60"))
                except ValueError:
                    delay = 60
                BLOCKED = time.monotonic() + max(3, delay)
        raise

    return {
        "results": [c for c in data.get("results", []) if valid(c)],
        "next": data.get("next")
    }


DOWNLOAD_LOCK = threading.Lock()
LAST_DOWNLOAD = 0

def check_url(url):
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in (
            "api.clipkaboom.com", "clipkaboom.com"
        )
        or parsed.username or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise ValueError("Unrecognised provider download URL")
    return url

class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(
            req, fp, code, msg, headers, newurl
        )

def mcp_download_link(clip_id):
    session = None
    protocol = "2025-03-26"
    opener = urllib.request.build_opener(SafeRedirect())

    def rpc(method, params, request_id=None):
        nonlocal session, protocol
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }
        if request_id is not None:
            payload["id"] = request_id

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": "PulseMemeStudio/0.5",
            "MCP-Protocol-Version": protocol
        }

        if session:
            headers["Mcp-Session-Id"] = session

        req = urllib.request.Request(
            API + "/mcp",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST"
        )

        with opener.open(req, timeout=25) as response:
            session = response.headers.get(
                "Mcp-Session-Id", session
            )

            if request_id is None:
                return {}

            ctype = response.headers.get("Content-Type", "")

            if "text/event-stream" in ctype:
                event = None
                data = []

                for raw in response:
                    line = raw.decode("utf-8").strip()

                    if line.startswith("data:"):
                        data.append(line[5:].strip())

                    elif not line and data:
                        obj = json.loads("\n".join(data))
                        data = []

                        if obj.get("id") == request_id:
                            event = obj
                            break

                if event is None:
                    raise ValueError("No matching MCP response")
                obj = event
            else:
                obj = json.load(response)

        if "error" in obj:
            raise ValueError(str(obj["error"]))

        return obj.get("result", {})

    init = rpc("initialize", {
        "protocolVersion": protocol,
        "capabilities": {},
        "clientInfo": {
            "name": "PulseMemeStudio",
            "version": "0.4"
        }
    }, 1)

    protocol = init.get("protocolVersion", protocol)
    rpc("notifications/initialized", {})

    listing = rpc("tools/list", {}, 2)

    tool = next(
        (t for t in listing.get("tools", [])
         if t.get("name") == "get_download_url"),
        None
    )

    if not tool:
        raise ValueError("Free download tool unavailable")

    schema = tool.get("inputSchema", {})
    props = schema.get("properties", {})

    id_key = next(
        (key for key in ("clip_id", "clipId", "id", "slug")
         if key in props),
        None
    )

    if not id_key:
        raise ValueError(
            "Unrecognised download schema: " + str(list(props))
        )

    args = {id_key: clip_id}

    if "quality" in props:
        quality = props["quality"]
        choices = quality.get("enum", [])

        if "sd" in choices:
            args["quality"] = "sd"
        elif "480p" in choices:
            args["quality"] = "480p"
        elif "quality" in schema.get("required", []):
            raise ValueError("No explicit free SD quality available")

    missing = set(schema.get("required", [])) - set(args)
    if missing:
        raise ValueError("Unsupported required parameters: " + str(missing))

    result = rpc("tools/call", {
        "name": "get_download_url",
        "arguments": args
    }, 3)

    if result.get("isError"):
        raise ValueError(str(result.get("content", []))[:500])

    # Accept links only from the official download tool.
    candidates = []

    def extract(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in ("url", "download_url", "downloadUrl", "download_link", "downloadLink"):
                    if isinstance(value, str):
                        candidates.append(value)
                elif isinstance(value, (dict, list)):
                    extract(value)

        elif isinstance(obj, list):
            for item in obj:
                extract(item)

    extract(result.get("structuredContent", {}))

    for item in result.get("content", []):
        if item.get("type") != "text":
            continue

        body = item.get("text", "")

        try:
            extract(json.loads(body))
        except (ValueError, TypeError):
            candidates.extend(
                re.findall(r'https://[^\s<>"\)]+', body)
            )

    for url in candidates:
        try:
            return check_url(url)
        except ValueError:
            continue

    raise ValueError("No supported download link returned")

def download_free(clip_id):
    global LAST_DOWNLOAD

    if not isinstance(clip_id, str) or not re.fullmatch(
        r"[A-Za-z0-9_-]{1,200}", clip_id
    ):
        raise ValueError("Invalid clip ID")

    with DOWNLOAD_LOCK:
        dest = LIB / ("clipkaboom-" + clip_id + "-sd.mp4")

        if dest.is_file():
            return {"ok": True, "name": dest.name, "existing": True}

        if time.monotonic() - LAST_DOWNLOAD < 10:
            raise ValueError("Allow 10 seconds between downloads")

        LAST_DOWNLOAD = time.monotonic()
        url = mcp_download_link(clip_id)
        temp = LIB / (uuid.uuid4().hex + ".part")

        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "PulseMemeStudio/0.5"
            })

            opener = urllib.request.build_opener(SafeRedirect())
            total = 0

            with opener.open(req, timeout=30) as response:
                check_url(response.geturl())

                head = response.read(64)
                if b"ftyp" not in head:
                    raise ValueError("Provider did not return an MP4")

                with temp.open("xb") as output:
                    output.write(head)
                    total = len(head)

                    while True:
                        chunk = response.read(65536)
                        if not chunk:
                            break

                        total += len(chunk)
                        if total > 50 * 1024 * 1024:
                            raise ValueError("Download exceeds 50 MB")

                        output.write(chunk)

            expected = response.headers.get("Content-Length")
            if expected and total != int(expected):
                raise ValueError("Incomplete download")

            temp.replace(dest)

        finally:
            temp.unlink(missing_ok=True)

        return {
            "ok": True,
            "name": dest.name,
            "bytes": total
        }

def get_clip(clip_id):
    global LAST, BLOCKED

    if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", clip_id):
        raise ValueError("Invalid meme ID")

    with LOCK:
        now = time.monotonic()
        if now < max(LAST + 3, BLOCKED):
            raise ValueError("Please wait before searching again.")
        LAST = now

    req = urllib.request.Request(
        API + "/v1/clips/" + clip_id,
        headers={
            "Accept": "application/json",
            "User-Agent": "PulseMemeStudio/0.5"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            with LOCK:
                try:
                    delay = int(exc.headers.get("Retry-After", "60"))
                except ValueError:
                    delay = 60
                BLOCKED = time.monotonic() + max(3, delay)
        raise

    clip = data.get("result")
    if not valid(clip):
        raise ValueError("Clip not found")
    return clip


def convert_recording(data):
    ffmpeg = shutil.which("ffmpeg")

    if not ffmpeg:
        try:
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass

    if not ffmpeg:
        raise ValueError(
            "FFmpeg unavailable; recording saved as WebM"
        )

    if data[:4] != b"\x1a\x45\xdf\xa3":
        raise ValueError("Invalid WebM recording")

    with tempfile.TemporaryDirectory(prefix="pulse-meme-") as folder:
        src = Path(folder) / "source.webm"
        dst = Path(folder) / "output.mp4"

        src.write_bytes(data)

        command = [
            ffmpeg,
            "-nostdin", "-hide_banner", "-loglevel", "error",
            "-protocol_whitelist", "file,pipe",
            "-f", "matroska",
            "-i", str(src),
            "-map", "0:v:0",
            "-map", "0:a:0?",
            "-t", "125",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            str(dst)
        ]

        result = subprocess.run(
            command, capture_output=True, timeout=180
        )

        if result.returncode or not dst.is_file():
            raise ValueError("FFmpeg conversion failed")

        if dst.stat().st_size > 160 * 1024 * 1024:
            raise ValueError("Converted file too large")

        return dst.read_bytes()


EDITOR_HTML = '\n<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n<title>Pulse Meme Editor v0.5.4</title>\n<style>\n*{box-sizing:border-box}\n:root{color-scheme:dark}\nbody{margin:0;background:#0b1017;color:#e6edf3;\nfont:14px \'Segoe UI\',Arial,sans-serif}\nheader{padding:17px 24px;border-bottom:1px solid #29394a;\ndisplay:flex;justify-content:space-between;align-items:center}\nh1{font-size:22px;color:#00d9ff;letter-spacing:2px;margin:0}\nsmall{color:#8297ad}\n.layout{display:grid;grid-template-columns:300px minmax(0,1fr) 280px;\nmin-height:calc(100vh - 140px);gap:14px;padding:15px}\n.panel{background:#141e29;border:1px solid #29394a;\nborder-radius:10px;padding:15px;align-self:start}\nh2{font-size:15px;color:#00d9ff;margin:4px 0 16px}\nlabel{display:block;margin:13px 0 6px;color:#b8c8d8}\nbutton,select,textarea,input[type=file]{\nfont:inherit;color:#e6edf3;background:#1a293a;border:1px solid #34475c;\nborder-radius:6px;padding:10px;width:100%}\nbutton{cursor:pointer;margin-top:8px}\nbutton:hover{border-color:#00d9ff}\nbutton:disabled{opacity:.5;cursor:default}\n.primary{background:#007e9a}\ntextarea{resize:vertical;min-height:100px}\ninput[type=range]{width:100%;accent-color:#00c8ec}\ninput[type=color]{width:100%;height:32px}\ninput[type=checkbox]{accent-color:#00d9ff}\n.stage{display:flex;align-items:center;justify-content:center;\nbackground:#080d13;border-radius:10px;padding:12px;\nmin-width:0;min-height:350px}\ncanvas{display:block;max-width:100%;max-height:70vh;\nobject-fit:contain;background:black;\nborder:1px solid #34475c;touch-action:none;cursor:move}\n.line{border-top:1px solid #29394a;margin:18px 0}\n.value{float:right;color:#00d9ff}\nfooter{padding:12px 20px;border-top:1px solid #29394a;\nbackground:#121d2a;color:#00d9ff;position:sticky;bottom:0}\n#source{display:none}\n.note{font-size:12px;line-height:1.6;color:#8297ad}\n@media(max-width:900px){\n.layout{grid-template-columns:1fr 1fr}\n.stage{grid-column:1/-1;grid-row:1}\n}\n\n/* Pulse Wide Canvas */\nhtml,body{\n    width:100%;\n    height:100%;\n    margin:0;\n}\n\nbody{\n    height:100dvh;\n    display:grid;\n    grid-template-rows:auto minmax(0,1fr) auto;\n    overflow:hidden;\n}\n\nheader{\n    padding:10px 16px;\n    gap:12px;\n    flex-wrap:wrap;\n}\n\n.view-controls{\n    display:flex;\n    align-items:center;\n    gap:8px;\n    flex-wrap:wrap;\n}\n\n.view-controls button{\n    width:auto;\n    margin:0;\n    padding:8px 12px;\n}\n\n.layout{\n    display:grid;\n    grid-template-columns:260px minmax(0,1fr) 280px;\n    grid-template-rows:minmax(0,1fr);\n    min-height:0;\n    height:100%;\n    padding:8px;\n    gap:8px;\n    overflow:hidden;\n}\n\n.panel{\n    min-width:0;\n    min-height:0;\n    height:100%;\n    max-height:none;\n    padding:12px;\n    align-self:stretch;\n    overflow-y:auto;\n    overflow-x:hidden;\n    scrollbar-width:thin;\n    scrollbar-color:#34475c #141e29;\n}\n\n.panel label{\n    margin:10px 0 4px;\n}\n\n.panel textarea{\n    min-height:75px;\n}\n\n.panel button{\n    padding:8px;\n}\n\n.stage{\n    grid-column:auto;\n    grid-row:auto;\n    min-width:0;\n    min-height:0;\n    height:100%;\n    padding:8px;\n    overflow:hidden;\n    align-self:stretch;\n    display:flex;\n    align-items:center;\n    justify-content:center;\n}\n\ncanvas{\n    max-width:100%;\n    max-height:100%;\n    width:auto;\n    height:auto;\n    flex-shrink:0;\n}\n\nfooter{\n    position:static;\n    padding:8px 16px;\n    min-height:36px;\n}\n\n.layout.left-hidden{\n    grid-template-columns:minmax(0,1fr) 280px;\n}\n\n.layout.right-hidden{\n    grid-template-columns:260px minmax(0,1fr);\n}\n\n.layout.left-hidden .left-panel,\n.layout.right-hidden .right-panel{\n    display:none;\n}\n\n.layout.focus{\n    grid-template-columns:minmax(0,1fr);\n}\n\n.layout.focus .left-panel,\n.layout.focus .right-panel{\n    display:none;\n}\n\n@media(max-width:1000px){\n    .layout{\n        grid-template-columns:210px minmax(0,1fr) 230px;\n    }\n\n    .layout.left-hidden{\n        grid-template-columns:minmax(0,1fr) 230px;\n    }\n\n    .layout.right-hidden{\n        grid-template-columns:210px minmax(0,1fr);\n    }\n\n    .layout.focus{\n        grid-template-columns:minmax(0,1fr);\n    }\n}\n\n@media(max-width:700px){\n    body{\n        height:auto;\n        min-height:100dvh;\n        overflow:auto;\n        display:block;\n    }\n\n    .layout,\n    .layout.left-hidden,\n    .layout.right-hidden,\n    .layout.focus{\n        grid-template-columns:minmax(0,1fr);\n        grid-template-rows:auto;\n        height:auto;\n        overflow:visible;\n    }\n\n    .stage{\n        grid-row:1;\n        height:65vh;\n    }\n\n    .panel{\n        height:auto;\n        overflow:visible;\n    }\n}\n\n</style>\n</head>\n<body>\n<header>\n<h1>PULSE / MEME EDITOR</h1>\n\n<div class="view-controls">\n    <small>V0.5.4 | LOCAL EDITING</small>\n    <button id="toggleLeft">Hide Left</button>\n    <button id="toggleRight">Hide Right</button>\n    <button id="focusMode">Focus Mode</button>\n</div>\n\n</header>\n\n<div class="layout">\n<aside class="panel left-panel">\n<h2>CANVAS & BACKGROUND</h2>\n\n<label>Canvas format</label>\n<select id="format">\n<option value="720,1280">YouTube Shorts 9:16</option>\n<option value="1280,720">Landscape 16:9</option>\n<option value="720,720">Square 1:1</option>\n</select>\n\n<label>Background colour</label>\n<input type="color" id="bgColor" value="#151515">\n\n<label>Background image or video</label>\n<input type="file" id="bgFile" accept="image/*,video/*">\n<button id="clearBg">Remove background media</button>\n\n<label>Background start time\n<span class="value" id="bgTimeV">0.0s</span>\n</label>\n<input type="range" id="bgTime"\nmin="0" max="0" step="0.1" value="0" disabled>\n\n<div class="line"></div>\n<h2>GREEN SCREEN</h2>\n\n<label>\n<input type="checkbox" id="keyOn">\nEnable chroma key\n</label>\n\n<label>Removal strength <span class="value" id="strengthV"></span></label>\n<input type="range" id="strength" min="0" max="100" value="65">\n\n<label>Edge softness <span class="value" id="softV"></span></label>\n<input type="range" id="soft" min="1" max="100" value="30">\n\n<div class="line"></div>\n\n<h2>CHARACTER</h2>\n<label>Scale <span class="value" id="scaleV"></span></label>\n<input type="range" id="scale" min="20" max="300" value="85">\n<label>Horizontal position\n<span class="value" id="charXV"></span></label>\n<input type="range" id="charX"\nmin="0" max="100" step="0.1" value="50">\n\n<label>Vertical position\n<span class="value" id="charYV"></span></label>\n<input type="range" id="charY"\nmin="0" max="100" step="0.1" value="57">\n\n<label>Quick positioning</label>\n<select id="charPreset">\n<option value="">Choose position...</option>\n<option value="tl">Top left</option>\n<option value="tc">Top centre</option>\n<option value="tr">Top right</option>\n<option value="cl">Centre left</option>\n<option value="cc">Centre</option>\n<option value="cr">Centre right</option>\n<option value="bl">Bottom left</option>\n<option value="bc">Bottom centre</option>\n<option value="br">Bottom right</option>\n</select>\n\n<button id="resetPosition">Reset character</button>\n\n<p id="frameWarning" class="note"\nstyle="color:#e8b45c;display:none">\nSource extends beyond the canvas.\nKeep required provider watermarks visible.\n</p>\n\n<p class="note">Drag the meme on the canvas to reposition it.</p>\n</aside>\n\n<main class="stage">\n<canvas id="canvas" width="720" height="1280"></canvas>\n</main>\n\n<aside class="panel right-panel">\n<h2>MEME CAPTION</h2>\n\n<textarea id="caption" maxlength="160"\nplaceholder="When you realise..."></textarea>\n\n<label>Font family</label>\n<select id="fontFamily">\n    <option value="Arial">Arial</option>\n    <option value="Impact">Impact - Classic Meme</option>\n    <option value="Arial Black">Arial Black</option>\n    <option value="Comic Sans MS">Comic Sans</option>\n    <option value="Segoe UI">Segoe UI</option>\n    <option value="Verdana">Verdana</option>\n    <option value="Tahoma">Tahoma</option>\n    <option value="Georgia">Georgia</option>\n    <option value="Courier New">Courier New</option>\n    <option value="Trebuchet MS">Trebuchet</option>\n    <option value="Times New Roman">Times New Roman</option>\n    <option value="Consolas">Consolas</option>\n</select>\n\n<div style="display:flex;gap:20px">\n    <label>\n        <input type="checkbox" id="boldText" checked>\n        Bold\n    </label>\n    <label>\n        <input type="checkbox" id="italicText">\n        Italic\n    </label>\n</div>\n\n<label>Text alignment</label>\n<select id="textAlign">\n    <option value="left">Left</option>\n    <option value="center" selected>Centre</option>\n    <option value="right">Right</option>\n</select>\n\n<label>Text size <span class="value" id="fontV"></span></label>\n<input type="range" id="font" min="20" max="100" value="48">\n\n<label>Horizontal position\n<span class="value" id="textXV"></span></label>\n<input type="range" id="textX"\nmin="0" max="100" step="0.1" value="50">\n\n<label>Vertical position\n<span class="value" id="textYV"></span></label>\n<input type="range" id="textY"\nmin="0" max="100" step="0.1" value="12">\n\n<button id="resetText">Reset text position</button>\n<p class="note">Drag the caption directly on the canvas.</p>\n\n<label>Text colour</label>\n<input type="color" id="textColor" value="#ffffff">\n\n<label>Outline colour</label>\n<input type="color" id="outlineColor" value="#000000">\n\n<label>Outline thickness\n<span class="value" id="outlineV"></span></label>\n<input type="range" id="outline"\nmin="0" max="16" value="5">\n\n<label>\n<input type="checkbox" id="textBg">\nText background\n</label>\n\n<label>Text background colour</label>\n<input type="color" id="textBgColor" value="#000000">\n\n<div class="line"></div>\n<h2>AUDIO & PLAYBACK</h2>\n\n<label>Original audio volume <span class="value" id="volumeV"></span></label>\n<input type="range" id="volume" min="0" max="100" value="100">\n\n<button id="play">Play / Pause</button>\n<button id="restart">Restart preview</button>\n\n<div class="line"></div>\n<h2>EXPORT</h2>\n<button class="primary" id="export">EXPORT MEME</button>\n<p class="note">Keep this tab visible while exporting.\nExport runs in real time and retains the original audio.</p>\n</aside>\n</div>\n\n<video id="source" playsinline preload="auto"></video>\n<footer id="status">Loading selected meme...</footer>\n\n<script>\nconst $=id=>document.getElementById(id);\nconst canvas=$("canvas");\nconst ctx=canvas.getContext("2d");\nconst clip=$("source");\n\nconst scratch=document.createElement("canvas");\nconst sx=scratch.getContext("2d",{willReadFrequently:true});\n\nconst filename=new URLSearchParams(location.search).get("name")||"";\n\nlet background=null;\nlet bgVideo=null;\nlet bgDrawError=false;\nlet bgUrl=null;\nlet bgGeneration=0;\nlet posX=.5,posY=.57;\nlet rect={x:0,y:0,w:1,h:1};\nlet busy=false;\nlet dragging=false;\nlet dragTarget=null;\nlet captionRect=null;\nlet dragDX=0,dragDY=0;\nlet audio=null,gain=null,audioDest=null;\nlet loaded=false;\nlet lastFrame=0;\n\nfunction status(message){\n    $("status").textContent=message;\n}\n\nfunction clamp(n,min,max){\n    return Math.max(min,Math.min(max,n));\n}\n\nfunction updateValues(){\n    for(const [input,output,suffix] of [\n        ["strength","strengthV","%"],\n        ["soft","softV","%"],\n        ["scale","scaleV","%"],\n        ["charX","charXV","%"],\n        ["charY","charYV","%"],\n        ["font","fontV","px"],\n        ["textX","textXV","%"],\n        ["textY","textYV","%"],\n        ["outline","outlineV","px"],\n        ["volume","volumeV","%"]\n    ]){\n        $(output).textContent=$(input).value+suffix;\n    }\n    if(gain)gain.gain.value=Number($("volume").value)/100;\n}\n\ndocument.querySelectorAll("input[type=range]").forEach(\n    node=>node.addEventListener("input",updateValues)\n);\n\nupdateValues();\n\nfunction canvasFormat(){\n    const [w,h]=$("format").value.split(",").map(Number);\n    canvas.width=w;\n    canvas.height=h;\n}\n$("format").onchange=canvasFormat;\n\nfunction cover(media){\n    if(media instanceof HTMLVideoElement &&\n       media.readyState<2)return;\n\n    const w=media.videoWidth||media.naturalWidth;\n    const h=media.videoHeight||media.naturalHeight;\n    if(!w||!h)return;\n    const scale=Math.max(canvas.width/w,canvas.height/h);\n    ctx.drawImage(media,\n        (canvas.width-w*scale)/2,\n        (canvas.height-h*scale)/2,\n        w*scale,h*scale\n    );\n}\n\nfunction clearBackground(){\n    bgGeneration++;\n    if(bgVideo){\n        bgVideo.pause();\n        bgVideo.removeAttribute("src");\n        bgVideo.load();\n        bgVideo.remove();\n        bgVideo=null;\n    }\n\n    bgDrawError=false;\n    $("bgTime").max=0;\n    $("bgTime").value=0;\n    $("bgTime").disabled=true;\n    $("bgTimeV").textContent="0.0s";\n\n    if(bgUrl)URL.revokeObjectURL(bgUrl);\n    bgUrl=null;\n    background=null;\n}\n\n$("clearBg").onclick=()=>{\n    clearBackground();\n    $("bgFile").value="";\n};\n\n$("bgFile").onchange=()=>{\n    const file=$("bgFile").files[0];\n    if(!file)return;\n\n    clearBackground();\n    const token=bgGeneration;\n    bgUrl=URL.createObjectURL(file);\n\n\n    if(file.type.startsWith("video/") ||\n       /\\.(mp4|webm|mov|m4v)$/i.test(file.name)){\n\n        const video=document.createElement("video");\n\n        video.muted=true;\n        video.defaultMuted=true;\n        video.loop=true;\n        video.playsInline=true;\n        video.preload="auto";\n\n        video.style.position="fixed";\n        video.style.left="0";\n        video.style.top="0";\n        video.style.width="1px";\n        video.style.height="1px";\n        video.style.opacity="0";\n        video.style.pointerEvents="none";\n\n        document.body.append(video);\n\n        bgVideo=video;\n        background=video;\n        bgDrawError=false;\n\n        video.onloadedmetadata=()=>{\n            if(token!==bgGeneration)return;\n\n            $("bgTime").max=Number.isFinite(video.duration)\n                ? Math.max(0,video.duration-.1)\n                : 0;\n\n            $("bgTime").disabled=false;\n\n            status("Background video: "+\n                video.videoWidth+" x "+\n                video.videoHeight);\n        };\n\n        video.onloadeddata=()=>{\n            if(token!==bgGeneration)return;\n\n            render();\n\n            status("Background ready: "+\n                video.duration.toFixed(1)+" seconds");\n\n            if(!clip.paused){\n                video.play().catch(e=>{\n                    status("Background playback: "+e.message);\n                });\n            }\n        };\n\n        video.onseeked=()=>{\n            if(token!==bgGeneration)return;\n            render();\n        };\n\n        video.oncanplay=()=>{\n            if(token===bgGeneration)render();\n        };\n\n        video.onerror=()=>{\n            if(token!==bgGeneration)return;\n\n            status("Background video error: "+\n                (video.error?.message ||\n                 "Unsupported video codec"));\n        };\n\n        video.src=bgUrl;\n        video.load();\n\n    }else if(file.type.startsWith("image/")){\n        const image=new Image();\n        image.onload=()=>{\n            if(token!==bgGeneration)return;\n            background=image;\n            status("Image background loaded");\n        };\n        image.onerror=()=>{\n            if(token===bgGeneration)status("Cannot read image");\n        };\n        image.src=bgUrl;\n    }else{\n        status("Unsupported background file");\n    }\n};\n\n\n$("bgTime").oninput=()=>{\n    if(!bgVideo||bgVideo.readyState<1)return;\n\n    const value=Number($("bgTime").value);\n\n    $("bgTimeV").textContent=value.toFixed(1)+"s";\n\n    try{\n        bgVideo.currentTime=value;\n    }catch(e){\n        status("Background seek failed: "+e.message);\n    }\n};\n\n\nfunction characterSize(){\n    if(!clip.videoWidth||!clip.videoHeight){\n        return {w:1,h:1};\n    }\n\n    const fit=Math.min(\n        canvas.width/clip.videoWidth,\n        canvas.height/clip.videoHeight\n    )*Number($("scale").value)/100;\n\n    return {\n        w:Math.max(1,Math.round(clip.videoWidth*fit)),\n        h:Math.max(1,Math.round(clip.videoHeight*fit))\n    };\n}\n\nfunction syncCharacterPosition(){\n    $("charX").value=(posX*100).toFixed(1);\n    $("charY").value=(posY*100).toFixed(1);\n    updateValues();\n}\n\n$("charX").oninput=()=>{\n    posX=Number($("charX").value)/100;\n    render();\n};\n\n$("charY").oninput=()=>{\n    posY=Number($("charY").value)/100;\n    render();\n};\n\n$("charPreset").onchange=()=>{\n    const preset=$("charPreset").value;\n    if(!preset||!loaded)return;\n\n    const {w,h}=characterSize();\n\n    const left=Math.min(.5,w/(2*canvas.width));\n    const right=1-left;\n    const top=Math.min(.5,h/(2*canvas.height));\n    const bottom=1-top;\n\n    const positions={\n        tl:[left,top],\n        tc:[.5,top],\n        tr:[right,top],\n        cl:[left,.5],\n        cc:[.5,.5],\n        cr:[right,.5],\n        bl:[left,bottom],\n        bc:[.5,bottom],\n        br:[right,bottom]\n    };\n\n    if(positions[preset]){\n        [posX,posY]=positions[preset];\n        syncCharacterPosition();\n        render();\n    }\n\n    $("charPreset").value="";\n};\n\nfunction drawCharacter(){\n    if(clip.readyState<2||!clip.videoWidth)return;\n\n    const {w,h}=characterSize();\n\n    // Keep positioning independent of source size.\n    const x=posX*canvas.width-w/2;\n    const y=posY*canvas.height-h/2;\n\n    rect={x,y,w,h};\n\n    const cropped=\n        x<-.5||y<-.5||\n        x+w>canvas.width+.5||\n        y+h>canvas.height+.5;\n\n    $("frameWarning").style.display=\n        cropped?"block":"none";\n\n    if(!$("keyOn").checked){\n        ctx.drawImage(clip,x,y,w,h);\n        return;\n    }\n\n    // Process chroma key at a bounded source resolution.\n    // Upscale after keying rather than processing millions\n    // of additional pixels at 300% zoom.\n    const processScale=Math.min(\n        1,\n        960/clip.videoWidth,\n        960/clip.videoHeight\n    );\n\n    const pw=Math.max(\n        1,Math.round(clip.videoWidth*processScale)\n    );\n\n    const ph=Math.max(\n        1,Math.round(clip.videoHeight*processScale)\n    );\n\n    if(scratch.width!==pw||scratch.height!==ph){\n        scratch.width=pw;\n        scratch.height=ph;\n    }\n\n    sx.clearRect(0,0,pw,ph);\n    sx.drawImage(clip,0,0,pw,ph);\n\n    const frame=sx.getImageData(0,0,pw,ph);\n    const pixels=frame.data;\n\n    const threshold=\n        130-Number($("strength").value)*1.15;\n\n    const softness=\n        Number($("soft").value)*.7+1;\n\n    for(let i=0;i<pixels.length;i+=4){\n        const r=pixels[i];\n        const g=pixels[i+1];\n        const b=pixels[i+2];\n\n        const excess=g-Math.max(r,b);\n\n        if(g>55&&excess>threshold){\n            const opacity=clamp(\n                1-(excess-threshold)/softness,0,1\n            );\n\n            pixels[i+3]=Math.round(255*opacity);\n\n            if(opacity>0&&opacity<1){\n                pixels[i+1]=Math.min(\n                    g,Math.max(r,b)+threshold\n                );\n            }\n        }\n    }\n\n    sx.putImageData(frame,0,0);\n\n    ctx.imageSmoothingEnabled=true;\n    ctx.drawImage(scratch,x,y,w,h);\n}\n\nfunction drawCaption(){\n    captionRect=null;\n\n    const caption=$("caption").value.trim();\n    if(!caption)return;\n\n    const size=Number($("font").value);\n    const outline=Number($("outline").value);\n    const family=$("fontFamily").value;\n    const bold=$("boldText").checked?"900":"400";\n    const italic=$("italicText").checked?"italic ":"";\n    const alignment=$("textAlign").value;\n\n    ctx.save();\n\n    ctx.font=italic+bold+" "+size+\'px "\'+family+\'"\';\n    ctx.textBaseline="top";\n    ctx.lineJoin="round";\n    ctx.strokeStyle=$("outlineColor").value;\n    ctx.fillStyle=$("textColor").value;\n    ctx.lineWidth=Math.max(1,outline);\n\n    const padding=Math.max(8,outline+3);\n    const maxWidth=canvas.width*.88;\n    const lines=[];\n\n    for(const paragraph of caption.split("\\n")){\n        let line="";\n\n        for(const word of paragraph.split(/\\s+/)){\n            const candidate=line?line+" "+word:word;\n\n            if(ctx.measureText(candidate).width>maxWidth&&line){\n                lines.push(line);\n                line=word;\n            }else{\n                line=candidate;\n            }\n        }\n\n        lines.push(line);\n    }\n\n    const lineHeight=size*1.22;\n\n    const blockWidth=Math.min(\n        maxWidth,\n        Math.max(1,...lines.map(\n            line=>ctx.measureText(line).width\n        ))\n    );\n\n    const blockHeight=lines.length*lineHeight;\n\n    const centerX=clamp(\n        canvas.width*Number($("textX").value)/100,\n        blockWidth/2+padding,\n        canvas.width-blockWidth/2-padding\n    );\n\n    const y=clamp(\n        canvas.height*Number($("textY").value)/100,\n        padding,\n        Math.max(padding,canvas.height-blockHeight-padding)\n    );\n\n    const left=centerX-blockWidth/2;\n\n    captionRect={\n        x:left-padding,\n        y:y-padding,\n        w:blockWidth+padding*2,\n        h:blockHeight+padding*2,\n        anchorX:centerX,\n        anchorY:y\n    };\n\n    if($("textBg").checked){\n        ctx.fillStyle=$("textBgColor").value;\n        ctx.fillRect(\n            captionRect.x,\n            captionRect.y,\n            captionRect.w,\n            captionRect.h\n        );\n    }\n\n    ctx.fillStyle=$("textColor").value;\n    ctx.textAlign=alignment;\n\n    const anchor=alignment==="left"\n        ?left\n        :alignment==="right"\n            ?left+blockWidth\n            :centerX;\n\n    lines.forEach((line,i)=>{\n        const lineY=y+i*lineHeight;\n\n        if(outline>0){\n            ctx.strokeText(line,anchor,lineY,maxWidth);\n        }\n\n        ctx.fillText(line,anchor,lineY,maxWidth);\n    });\n\n    ctx.restore();\n}\n\nfunction render(){\n    ctx.fillStyle=$("bgColor").value;\n    ctx.fillRect(0,0,canvas.width,canvas.height);\n\n    if(background){\n        try{\n            cover(background);\n        }catch(e){\n            if(!bgDrawError){\n                bgDrawError=true;\n                status("Background render error: "+e.message);\n            }\n        }\n    }\n\n    drawCharacter();\n    drawCaption();\n}\n\nfunction loop(now){\n    if(now-lastFrame>=32){\n        lastFrame=now;\n        render();\n    }\n    requestAnimationFrame(loop);\n}\n\nrequestAnimationFrame(loop);\n\nfunction pointer(e){\n    const bounds=canvas.getBoundingClientRect();\n    return {\n        x:(e.clientX-bounds.left)*canvas.width/bounds.width,\n        y:(e.clientY-bounds.top)*canvas.height/bounds.height\n    };\n}\n\n\nfunction inside(p,r){\n    return r&&\n        p.x>=r.x&&p.x<=r.x+r.w&&\n        p.y>=r.y&&p.y<=r.y+r.h;\n}\n\ncanvas.onpointerdown=e=>{\n    if(busy||!loaded)return;\n\n    const p=pointer(e);\n\n    // Caption gets priority because it is drawn on top.\n    if(inside(p,captionRect)){\n        dragTarget="caption";\n        dragDX=p.x-captionRect.anchorX;\n        dragDY=p.y-captionRect.anchorY;\n    }else if(inside(p,rect)){\n        dragTarget="character";\n        dragDX=p.x-(rect.x+rect.w/2);\n        dragDY=p.y-(rect.y+rect.h/2);\n    }else{\n        return;\n    }\n\n    dragging=true;\n    canvas.setPointerCapture(e.pointerId);\n};\n\ncanvas.onpointermove=e=>{\n    if(busy)return;\n\n    const p=pointer(e);\n\n    if(!dragging){\n        canvas.style.cursor=\n            inside(p,captionRect)||inside(p,rect)\n                ?"move":"default";\n        return;\n    }\n\n    if(dragTarget==="caption"){\n        $("textX").value=clamp(\n            (p.x-dragDX)/canvas.width*100,0,100\n        );\n\n        $("textY").value=clamp(\n            (p.y-dragDY)/canvas.height*100,0,100\n        );\n\n        updateValues();\n        render();\n        return;\n    }\n\n    if(dragTarget==="character"){\n        posX=clamp(\n            (p.x-dragDX)/canvas.width,0,1\n        );\n\n        posY=clamp(\n            (p.y-dragDY)/canvas.height,0,1\n        );\n\n        syncCharacterPosition();\n        render();\n    }\n};\n\nfunction endDrag(){\n    dragging=false;\n    dragTarget=null;\n}\n\ncanvas.onpointerup=endDrag;\ncanvas.onpointercancel=endDrag;\ncanvas.onlostpointercapture=endDrag;\n\n$("resetText").onclick=()=>{\n    $("textX").value=50;\n    $("textY").value=12;\n    updateValues();\n    render();\n};\n\n$("resetPosition").onclick=()=>{\n    posX=.5;\n    posY=.57;\n\n    $("scale").value=85;\n    $("charPreset").value="";\n\n    syncCharacterPosition();\n    render();\n};\n\nasync function setupAudio(){\n    if(!audio){\n        const Audio=window.AudioContext||window.webkitAudioContext;\n        if(!Audio)throw Error("Web Audio unavailable");\n\n        audio=new Audio();\n        const source=audio.createMediaElementSource(clip);\n        gain=audio.createGain();\n        audioDest=audio.createMediaStreamDestination();\n\n        source.connect(gain);\n        gain.connect(audio.destination);\n        gain.connect(audioDest);\n        updateValues();\n    }\n\n    await audio.resume();\n}\n\nfunction pause(){\n    clip.pause();\n    if(background instanceof HTMLVideoElement)background.pause();\n}\n\nasync function play(){\n    if(!loaded)return;\n\n    await setupAudio();\n\n    if(clip.ended)clip.currentTime=0;\n\n    if(background instanceof HTMLVideoElement){\n        background.play().catch(()=>{});\n    }\n\n    await clip.play();\n}\n\n$("play").onclick=async()=>{\n    if(busy)return;\n    try{\n        if(clip.paused)await play();\n        else pause();\n    }catch(e){status(e.message)}\n};\n\n$("restart").onclick=async()=>{\n    if(busy||!loaded)return;\n    pause();\n    clip.currentTime=0;\n\n    if(background instanceof HTMLVideoElement){\n        background.currentTime=Number($("bgTime").value);\n    }\n\n    try{await play()}catch(e){status(e.message)}\n};\n\nclip.onended=()=>{\n    if(background instanceof HTMLVideoElement)background.pause();\n};\n\nclip.onloadedmetadata=()=>{\n    loaded=true;\n\n    if(/brother-ew|green-screen/i.test(filename)){\n        $("keyOn").checked=true;\n    }\n\n    status("Ready | "+clip.duration.toFixed(1)+" seconds");\n};\n\nclip.onerror=()=>status("Could not load this meme.");\n\nclip.src="media?name="+encodeURIComponent(filename);\n\nfunction seekStart(video,target=0){\n    if(Math.abs(video.currentTime-target)<.01)\n        return Promise.resolve();\n\n    return new Promise((resolve,reject)=>{\n        const timeout=setTimeout(()=>{\n            video.removeEventListener("seeked",done);\n            reject(Error("Video seek timed out"));\n        },5000);\n\n        function done(){\n            clearTimeout(timeout);\n            resolve();\n        }\n\n        video.addEventListener("seeked",done,{once:true});\n        video.currentTime=target;\n    });\n}\n\nfunction download(blob,extension){\n    const url=URL.createObjectURL(blob);\n    const a=document.createElement("a");\n    a.href=url;\n    a.download="Pulse-Meme-"+Date.now()+"."+extension;\n    document.body.append(a);\n    a.click();\n    a.remove();\n    setTimeout(()=>URL.revokeObjectURL(url),60000);\n}\n\nfunction setBusy(value){\n    busy=value;\n\n    document.querySelectorAll(\n        "button,input,select,textarea"\n    ).forEach(node=>node.disabled=value);\n\n    if(!value)$("bgTime").disabled=!bgVideo;\n}\n\n\nconst wideLayout=document.querySelector(".layout");\nconst wideStage=document.querySelector(".stage");\n\nlet wideMode="normal";\n\nfunction fitCanvas(){\n    const style=getComputedStyle(wideStage);\n\n    const availableW=Math.max(\n        1,\n        wideStage.clientWidth\n        -parseFloat(style.paddingLeft)\n        -parseFloat(style.paddingRight)\n    );\n\n    const availableH=Math.max(\n        1,\n        wideStage.clientHeight\n        -parseFloat(style.paddingTop)\n        -parseFloat(style.paddingBottom)\n    );\n\n    const ratio=Math.min(\n        availableW/canvas.width,\n        availableH/canvas.height\n    );\n\n    canvas.style.width=\n        Math.floor(canvas.width*ratio)+"px";\n\n    canvas.style.height=\n        Math.floor(canvas.height*ratio)+"px";\n}\n\nfunction applyWideMode(){\n    wideLayout.classList.remove(\n        "left-hidden","right-hidden","focus"\n    );\n\n    if(wideMode==="left"){\n        wideLayout.classList.add("left-hidden");\n    }\n\n    if(wideMode==="right"){\n        wideLayout.classList.add("right-hidden");\n    }\n\n    if(wideMode==="focus"){\n        wideLayout.classList.add("focus");\n    }\n\n    $("toggleLeft").textContent=\n        wideMode==="left"?"Show Left":"Hide Left";\n\n    $("toggleRight").textContent=\n        wideMode==="right"?"Show Right":"Hide Right";\n\n    $("focusMode").textContent=\n        wideMode==="focus"?"Exit Focus":"Focus Mode";\n\n    requestAnimationFrame(fitCanvas);\n}\n\n$("toggleLeft").onclick=()=>{\n    wideMode=wideMode==="left"?"normal":"left";\n    applyWideMode();\n};\n\n$("toggleRight").onclick=()=>{\n    wideMode=wideMode==="right"?"normal":"right";\n    applyWideMode();\n};\n\n$("focusMode").onclick=()=>{\n    wideMode=wideMode==="focus"?"normal":"focus";\n    applyWideMode();\n};\n\nconst wideObserver=new ResizeObserver(fitCanvas);\nwideObserver.observe(wideStage);\n\nwindow.addEventListener("resize",fitCanvas);\n\n$("format").addEventListener("change",()=>{\n    requestAnimationFrame(fitCanvas);\n});\n\nrequestAnimationFrame(fitCanvas);\n\n$("export").onclick=async()=>{\n    if(busy||!loaded)return;\n\n    if(!Number.isFinite(clip.duration)||clip.duration>120){\n        status("Export supports clips up to 120 seconds.");\n        return;\n    }\n\n    if(!window.MediaRecorder||!canvas.captureStream){\n        status("Browser recording unsupported. Use Chrome or Edge.");\n        return;\n    }\n\n    const types=[\n        \'video/mp4;codecs="avc1.42001f,mp4a.40.2"\',\n        "video/webm;codecs=vp9,opus",\n        "video/webm;codecs=vp8,opus",\n        "video/mp4",\n        "video/webm"\n    ];\n\n    const mime=types.find(type=>MediaRecorder.isTypeSupported(type));\n\n    if(!mime){\n        status("No supported recording format.");\n        return;\n    }\n\n    setBusy(true);\n    pause();\n\n    let recorder=null;\n    let stream=null;\n    let timer=null;\n    let endHandler=null;\n\n    try{\n        await setupAudio();\n        await seekStart(clip);\n\n        if(background instanceof HTMLVideoElement){\n            await seekStart(background,Number($("bgTime").value));\n        }\n\n        render();\n        stream=canvas.captureStream(30);\n\n        for(const track of audioDest.stream.getAudioTracks()){\n            stream.addTrack(track.clone());\n        }\n\n        recorder=new MediaRecorder(stream,{\n            mimeType:mime,\n            videoBitsPerSecond:5000000,\n            audioBitsPerSecond:128000\n        });\n\n        const chunks=[];\n\n        recorder.ondataavailable=e=>{\n            if(e.data.size)chunks.push(e.data);\n        };\n\n        const completed=new Promise((resolve,reject)=>{\n            recorder.onstop=()=>resolve(\n                new Blob(chunks,{type:recorder.mimeType||mime})\n            );\n            recorder.onerror=()=>reject(Error("Recording failed"));\n        });\n\n        completed.catch(()=>{});\n\n        endHandler=()=>{\n            render();\n            if(recorder.state!=="inactive")recorder.stop();\n        };\n\n        clip.addEventListener("ended",endHandler,{once:true});\n\n        recorder.start(250);\n\n        if(background instanceof HTMLVideoElement){\n            background.play().catch(()=>{});\n        }\n\n        await clip.play();\n\n        status("Exporting... keep this tab visible.");\n\n        const deadline=new Promise((resolve,reject)=>{\n            timer=setTimeout(\n                ()=>reject(Error("Export timed out")),\n                (clip.duration+15)*1000\n            );\n        });\n\n        const blob=await Promise.race([completed,deadline]);\n\n        if(!blob.size)throw Error("Empty recording");\n\n        if(blob.type.startsWith("video/mp4")){\n            download(blob,"mp4");\n            status("MP4 export ready.");\n        }else{\n            status("Converting recording to MP4...");\n\n            try{\n                const response=await fetch("export-mp4",{\n                    method:"POST",\n                    headers:{"Content-Type":"application/octet-stream"},\n                    body:blob\n                });\n\n                if(!response.ok){\n                    const result=await response.json();\n                    throw Error(result.error||"Conversion failed");\n                }\n\n                download(await response.blob(),"mp4");\n                status("MP4 export ready.");\n            }catch(e){\n                download(blob,"webm");\n                status("Saved WebM fallback: "+e.message);\n            }\n        }\n    }catch(e){\n        status("Export failed: "+e.message);\n    }finally{\n        clearTimeout(timer);\n        pause();\n\n        if(endHandler){\n            clip.removeEventListener("ended",endHandler);\n        }\n\n        if(recorder&&recorder.state!=="inactive")recorder.stop();\n\n        if(stream){\n            for(const track of stream.getTracks())track.stop();\n        }\n\n        setBusy(false);\n    }\n};\n</script>\n</body>\n</html>\n'

HTML = r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pulse Meme Studio v0.5.4</title>
<style>
*{box-sizing:border-box}
:root{color-scheme:dark}
body{margin:0;background:#0b1017;color:#e6edf3;
font:14px 'Segoe UI',Arial,sans-serif}
header{padding:20px 24px;border-bottom:1px solid #253344;
display:flex;align-items:center;justify-content:space-between}
h1{margin:0;color:#00d9ff;font-size:24px;letter-spacing:2px}
small{color:#8297ad}
.free{color:#7ee787}
.controls{padding:14px 24px;background:#101722;
border-bottom:1px solid #253344}
.row{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:9px}
.row:last-child{margin-bottom:0}
input,button{font:inherit;border:1px solid #34455b;
border-radius:7px;padding:10px 13px;background:#172332;color:#e6edf3}
input{flex:1;min-width:180px;outline:none}
input:focus{border-color:#00d9ff}
button{cursor:pointer}
button:hover{border-color:#00d9ff;color:#00d9ff}
button:disabled{opacity:.4;cursor:default}
.primary{background:#007e9a;color:white}
.active{border-color:#00d9ff;color:#00d9ff}
.layout{display:grid;grid-template-columns:minmax(0,1fr) 340px;
gap:18px;padding:18px 24px 90px}
.gallery{display:grid;
grid-template-columns:repeat(auto-fill,minmax(190px,1fr));
align-content:start;gap:14px}
.card{background:#151e29;border:1px solid #26364a;
border-radius:10px;overflow:hidden;cursor:pointer;min-width:0}
.card:hover,.selected{border-color:#00d9ff}
.thumb{aspect-ratio:16/9;background:#080c12;
display:flex;align-items:center;justify-content:center;overflow:hidden}
.thumb img{width:100%;height:100%;object-fit:contain}
.info{padding:10px}
.name{font-weight:600;min-height:38px;overflow-wrap:anywhere}
.meta{font-size:12px;color:#8297ad;margin:5px 0}
.cardbuttons{display:flex;gap:6px}
.cardbuttons button{font-size:12px;padding:7px;flex:1}
.preview{position:sticky;top:14px;align-self:start;
background:#151e29;border:1px solid #26364a;border-radius:10px;
padding:14px;min-width:0}
.preview h2{font-size:18px;overflow-wrap:anywhere}
.player{aspect-ratio:16/9;background:black;
border-radius:6px;overflow:hidden}
iframe,video{width:100%;height:100%;border:0}
.tags{color:#8297ad;line-height:1.6;overflow-wrap:anywhere}
.preview button{width:100%;margin-top:8px}
footer{position:fixed;bottom:0;left:0;right:0;
background:#111b28;border-top:1px solid #34455b;
padding:12px 24px;display:flex;gap:10px;align-items:center;
z-index:10;flex-wrap:wrap}
#status{color:#00d9ff;flex:1;min-width:120px}
@media(max-width:800px){
.layout{grid-template-columns:1fr}
.preview{position:static;grid-row:1}
.gallery{grid-template-columns:repeat(auto-fill,minmax(150px,1fr))}
footer{padding:8px}
}
</style>
</head>
<body>
<header>
<h1>PULSE / MEME STUDIO</h1>
<small class="free">V0.5.4 | FREE MODE</small>
</header>
<div class="controls">
<div class="row">
<input id="query" placeholder="Search memes, quotes, reactions...">
<button class="primary" id="search">Search</button>
<button id="trending">Trending</button>
<button id="paste">Paste Meme URL</button>
<button id="random">Random Meme</button>
</div>
<div class="row" id="filters">
<button data-category="reactions">Reactions</button>
<button data-category="funny">Funny</button>
<button data-tag="green-screen">Green Screen</button>
<button data-tag="rage">Rage</button>
<button data-tag="awkward">Awkward</button>
<button data-tag="laughing">Laughing</button>
<button data-category="sfx">Sound Effects</button>
<button id="favs">Favourites</button>
<button id="library">Local Library / Recent</button>
</div>
</div>
<div class="layout">
<main class="gallery" id="gallery"></main>
<aside class="preview" id="preview">
<small>MEME PREVIEW</small>
<h2>Select a meme</h2>
<div class="player"></div>
<p class="tags">Choose a clip to preview it with sound.</p>
</aside>
</div>
<footer>
<span id="status">Ready</span>
<button id="prev">Previous</button>
<button id="next">Next Page</button>
<button id="import">Import MP4</button>
<button id="openlib">Open Library</button>
<input type="file" id="files" accept=".mp4" multiple hidden>
</footer>
<script>
const $=id=>document.getElementById(id);
let items=[], saved=[], cursor=null, history=[];
let current={}, busy=false, view="remote", selection=null;

function status(s){$("status").textContent=s}

async function api(path,options={}){
    const response=await fetch(path,options);
    const data=await response.json();
    if(!response.ok)throw Error(data.error||"Request failed");
    return data;
}
function el(tag,cls,text){
    const node=document.createElement(tag);
    if(cls)node.className=cls;
    if(text!==undefined)node.textContent=text;
    return node;
}
function button(text,action){
    const b=el("button","",text);
    b.onclick=e=>{e.stopPropagation();action()};
    return b;
}
function external(url){
    window.open(url,"_blank","noopener,noreferrer");
}
function isFav(c){return saved.some(x=>x.id===c.id)}
function page(c){return "https://clipkaboom.com/c/"+encodeURIComponent(c.id)}
function embed(c){return "https://clipkaboom.com/embed/"+encodeURIComponent(c.id)}

function poster(c){
    try{
        const url=new URL(c.media_formats.poster.url);
        if(url.origin==="https://api.clipkaboom.com"
          && url.pathname.startsWith("/poster/"))return url.href;
    }catch(e){}
    return "";
}
const localObserver=new IntersectionObserver(entries=>{
        for(const entry of entries){
            if(entry.isIntersecting){
                const video=entry.target;
                video.src=video.dataset.src;
                localObserver.unobserve(video);
            }
        }
    });

    function editMeme(c){
        window.open(
            "editor?name="+encodeURIComponent(c.name),
            "_blank","noopener"
        );
    }

    function show(){
        localObserver.disconnect();
    const gallery=$("gallery");
    gallery.replaceChildren();
    if(!items.length)gallery.append(el("p","","No clips found."));
    for(const c of items){
        const card=el("article","card");
        if(c===selection)card.classList.add("selected");
        const thumb=el("div","thumb");
        const url=poster(c);
        if(url&&!c.local){
            const img=el("img");
            img.src=url;
            img.loading="lazy";
            img.alt=c.title;
            img.onerror=()=>thumb.replaceChildren(el("small","","Preview unavailable"));
            thumb.append(img);
        }else if(c.local){
        const video=el("video");
        video.muted=true;
        video.playsInline=true;
        video.preload="metadata";
        video.style.objectFit="contain";
        video.dataset.src="media?name="+encodeURIComponent(c.name);
        video.onloadedmetadata=()=>{
            if(Number.isFinite(video.duration)){
                video.currentTime=Math.min(0.25,video.duration/3);
            }
        };
        thumb.append(video);
        localObserver.observe(video);
    }else thumb.append(el("small","","VIDEO"));
        const info=el("div","info");
        info.append(el("div","name",c.title||"Untitled"));
        let meta=c.local?"Local video":(c.duration??"?")+"s";
        if(c.tags?.includes("green-screen"))meta+=" | GREEN SCREEN";
        info.append(el("div","meta",meta));
        const actions=el("div","cardbuttons");
        actions.append(button("Preview",()=>select(c,true)));
        if(c.local){
            actions.append(button("Edit",()=>editMeme(c)));
        }else{
            actions.append(button(isFav(c)?"Saved":"Save",()=>toggle(c)));
            actions.append(button("Get MP4",()=>downloadFree(c)));
        }
        info.append(actions);
        card.append(thumb,info);
        card.onclick=()=>select(c,true);
        gallery.append(card);
    }
    $("next").disabled=busy||view!=="remote"||!cursor;
    $("prev").disabled=busy||view!=="remote"||!history.length;
}
async function copyPath(c){
    try{
        await navigator.clipboard.writeText(c.path);
        status("Video path copied. Paste into Pulse Capture.");
    }catch(e){window.prompt("Copy this video path:",c.path)}
}
function select(c,play=false){
    selection=c;
    const panel=$("preview");
    panel.replaceChildren(el("small","","MEME PREVIEW"),el("h2","",c.title));
    const player=el("div","player");
    if(c.local){
        const video=el("video");
        video.src="media?name="+encodeURIComponent(c.name);
        video.controls=true;
        player.append(video);
    }else if(play){
        const frame=el("iframe");
        frame.src=embed(c);
        frame.allow="autoplay; fullscreen";
        frame.allowFullscreen=true;
        frame.referrerPolicy="no-referrer";
        player.append(frame);
    }
    panel.append(player);
    if(c.local){
        panel.append(button("OPEN MEME EDITOR",()=>editMeme(c)));
        panel.append(button("Copy path for Pulse Capture",()=>copyPath(c)));
    }else{
        panel.append(el("p","tags",[...new Set(c.tags||[])].slice(0,14).join(" / ")));
        panel.append(button("Open external preview",()=>external(embed(c))));
        panel.append(button("Download FREE MP4",()=>downloadFree(c)));
        panel.append(button("Official download page",()=>external(page(c))));
        panel.append(button(isFav(c)?"Remove favourite":"Add favourite",()=>toggle(c)));
    }
    show();
}
function clearPreview(){
    selection=null;
    $("preview").replaceChildren(
        el("small","","MEME PREVIEW"),
        el("h2","","Select a meme"),
        el("div","player")
    );
}
async function toggle(c){
    try{
        saved=await api("favourites",{
            method:"POST",
            headers:{"Content-Type":"application/json"},
            body:JSON.stringify(c)
        });
        if(view==="favourites")items=saved;
        if(selection===c)clearPreview();
        show();
        status(isFav(c)?"Saved to favourites":"Favourite removed");
    }catch(e){status(e.message)}
}
async function load(params,trail=[]){
    if(busy)return;
    busy=true;
    status("Loading memes...");
    try{
        const data=await api("search?"+new URLSearchParams(params));
        view="remote";
        current=params;
        cursor=data.next;
        history=trail;
        items=data.results;
        clearPreview();
        status(items.length+" memes found");
    }catch(e){status(e.message)}
    finally{busy=false;show()}
}
async function localView(kind){
    if(busy)return;
    busy=true;
    try{
        const data=await api(kind);
        view=kind;
        items=data;
        if(kind==="favourites")saved=data;
        clearPreview();
        status(items.length+" saved clips");
    }catch(e){status(e.message)}
    finally{busy=false;show()}
}

let downloading=false;

async function downloadFree(c){
    if(downloading||busy){
        status("Please wait for the current request.");
        return;
    }

    downloading=true;
    status("Downloading free watermarked MP4: "+c.title);

    try{
        const result=await api("download-free",{
            method:"POST",
            headers:{"Content-Type":"application/json"},
            body:JSON.stringify({id:c.id})
        });

        status(result.existing
            ?"Already in local library"
            :"Downloaded: "+result.name);

        const files=await api("library");
        const file=files.find(x=>x.name===result.name);

        if(file){
            view="library";
            items=files;
            select(file,true);
        }
    }catch(e){
        status("Download unavailable: "+e.message);
        if(confirm("Free download failed. Open official download page?")){
            external(page(c));
        }
    }finally{
        downloading=false;
    }
}

async function pasteMeme(){
    if(busy)return;

    const input=prompt("Paste a ClipKaboom page URL or embed code:");
    if(!input)return;

    const match=input.match(
        /https:\/\/(?:www\.)?clipkaboom\.com\/(?:c|embed)\/([A-Za-z0-9_-]+)(?=$|[?&#/"'\s<>])/
    );

    if(!match){
        status("Please paste a valid ClipKaboom URL or embed.");
        return;
    }

    busy=true;
    try{
        const clip=await api("clip?id="+encodeURIComponent(match[1]));
        view="lookup";
        items=[clip];
        cursor=null;
        history=[];
        select(clip,true);
        status("Found: "+clip.title);
    }catch(e){
        status(e.message);
    }finally{
        busy=false;
        show();
    }
}

$("paste").onclick=pasteMeme;

$("random").onclick=()=>{
    if(busy)return;

    const pool=items.filter(c=>!c.local&&c!==selection);

    if(!pool.length){
        status("Load a meme gallery first.");
        return;
    }

    const clip=pool[Math.floor(Math.random()*pool.length)];
    select(clip,true);
    status("Random pick: "+clip.title);
};

$("search").onclick=()=>load({q:$("query").value.trim()});
$("query").onkeydown=e=>{if(e.key==="Enter")$("search").click()};
$("trending").onclick=()=>load({mode:"trending"});
document.querySelectorAll("[data-category],[data-tag]").forEach(b=>{
    b.onclick=()=>load({
        q:$("query").value.trim(),
        ...(b.dataset.category?{category:b.dataset.category}:{tag:b.dataset.tag})
    });
});
$("next").onclick=()=>load({...current,cursor},[...history,current]);
$("prev").onclick=()=>{
    if(history.length)load(history.at(-1),history.slice(0,-1));
};
$("favs").onclick=()=>localView("favourites");
$("library").onclick=()=>localView("library");
$("import").onclick=()=>$("files").click();
$("files").onchange=async()=>{
    for(const file of $("files").files){
        try{
            status("Importing "+file.name);
            await api("import?name="+encodeURIComponent(file.name),{
                method:"POST",
                headers:{"Content-Type":"application/octet-stream"},
                body:file
            });
        }catch(e){alert(e.message)}
    }
    $("files").value="";
    await localView("library");
};
$("openlib").onclick=async()=>{
    try{
        await api("open-library",{
            method:"POST",
            headers:{"Content-Type":"application/json"},
            body:"{}"
        });
    }catch(e){status(e.message)}
};
(async()=>{
    try{saved=await api("favourites")}catch(e){}
    await load({mode:"trending"});
})();
</script>
</body>
</html>
"""

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, data, code=200):
        raw = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def route(self):
        expected = "127.0.0.1:" + str(self.server.server_port)
        if self.headers.get("Host") != expected:
            raise ValueError("Invalid host")
        parsed = urllib.parse.urlsplit(self.path)
        if not parsed.path.startswith(PREFIX):
            raise ValueError("Invalid session")
        params = dict(urllib.parse.parse_qsl(parsed.query))
        return parsed.path[len(PREFIX):], params

    def do_GET(self):
        try:
            route, params = self.route()

            if route == "":
                raw = HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Content-Security-Policy",
                    "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                    "style-src 'self' 'unsafe-inline'; "
                    "img-src 'self' https://api.clipkaboom.com; "
                    "frame-src https://clipkaboom.com; "
                    "media-src 'self'; frame-ancestors 'none'; base-uri 'none'")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            elif route == "search":
                self.reply(search(params))

            elif route == "editor":
                raw = EDITOR_HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; "
                    "script-src 'self' 'unsafe-inline'; "
                    "style-src 'self' 'unsafe-inline'; "
                    "img-src 'self' blob: data:; "
                    "media-src 'self' blob:; "
                    "frame-ancestors 'none'; base-uri 'none'"
                )
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            elif route == "clip":
                self.reply(get_clip(params.get("id", "")))

            elif route == "favourites":
                self.reply(favourites())

            elif route == "library":
                self.reply(library())

            elif route == "media":
                self.media(params.get("name", ""))

            else:
                self.reply({"error": "Not found"}, 404)

        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            self.reply({"error": str(exc)}, 400)

    def media(self, name):
        if Path(name).name != name or not name.lower().endswith(".mp4"):
            raise ValueError("Invalid filename")
        path = LIB / name
        if not path.is_file() or path.is_symlink():
            raise ValueError("Video not found")

        size = path.stat().st_size
        if not size:
            raise ValueError("Empty video")

        start, end = 0, size - 1
        partial = False
        requested = self.headers.get("Range")

        if requested:
            m = re.fullmatch(r"bytes=(\d*)-(\d*)", requested)
            if not m or not any(m.groups()):
                self.send_error(416)
                return
            if m[1]:
                start = int(m[1])
                end = min(end, int(m[2])) if m[2] else end
            else:
                start = max(0, size - int(m[2]))
            if start > end or start >= size:
                self.send_error(416)
                return
            partial = True

        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end-start+1))
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()

        with path.open("rb") as f:
            f.seek(start)
            remaining = end-start+1
            while remaining:
                chunk = f.read(min(65536, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def do_POST(self):
        try:
            route, params = self.route()
            origin = "http://127.0.0.1:" + str(self.server.server_port)
            if self.headers.get("Origin") != origin:
                raise ValueError("Invalid request origin")

            size = int(self.headers.get("Content-Length", "0"))
            if size < 1:
                raise ValueError("Empty request")

            if route == "import":
                if size > 100 * 1024 * 1024:
                    raise ValueError("Maximum import size is 100 MB")
                name = Path(params.get("name", "")).name
                if not name.lower().endswith(".mp4"):
                    raise ValueError("MP4 files only")
                name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)

                data = self.rfile.read(size)
                if len(data) != size or b"ftyp" not in data[:64]:
                    raise ValueError("Invalid MP4 file")

                with LOCK:
                    path = LIB / name
                    n = 2
                    while path.exists():
                        path = LIB / (Path(name).stem + f"-{n}.mp4")
                        n += 1
                    path.write_bytes(data)
                self.reply({"ok": True})

            elif route == "export-mp4":
                if size > 160 * 1024 * 1024:
                    raise ValueError("Recording too large")

                data = self.rfile.read(size)

                if len(data) != size:
                    raise ValueError("Incomplete recording")

                output = convert_recording(data)

                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(len(output)))
                self.end_headers()
                self.wfile.write(output)

            elif route == "download-free":
                if size > 4096:
                    raise ValueError("Request too large")
                body = json.loads(self.rfile.read(size))
                self.reply(download_free(body.get("id")))

            elif route == "favourites":
                if size > 65536:
                    raise ValueError("Request too large")
                c = json.loads(self.rfile.read(size))
                if not valid(c):
                    raise ValueError("Invalid meme")
                with LOCK:
                    saved = favourites()
                    if any(x["id"] == c["id"] for x in saved):
                        saved = [x for x in saved if x["id"] != c["id"]]
                    else:
                        saved.append(c)
                    tmp = FAV.with_suffix(".tmp")
                    tmp.write_text(json.dumps(saved, indent=2), encoding="utf-8")
                    tmp.replace(FAV)
                self.reply(saved)

            elif route == "open-library":
                if size > 1024:
                    raise ValueError("Request too large")
                self.rfile.read(size)
                import os
                os.startfile(str(LIB))
                self.reply({"ok": True})

            else:
                self.reply({"error": "Not found"}, 404)

        except Exception as exc:
            self.reply({"error": str(exc)}, 400)

server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
url = f"http://127.0.0.1:{server.server_port}{PREFIX}"

print("\nPULSE MEME STUDIO v0.5.4")
print("FREE MODE - No API key")
print("Local library:", LIB)
print("Press Ctrl+C to stop.")
webbrowser.open(url)

try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    server.server_close()
