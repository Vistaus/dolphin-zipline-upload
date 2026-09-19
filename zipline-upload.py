#!/usr/bin/env python3
"""Zipline Upload for Dolphin — a KDE Plasma 6 context-menu uploader.

Invoked from a Dolphin service menu (right click → Upload to Zipline) to
upload the selected file(s) to a self-hosted Zipline instance, with:

  * a settings GUI: a dark-themed PySide6 window when available (private
    venv), kdialog menus otherwise — configured via --configure
  * import of Zipline-generated shell uploader scripts
  * live upload progress via a kdialog progress bar (with Cancel) or a
    Plasma notification with a progress hint
  * post-upload actions: copy URL to clipboard (Klipper/wl-copy/xclip/xsel),
    open in browser, notification
  * an optional user hook (~/.config/zipline-upload/hook.py) for custom
    post-upload behaviour

Standard library only — no pip dependencies. Tested with Python 3.8+.

Usage:
  zipline-upload.py FILE [FILE ...]      upload file(s)
  zipline-upload.py --configure          open the settings GUI
  zipline-upload.py --import-script PATH import settings from a Zipline script
  zipline-upload.py --status             print current settings (token masked)
  zipline-upload.py --test               run a connection test
  zipline-upload.py --version            print version
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.parse
import uuid
from datetime import datetime, timezone
from http.client import HTTPConnection, HTTPSConnection, HTTPException

VERSION = "1.1.0"
APP_NAME = "Zipline Upload"
ICON = "cloud-upload"

CONFIG_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
    "zipline-upload",
)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
STATE_DIR = os.path.join(
    os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")),
    "zipline-upload",
)
LOG_PATH = os.path.join(STATE_DIR, "zipline-upload.log")
HISTORY_PATH = os.path.join(STATE_DIR, "history.jsonl")
HOOK_PATH = os.path.join(CONFIG_DIR, "hook.py")

# Where install.sh (and the optional PySide6 venv setup) put things.
APP_DATA_DIR = os.path.join(
    os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")),
    "zipline-upload",
)
VENV_DIR = os.path.join(APP_DATA_DIR, "venv")
VENV_PYTHON = os.path.join(VENV_DIR, "bin", "python")
# The Qt GUI module always sits next to this file, wherever it lives
# (repo checkout, ~/.local/share/zipline-upload, or a servicemenus install).
GUI_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "zipline_gui.py")

FORMAT_CHOICES = [("", "Server default"), ("name", "Keep original name"),
                  ("random", "Random"), ("uuid", "Random UUID"),
                  ("date", "Date"), ("gfycat", "Gfycat style")]
COMPRESSION_TYPES = ["jpg", "png", "webp", "jxl"]
POST_ACTIONS = [
    ("copy", "Copy URL(s) to clipboard"),
    ("copy_open", "Copy URL(s) and open in browser"),
    ("open", "Open URL(s) in browser"),
    ("notify", "Show notification only"),
    ("none", "Do nothing"),
]
CLIPBOARD_TOOLS = [
    ("auto", "Auto-detect (recommended)"),
    ("klipper", "Klipper (Plasma)"),
    ("wl-copy", "wl-copy (Wayland)"),
    ("xclip", "xclip (X11)"),
    ("xsel", "xsel (X11)"),
]
PROGRESS_MODES = [
    ("progressbar", "Progress bar dialog (kdialog)"),
    ("notification", "Progress notification"),
    ("none", "No progress display"),
]

# Query params of older Zipline scripts mapped to x-zipline-* headers.
QUERY_TO_HEADER = {
    "format": "x-zipline-format",
    "imagecompression": "x-zipline-image-compression-percent",
    "imagecompressiontype": "x-zipline-image-compression-type",
    "password": "x-zipline-password",
    "maxviews": "x-zipline-max-views",
    "originalname": "x-zipline-original-name",
    "extensionless": "x-zipline-extensionless",
}


class ZiplineError(Exception):
    """User-facing upload error."""


class UploadCancelled(Exception):
    """The user pressed Cancel in the progress dialog."""


# --------------------------------------------------------------------------- #
#  Small helpers
# --------------------------------------------------------------------------- #

def log(message: str) -> None:
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"{stamp} {message}\n")
    except OSError:
        pass  # logging must never break an upload


def run(cmd, **kwargs):
    """Run a subprocess without a shell; returns CompletedProcess."""
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def have(binary: str) -> bool:
    return shutil.which(binary) is not None


def human_size(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or unit == "TiB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TiB"


def mask(token: str) -> str:
    if not token:
        return "(not set)"
    if len(token) <= 8:
        return token[:2] + "…"
    return f"{token[:4]}…{token[-4:]}"


# --------------------------------------------------------------------------- #
#  Configuration
# --------------------------------------------------------------------------- #

DEFAULTS = {
    "url": "",                # full upload endpoint, e.g. https://host/api/upload
    "token": "",              # stored token ("") — never logged
    "use_env_token": False,   # read token from $ZIPLINE_TOKEN at runtime instead
    "format": "",             # x-zipline-format: ""|name|random|uuid|date|gfycat
    "original_name": False,   # x-zipline-original-name
    "compress": False,        # x-zipline-image-compression-percent
    "compress_percent": 80,
    "compress_type": "jpg",   # x-zipline-image-compression-type
    "password": "",           # x-zipline-password
    "max_views": None,        # x-zipline-max-views
    "deletes_at": "",         # x-zipline-deletes-at, e.g. "1d"
    "extensionless": False,   # x-zipline-extensionless
    "extra_headers": {},      # any other x-zipline-* headers, e.g. folder id
    "post_action": "copy",
    "clipboard_tool": "auto",
    "notify_done": True,
    "progress_ui": "progressbar",
    "timeout": 30,
}


def load_config(path: str = CONFIG_PATH) -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(path, encoding="utf-8") as fh:
            stored = json.load(fh)
        if isinstance(stored, dict):
            cfg.update({k: v for k, v in stored.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg: dict, path: str = CONFIG_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.chmod(tmp, 0o600)  # config may contain the upload token
    os.replace(tmp, path)


def effective_config(cfg: dict) -> dict:
    """Apply environment overrides ($ZIPLINE_URL, $ZIPLINE_TOKEN)."""
    eff = dict(cfg)
    if os.environ.get("ZIPLINE_URL"):
        try:
            eff["url"] = normalize_endpoint(os.environ["ZIPLINE_URL"])
        except ZiplineError as exc:
            log(f"ignoring invalid $ZIPLINE_URL: {exc}")
    if os.environ.get("ZIPLINE_TOKEN"):
        eff["token"] = os.environ["ZIPLINE_TOKEN"]
    return eff


def normalize_endpoint(url: str) -> str:
    """Accept 'https://host', 'https://host/zipline' or a full /api/upload URL."""
    url = (url or "").strip()
    if not url:
        raise ZiplineError("Server URL is empty.")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https"):
        raise ZiplineError(
            f"Server URL must start with http:// or https:// — got {url!r}."
        )
    if not parsed.hostname:
        raise ZiplineError(f"Server URL has no host: {url!r}")
    base = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
    if not base.endswith("/api/upload"):
        base += "/api/upload"
    return base


def server_origin(endpoint: str) -> str:
    parsed = urllib.parse.urlsplit(endpoint)
    return f"{parsed.scheme}://{parsed.netloc}"


def config_is_valid(cfg: dict) -> bool:
    try:
        normalize_endpoint(cfg.get("url", ""))
    except ZiplineError:
        return False
    return bool(cfg.get("token")) or bool(cfg.get("use_env_token") and
                                          os.environ.get("ZIPLINE_TOKEN"))


def build_headers(cfg: dict) -> dict:
    """Translate config into x-zipline-* request headers (empty values skipped)."""
    h = {}
    if cfg.get("format"):
        h["x-zipline-format"] = str(cfg["format"])
    if cfg.get("original_name"):
        h["x-zipline-original-name"] = "true"
    if cfg.get("compress"):
        h["x-zipline-image-compression-percent"] = str(int(cfg.get("compress_percent", 80)))
        h["x-zipline-image-compression-type"] = str(cfg.get("compress_type", "jpg"))
    if cfg.get("password"):
        h["x-zipline-password"] = str(cfg["password"])
    if cfg.get("max_views"):
        h["x-zipline-max-views"] = str(int(cfg["max_views"]))
    if cfg.get("deletes_at"):
        h["x-zipline-deletes-at"] = str(cfg["deletes_at"])
    if cfg.get("extensionless"):
        h["x-zipline-extensionless"] = "true"
    for key, value in (cfg.get("extra_headers") or {}).items():
        key = key.strip().lower()
        if key and value not in (None, ""):
            h[key] = str(value)
    return h


def config_summary(cfg: dict) -> str:
    eff = effective_config(cfg)
    lines = [
        f"Server endpoint:   {eff.get('url') or '(not set)'}",
        f"Token:             {mask(eff.get('token', ''))}"
        + ("  (from $ZIPLINE_TOKEN)" if eff.get("use_env_token") else ""),
        f"Filename format:   {eff.get('format') or 'server default'}",
        f"Original name:     {'yes' if eff.get('original_name') else 'no'}",
        f"Image compression: "
        + (f"{eff.get('compress_percent')}% {eff.get('compress_type')}" if eff.get("compress") else "off"),
        f"Password protect:  {'yes' if eff.get('password') else 'no'}",
        f"Auto-delete after: {eff.get('deletes_at') or 'never'}",
        f"Max views:         {eff.get('max_views') or 'unlimited'}",
        f"Extensionless URL: {'yes' if eff.get('extensionless') else 'no'}",
        f"Extra headers:     {eff.get('extra_headers') or 'none'}",
        f"After upload:      {dict(POST_ACTIONS).get(eff.get('post_action'), '?')}",
        f"Clipboard tool:    {eff.get('clipboard_tool')}",
        f"Completion notify: {'yes' if eff.get('notify_done') else 'no'}",
        f"Progress display:  {eff.get('progress_ui')}",
        f"Timeout:           {eff.get('timeout')} s",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
#  Zipline script importer
# --------------------------------------------------------------------------- #

def parse_zipline_script(text: str) -> dict:
    """Extract endpoint, token and x-zipline-* options from a Zipline script.

    Supports both generated scripts (inline curl arguments) and the DIY style
    (TOKEN=/URL= variables) documented at zipline.diced.sh.
    Returns {endpoint, token, headers, raw_url}.
    """
    # Shell variable assignments (DIY scripts use TOKEN= / URL= / SERVER=).
    variables = dict(
        (m.group(1), m.group(2))
        for m in re.finditer(
            r'^\s*(?:export\s+)?(TOKEN|URL|SERVER)\s*=\s*["\']([^"\']+)["\']',
            text, re.IGNORECASE | re.MULTILINE))

    def resolve(value: str) -> str:
        """Follow $VAR / ${VAR} references between the assignments."""
        seen = set()
        while value.startswith("$") and value.lstrip("$").strip("{}") in variables:
            name = value.lstrip("$").strip("{}")
            if name in seen:
                break
            seen.add(name)
            value = variables[name]
        return value if not value.startswith("$") else ""

    token = ""
    auth = re.search(r"authorization:\s*([^\s'\"]+)", text, re.IGNORECASE)
    if auth:
        token = resolve(auth.group(1))
    if not token:
        token = variables.get("TOKEN", "")

    raw_url = ""
    if "URL" in variables:
        raw_url = resolve(variables["URL"])
    if not raw_url:
        candidates = re.findall(r"https?://[^\s'\"|;]+", text)
        for candidate in candidates:
            if "/api/upload" in candidate:
                raw_url = candidate
                break
        else:
            candidates = [c.rstrip(",);") for c in candidates]
            raw_url = candidates[0] if candidates else ""
    raw_url = raw_url.strip().rstrip(",);")
    if not raw_url:
        raise ZiplineError("No upload URL found in the script.")

    headers = {}
    for match in re.finditer(
            r"['\"]x-zipline-([a-z0-9\-]+)\s*:\s*([^'\"]+)['\"]", text, re.IGNORECASE):
        headers[f"x-zipline-{match.group(1).lower()}"] = match.group(2).strip()

    # Older scripts passed options as /api/upload?query=params — fold the ones
    # we understand into headers.
    parts = urllib.parse.urlsplit(raw_url)
    if parts.query:
        for key, value in urllib.parse.parse_qsl(parts.query):
            header = QUERY_TO_HEADER.get(key.lower())
            if header and header not in headers:
                headers[header] = value

    endpoint = normalize_endpoint(raw_url)
    return {"endpoint": endpoint, "token": token, "headers": headers,
            "raw_url": raw_url}


def apply_imported(cfg: dict, parsed: dict) -> dict:
    """Merge parse_zipline_script() output into a config dict."""
    cfg = dict(cfg)
    cfg["url"] = parsed["endpoint"]
    if parsed["token"]:
        cfg["token"] = parsed["token"]
        cfg["use_env_token"] = False
    headers = dict(parsed["headers"])
    if headers.get("x-zipline-format"):
        cfg["format"] = headers.pop("x-zipline-format")
    if headers.get("x-zipline-original-name"):
        cfg["original_name"] = headers.pop("x-zipline-original-name").lower() == "true"
    if headers.get("x-zipline-image-compression-percent"):
        try:
            cfg["compress"] = True
            cfg["compress_percent"] = int(headers.pop("x-zipline-image-compression-percent"))
            ctype = headers.pop("x-zipline-image-compression-type", "")
            if ctype:
                cfg["compress_type"] = ctype.lower()
        except ValueError:
            pass
    if headers.get("x-zipline-password"):
        cfg["password"] = headers.pop("x-zipline-password")
    if headers.get("x-zipline-max-views"):
        try:
            cfg["max_views"] = int(headers.pop("x-zipline-max-views"))
        except ValueError:
            pass
    if headers.get("x-zipline-deletes-at"):
        cfg["deletes_at"] = headers.pop("x-zipline-deletes-at")
    if headers.get("x-zipline-extensionless"):
        cfg["extensionless"] = headers.pop("x-zipline-extensionless").lower() == "true"
    headers.pop("x-zipline-no-json", None)  # we always parse JSON ourselves
    if headers:
        cfg["extra_headers"] = headers
    return cfg


def reconcile_import(current: dict, parsed: dict) -> dict:
    """Merge an imported Zipline script over the current config.

    This is the addon's import policy — a product decision rather than
    plumbing, so it lives in one place and both settings UIs (the Qt window
    and the kdialog fallback) call it. The defaults below: URL and token
    always come from the script (they are a matched pair); anything the
    script doesn't mention keeps the user's own setting; desktop behaviour
    (actions, clipboard, notifications, timeout) is never touched by an
    import. Customise freely — e.g. "never overwrite a manually-set
    password", "always reset upload options on import", or "ask first when
    the token differs".
    """
    merged = apply_imported(current, parsed)
    # The script cannot express these — always keep the user's own choices.
    for key in ("post_action", "clipboard_tool", "notify_done",
                "progress_ui", "timeout", "use_env_token"):
        merged[key] = current.get(key, DEFAULTS[key])
    return merged


# --------------------------------------------------------------------------- #
#  Upload
# --------------------------------------------------------------------------- #

def guess_mime(path: str) -> str:
    """Prefer `file --mime-type` (matches Zipline's own script), fall back to
    Python's mimetypes, then application/octet-stream."""
    if have("file"):
        proc = run(["file", "--mime-type", "-b", path])
        mime = proc.stdout.strip()
        if proc.returncode == 0 and "/" in mime and " " not in mime:
            return mime
    mime, _ = mimetypes.guess_type(path)
    return mime or "application/octet-stream"


def _disposition(filename: str) -> str:
    """RFC 7578 Content-Disposition. Pure-ASCII names go in a plain quoted
    string; anything else uses RFC 5987 (filename*=UTF-8'') because server-side
    multipart parsers decode unencoded header bytes as latin-1."""
    if all(ord(ch) < 128 for ch in filename):
        return f'filename="{filename}"'
    quoted = urllib.parse.quote(filename, safe="")
    return f"filename*=UTF-8''{quoted}"


def extract_urls(payload, endpoint: str) -> list:
    """Pull URL list out of a Zipline upload response ({"files":[…]}, […] or
    a bare object; plain-text URL responses also tolerated)."""
    if isinstance(payload, str):
        stripped = payload.strip()
        if stripped.startswith(("http://", "https://")):
            return [line for line in stripped.splitlines()
                    if line.startswith(("http://", "https://"))]
        raise ZiplineError(f"Unexpected server response: {stripped[:200]}")
    if isinstance(payload, dict) and "files" in payload:
        items = payload["files"]
    elif isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = [payload]
    else:
        raise ZiplineError("Unexpected server response format.")
    urls = []
    for item in items:
        if isinstance(item, dict) and item.get("url"):
            urls.append(urllib.parse.urljoin(endpoint, str(item["url"])))
    if not urls:
        raise ZiplineError("Server response contained no file URL.")
    return urls


def upload_file(endpoint: str, token: str, path: str, *,
                option_headers: dict | None = None, timeout: int = 30,
                progress=None, name_for_label: str = None) -> list:
    """Upload one file to Zipline; returns a list of URLs (usually one).

    Streams the multipart body with http.client so memory use stays flat and
    progress is byte-accurate. Raises ZiplineError with a readable message.
    """
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise ZiplineError(f"Not a file: {path}")
    size = os.path.getsize(path)
    mime = guess_mime(path)
    display_name = name_for_label or os.path.basename(path)

    boundary = "----ZiplineDolphin" + uuid.uuid4().hex
    head = (
        f"--{boundary}\r\n"
        f"Content-Disposition: form-data; name=\"file\"; {_disposition(display_name)}\r\n"
        f"Content-Type: {mime}\r\n\r\n"
    ).encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("ascii")
    total = len(head) + size + len(tail)

    class _Body:
        """File-like multipart body; reports progress and Cancel presses.
        http.client streams it in fixed-size read() calls (no full buffering)."""

        def __init__(self):
            self.sent = 0
            self._head = head
            self._tail = tail
            self._fh = open(path, "rb")
            self._file_done = False
            self._eof = False

        def __len__(self):  # lets http.client verify length if it wants
            return total

        def read(self, n=-1):
            if self._eof:
                return b""
            if progress is not None:
                progress.check_cancel()
            want = None if n is None or n < 0 else n
            parts = []
            if self._head:
                chunk = self._head if want is None else self._head[:want]
                self._head = self._head[len(chunk):]
                parts.append(chunk)
                if want is not None:
                    want -= len(chunk)
            if not self._file_done and (want is None or want > 0):
                data = self._fh.read() if want is None else self._fh.read(want)
                if not data or (want is not None and len(data) < want):
                    self._file_done = True
                    self._fh.close()
                if data:
                    parts.append(data)
                    if want is not None:
                        want -= len(data)
            if self._file_done and self._head == b"" and (want is None or want > 0):
                chunk = self._tail if want is None else self._tail[:want]
                self._tail = self._tail[len(chunk):]
                parts.append(chunk)
            data = b"".join(parts)
            self.sent += len(data)
            if not self._head and self._file_done and not self._tail:
                self._eof = True
            if progress is not None and data:
                progress.update(self.sent, total, display_name)
            return data

        def close(self):
            try:
                self._fh.close()
            except OSError:
                pass

    parts = urllib.parse.urlsplit(endpoint)
    if parts.scheme == "https":
        conn = HTTPSConnection(parts.hostname, parts.port or 443,
                               timeout=timeout,
                               context=ssl.create_default_context())
    else:
        conn = HTTPConnection(parts.hostname, parts.port or 80, timeout=timeout)

    body = _Body()
    headers = {
        "Authorization": token,
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(total),
        "User-Agent": f"zipline-dolphin/{VERSION}",
        "Accept": "application/json, text/plain",
    }
    headers.update({k: str(v) for k, v in (option_headers or {}).items()})

    try:
        if progress is not None:
            progress.start(f"Uploading {display_name}")
        conn.request("POST", parts.path or "/", body=body, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
    except socket.timeout:
        raise ZiplineError(f"Connection timed out after {timeout}s "
                           f"({urllib.parse.urlsplit(endpoint).hostname}).")
    except (OSError, HTTPException) as exc:
        raise ZiplineError(f"Connection failed: {exc}") from exc
    finally:
        body.close()
        conn.close()

    text = raw.decode("utf-8", errors="replace")
    if resp.status in (200, 201):
        try:
            payload = json.loads(text)
        except ValueError:
            payload = text  # plain-text URL response
        urls = extract_urls(payload, endpoint)
        log(f"OK {resp.status} {display_name} ({human_size(size)}) -> {urls[0]}")
        return urls

    # Errors: surface Zipline's own JSON message when present.
    message = ""
    try:
        message = json.loads(text).get("error", "")
    except (ValueError, AttributeError):
        pass
    reason = {
        401: "Invalid or missing token — check Settings → Token.",
        403: "Server refused the upload (forbidden).",
        413: "File is larger than the server's upload limit.",
    }.get(resp.status, "")
    detail = f": {message}" if message else ""
    hint = f" ({reason})" if reason else ""
    raise ZiplineError(f"Upload failed — HTTP {resp.status}{hint}{detail}")


def _http_request(endpoint: str, method: str, token: str, *,
                  body=None, timeout: int = 10):
    """One-shot HTTP(S) request helper; returns (status, text)."""
    parts = urllib.parse.urlsplit(endpoint)
    if parts.scheme == "https":
        conn = HTTPSConnection(parts.hostname, parts.port or 443, timeout=timeout,
                               context=ssl.create_default_context())
    else:
        conn = HTTPConnection(parts.hostname, parts.port or 80, timeout=timeout)
    headers = {"User-Agent": f"zipline-dolphin/{VERSION}",
               "Accept": "application/json, text/plain"}
    if token:
        headers["Authorization"] = token
    if body is not None:
        headers["Content-Type"] = "application/json"
    try:
        conn.request(method, parts.path or "/", body=body, headers=headers)
        resp = conn.getresponse()
        text = resp.read().decode("utf-8", errors="replace")
        return resp.status, text
    finally:
        conn.close()


def run_connection_test(cfg: dict) -> str:
    """Upload one tiny test file, then try to delete it again via the API.
    Returns a readable result message for the settings GUI / --test."""
    eff = effective_config(cfg)
    if not config_is_valid(eff):
        return "Set the server URL and token first."
    endpoint, token = eff["url"], eff["token"]
    origin = server_origin(endpoint)
    timeout = min(int(eff.get("timeout", 30)), 15)

    # Reachability probe first, so we can distinguish "server down" from
    # "bad token" (404 on /api/version is fine — older servers lack it).
    version = ""
    try:
        status, text = _http_request(f"{origin}/api/version", "GET", token="",
                                     timeout=8)
        if status == 200:
            try:
                version = json.loads(text).get("version", "")
            except (ValueError, AttributeError):
                pass
    except (OSError, HTTPException, socket.timeout):
        pass  # reported via the upload attempt below

    with tempfile.NamedTemporaryFile(
            prefix="zipline-dolphin-test-", suffix=".txt",
            mode="w", encoding="utf-8", delete=False) as tmp:
        tmp.write("zipline-dolphin connection test\n")
        tmp_name = tmp.name
    try:
        try:
            urls = upload_file(endpoint, token, tmp_name,
                               option_headers={"x-zipline-format": "uuid"},
                               timeout=timeout)
        finally:
            os.unlink(tmp_name)
    except ZiplineError as exc:
        return f"Connection test FAILED:\n\n{exc}"
    message = (f"Connection test OK — upload succeeded.\n\n"
               f"Server: {origin}"
               + (f"  (Zipline {version})" if version else "")
               + f"\nToken: {mask(token)}\nTest URL: {urls[0]}")

    # Best-effort cleanup: find the uploaded file's id and delete it.
    file_id = None
    try:
        status, text = _http_request(
            f"{origin}/api/files?page=1&perpage=15", "GET", token, timeout=8)
        data = json.loads(text or "{}")
        entries = (data.get("page") or data.get("files") or []
                   if isinstance(data, dict) else data)
        url_path = urllib.parse.urlsplit(urls[0]).path
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            entry_url = urllib.parse.urlsplit(str(entry.get("url", ""))).path
            name = str(entry.get("name", ""))
            if entry_url == url_path or (name and url_path.endswith(name)):
                file_id = entry.get("id")
                break
    except (ValueError, OSError, HTTPException, socket.timeout) as exc:
        log(f"connection test cleanup lookup failed: {exc}")
    if file_id is None:
        return message + "\n\nNote: could not auto-delete the test file — " \
                         "please remove it in the Zipline dashboard."
    try:
        status, _ = _http_request(f"{origin}/api/file/{file_id}", "DELETE",
                                  token, timeout=8)
        if 200 <= status < 300:
            return message + "\n\n(The test file was deleted from the server.)"
    except (OSError, HTTPException, socket.timeout):
        pass
    return message + "\n\nNote: could not auto-delete the test file — " \
                     "please remove it in the Zipline dashboard."


# --------------------------------------------------------------------------- #
#  Progress displays
# --------------------------------------------------------------------------- #

def gdbus_call(dest: str, path: str, method: str, *args, timeout: float = 5.0):
    """Call a session-bus method with gdbus; tolerant of failures."""
    if not have("gdbus"):
        return None
    cmd = ["gdbus", "call", "--session", "--dest", dest,
           "--object-path", path, "--method", method, *args]
    try:
        proc = run(cmd, timeout=timeout)
        return proc.stdout.strip() if proc.returncode == 0 else None
    except (subprocess.TimeoutExpired, OSError):
        return None


def gdbus_set(dest: str, path: str, iface: str, prop: str, gvariant: str):
    if not have("gdbus"):
        return False
    cmd = ["gdbus", "call", "--session", "--dest", dest, "--object-path", path,
           "--method", "org.freedesktop.DBus.Properties.Set", iface, prop, gvariant]
    try:
        return run(cmd, timeout=5.0).returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


class ProgressBase:
    def start(self, label: str):  # noqa: D401 - trivial
        pass

    def update(self, sent: int, total: int, label: str):
        pass

    def check_cancel(self):
        pass

    def done(self):
        pass

    def close(self):
        pass


class NullProgress(ProgressBase):
    pass


class KDialogProgress(ProgressBase):
    """kdialog --progressbar driven over DBus (org.kde.kdialog.ProgressDialog,
    the interface used by kdialog in KDE Frameworks 6). Supports Cancel."""

    def __init__(self, title: str = APP_NAME):
        if not have("kdialog"):
            raise RuntimeError("kdialog not available")
        try:
            proc = subprocess.run(
                ["kdialog", "--title", title, "--progressbar", "Preparing…", "100"],
                capture_output=True, text=True, timeout=10)
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise RuntimeError(f"kdialog failed to start: {exc}") from exc
        out = proc.stdout.strip()
        tokens = out.split()
        if len(tokens) < 2:
            raise RuntimeError(f"kdialog returned no DBus address: {out!r}")
        self.bus, self.path = tokens[0], tokens[1]
        self.iface = "org.kde.kdialog.ProgressDialog"
        self._last_value = None
        self._last_label = None
        self._last_tick = 0.0
        self._last_cancel_check = 0.0
        self._closed = False
        # Offer a Cancel button; ignore failures (older kdialog).
        gdbus_call(self.bus, self.path, f"{self.iface}.showCancelButton", "true")

    def _alive(self) -> bool:
        return not self._closed

    def start(self, label: str):
        self._apply(0, label, force=True)

    def update(self, sent: int, total: int, label: str):
        pct = int(sent * 100 / total) if total else 100
        self._apply(pct, label)

    def _apply(self, value: int, label: str, force: bool = False):
        if not self._alive():
            return
        now = time.monotonic()
        if not force and value == self._last_value \
                and label == self._last_label:
            return
        # Throttle DBus round-trips to ~5/s unless the integer percent changed.
        if not force and value == self._last_value and now - self._last_tick < 0.2:
            return
        if value != self._last_value or force:
            gdbus_set(self.bus, self.path, self.iface, "value", f"<int32 {max(0, min(100, value))}>")
        if label != self._last_label or force:
            gdbus_call(self.bus, self.path, f"{self.iface}.setLabelText", label)
        self._last_value, self._last_label, self._last_tick = value, label, now

    def check_cancel(self):
        if not self._alive():
            raise UploadCancelled()
        now = time.monotonic()
        # check_cancel() fires on every streamed chunk — throttle the DBus
        # round-trip so it costs at most a few calls per second.
        if now - self._last_cancel_check < 0.25:
            return
        self._last_cancel_check = now
        result = gdbus_call(self.bus, self.path, f"{self.iface}.wasCancelled")
        if result is not None and "true" in result.lower():
            raise UploadCancelled()

    def set_busy(self, label: str):
        """Switch to a busy (indeterminate) indicator with the given label."""
        gdbus_set(self.bus, self.path, self.iface, "maximum", "<int32 0>")
        self._apply(0, label, force=True)

    def done(self):
        if self._alive():
            self._apply(100, "Done", force=True)

    def close(self):
        if self._alive():
            gdbus_call(self.bus, self.path, f"{self.iface}.close")
            self._closed = True


class NotifyProgress(ProgressBase):
    """Plasma notification with a progress-bar hint, updated via --replace-id."""

    def __init__(self):
        if not have("notify-send"):
            raise RuntimeError("notify-send not available")
        self._id = None
        self._last_value = None
        self._last_tick = 0.0

    def _send(self, body: str, value: int | None, timeout_ms: int, replace: bool):
        cmd = ["notify-send", "-a", APP_NAME, "-i", ICON,
               "-t", str(timeout_ms), "-p"]
        if replace and self._id is not None:
            cmd += ["-r", str(self._id)]
        if value is not None:
            cmd += ["-h", f"int:value:{max(0, min(100, value))}"]
        cmd += ["Uploading to Zipline", body]
        try:
            proc = run(cmd, timeout=5.0)
            if proc.stdout.strip().isdigit():
                self._id = int(proc.stdout.strip())
        except (subprocess.TimeoutExpired, OSError):
            pass

    def start(self, label: str):
        self._send(label, 0, 0, replace=False)

    def update(self, sent: int, total: int, label: str):
        pct = int(sent * 100 / total) if total else 100
        now = time.monotonic()
        if pct == self._last_value and now - self._last_tick < 1.0:
            return
        self._last_value, self._last_tick = pct, now
        self._send(f"{label}\n{pct}%", pct, 0, replace=True)

    def done(self):
        self._send("Finishing…", 100, 0, replace=True)

    def close(self):
        # The progress notification was sent with -t 0 (persistent); replace
        # it once more so it expires instead of lingering forever.
        if self._id is not None:
            self._send("Upload finished", None, 2000, replace=True)
            self._id = None


def make_progress(mode: str, count: int = 1) -> ProgressBase:
    if mode == "none" or os.environ.get("ZIPLINE_NO_PROGRESS"):
        return NullProgress()
    if mode == "notification":
        try:
            return NotifyProgress()
        except RuntimeError:
            return NullProgress()
    try:
        return KDialogProgress()
    except RuntimeError:
        try:
            return NotifyProgress()
        except RuntimeError:
            return NullProgress()


# --------------------------------------------------------------------------- #
#  Notifications and clipboard
# --------------------------------------------------------------------------- #

def notify(title: str, body: str, *, urgency: str = "normal",
           timeout_ms: int = 6000, icon: str = ICON):
    log(f"notify[{urgency}] {title}: {body[:120]}")
    if have("notify-send"):
        cmd = ["notify-send", "-a", APP_NAME, "-i", icon, "-u", urgency,
               "-t", str(timeout_ms), title, body]
        try:
            run(cmd, timeout=5.0)
            return
        except (subprocess.TimeoutExpired, OSError):
            pass
    if have("kdialog"):
        kind = "--error" if urgency == "critical" else "--msgbox"
        try:
            run(["kdialog", "--title", title, kind, body], timeout=3600)
        except (subprocess.TimeoutExpired, OSError):
            pass


def copy_to_clipboard(text: str, tool: str = "auto") -> tuple:
    """Copy text using the configured tool; returns (ok, tool_used, error)."""
    session = "wayland" if os.environ.get("WAYLAND_DISPLAY") else \
        "x11" if os.environ.get("DISPLAY") else "none"

    def via_klipper():
        result = gdbus_call("org.kde.klipper", "/klipper",
                            "org.kde.klipper.klipper.setClipboardContents", text)
        return result is not None

    def via_wl_copy():
        if not have("wl-copy"):
            return False
        try:
            # Text goes via stdin, not argv — stdin is wl-copy's canonical
            # interface and keeps the URL out of /proc/*/cmdline.
            proc = subprocess.run(["wl-copy"], input=text, capture_output=True,
                                  text=True, timeout=5)
            return proc.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False

    def via_xclip():
        if not have("xclip"):
            return False
        try:
            proc = subprocess.run(["xclip", "-selection", "clipboard"],
                                  input=text, capture_output=True, text=True, timeout=5)
            return proc.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False

    def via_xsel():
        if not have("xsel"):
            return False
        try:
            proc = subprocess.run(["xsel", "--clipboard", "--input"],
                                  input=text, capture_output=True, text=True, timeout=5)
            return proc.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False

    tools = {
        "klipper": via_klipper,
        "wl-copy": via_wl_copy,
        "xclip": via_xclip,
        "xsel": via_xsel,
    }
    if tool != "auto":
        order = [tool]
    else:
        # Klipper is Plasma-native and works on both Wayland and X11; wl-copy
        # only exists on Wayland, xclip/xsel only on X11.
        order = ["klipper"]
        if session == "wayland":
            order += ["wl-copy", "xclip", "xsel"]
        else:
            order += ["xclip", "xsel", "wl-copy"]

    for name in order:
        func = tools.get(name)
        if func is None:
            continue
        try:
            if func():
                return True, name, ""
        except Exception as exc:  # never let clipboard handling crash an upload
            log(f"clipboard {name} failed: {exc}")
    return False, "", (f"No working clipboard tool (tried: {', '.join(order)}). "
                       f"Install wl-clipboard (Wayland) or xclip (X11).")


def open_urls(urls: list):
    for url in urls:
        # URLs come from the server's response; only hand http(s) to
        # xdg-open so a hostile or misconfigured server cannot invoke other
        # URI handlers (file:, etc.) on the user's desktop.
        if urllib.parse.urlsplit(url).scheme.lower() not in ("http", "https"):
            log(f"refused to open non-http(s) URL: {url[:80]}")
            continue
        try:
            subprocess.Popen(["xdg-open", url],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            log(f"xdg-open failed: {exc}")


def append_history(files: list, urls: list, size: int):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        record = {
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "files": [os.path.basename(f) for f in files],
            "urls": urls,
            "size": size,
        }
        with open(HISTORY_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError as exc:
        log(f"history write failed: {exc}")


def read_history(limit: int = 50) -> list:
    """Most recent uploads first, from history.jsonl (newest → oldest)."""
    try:
        with open(HISTORY_PATH, encoding="utf-8") as fh:
            lines = fh.readlines()[-limit:]
    except OSError:
        return []
    records = []
    for line in reversed(lines):
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    return records


def run_hook(urls: list, files: list, cfg: dict):
    """Load ~/.config/zipline-upload/hook.py and call on_upload_complete()."""
    if not os.path.isfile(HOOK_PATH):
        return
    import importlib.util
    try:
        spec = importlib.util.spec_from_file_location("zipline_upload_hook", HOOK_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.on_upload_complete(urls, files, cfg)
    except Exception as exc:
        log(f"hook failed: {exc}")
        notify("Zipline upload — hook error",
               f"Your hook.py raised: {exc}", urgency="critical")


# --------------------------------------------------------------------------- #
#  kdialog settings GUI
# --------------------------------------------------------------------------- #

def kd(title: str, args: list, *, allow_cancel: bool = True):
    """Run kdialog; returns (rc, stdout)."""
    cmd = ["kdialog", "--title", title, *args]
    try:
        proc = run(cmd, timeout=3600)
        return proc.returncode, proc.stdout.rstrip("\n")
    except (subprocess.TimeoutExpired, OSError) as exc:
        log(f"kdialog failed: {exc}")
        return 1, ""


def kd_input(title: str, label: str, default: str = "") -> str | None:
    rc, out = kd(title, ["--inputbox", label, default])
    return out if rc == 0 else None


def kd_password(title: str, label: str) -> str | None:
    rc, out = kd(title, ["--password", label])
    return out if rc == 0 else None


def kd_menu(title: str, text: str, choices: list) -> str | None:
    args = ["--menu", text]
    for tag, label in choices:
        args += [tag, label]
    rc, out = kd(title, args)
    return out if rc == 0 and out else None


def kd_yesno(title: str, text: str) -> bool:
    rc, _ = kd(title, ["--yesno", text])
    return rc == 0


def kd_msgbox(title: str, text: str, error: bool = False):
    kd(title, ["--error" if error else "--msgbox", text])


def kd_choice(title: str, text: str, choices: list, current: str):
    """Menu for enum values: choices = [(value, label), …]."""
    labels = dict(choices)
    prompt = text
    if current in labels:
        prompt = f"{text}\n\nCurrent: {labels[current]}"
    tag = kd_menu(title, prompt, [(v, l) for v, l in choices] + [("_back", "← Back")])
    if tag is None or tag == "_back":
        return None
    return tag


def run_kdialog_settings(cfg: dict) -> tuple:
    """Fallback settings UI built from kdialog menu chains (no PySide6).
    Returns (saved: bool, cfg: dict)."""
    work = dict(cfg)
    dirty = False

    def server_settings():
        nonlocal work, dirty
        while True:
            choice = kd_menu("Zipline — Server", "Server settings", [
                ("url", "Upload URL…"),
                ("token", "Token…"),
                ("import", "Import from Zipline shell script…"),
                ("test", "Test connection"),
                ("back", "← Back"),
            ])
            if choice in (None, "back"):
                return
            if choice == "url":
                value = kd_input("Zipline — Server",
                                 "Server URL (e.g. https://zipline.example.com):",
                                 work.get("url", ""))
                if value is not None:
                    try:
                        work["url"] = normalize_endpoint(value)
                        dirty = True
                    except ZiplineError as exc:
                        kd_msgbox("Zipline — Server", str(exc), error=True)
            elif choice == "token":
                current = ("env $ZIPLINE_TOKEN" if work.get("use_env_token")
                           else mask(work.get("token", "")))
                choice2 = kd_menu(
                    "Zipline — Token", f"Current token: {current}", [
                        ("set", "Enter a new token…"),
                        ("env", "Use environment variable ZIPLINE_TOKEN"),
                        ("clear", "Clear stored token"),
                        ("back", "← Back"),
                    ])
                if choice2 == "set":
                    value = kd_password("Zipline — Token",
                                        "Zipline upload token (kept in "
                                        f"{CONFIG_PATH}, chmod 600):")
                    if value:
                        work["token"] = value
                        work["use_env_token"] = False
                        dirty = True
                elif choice2 == "env":
                    work["use_env_token"] = True
                    work["token"] = ""
                    dirty = True
                elif choice2 == "clear":
                    work["token"] = ""
                    work["use_env_token"] = False
                    dirty = True
            elif choice == "import":
                dirty = import_script_dialog(work) or dirty
            elif choice == "test":
                if not config_is_valid(effective_config(work)):
                    kd_msgbox("Zipline — Test",
                              "Set the server URL and token first.", error=True)
                    continue
                kd_msgbox("Zipline — Test connection", run_connection_test(work))

    def upload_options():
        nonlocal work, dirty
        while True:
            choice = kd_menu("Zipline — Upload options", "Upload options", [
                ("format", f"Filename format…"),
                ("orig", "Original name…"),
                ("compress", "Image compression…"),
                ("password", "Password protect…"),
                ("views", "Max views…"),
                ("expires", "Auto-delete after…"),
                ("extless", "Extensionless URLs…"),
                ("extra", "Additional x-zipline-* headers…"),
                ("back", "← Back"),
            ])
            if choice in (None, "back"):
                return
            if choice == "format":
                value = kd_choice("Zipline — Format", "Filename format",
                                  FORMAT_CHOICES, work.get("format", ""))
                if value is not None:
                    work["format"] = value
                    dirty = True
            elif choice == "orig":
                work["original_name"] = kd_yesno(
                    "Zipline — Original name",
                    f"Keep the original file name for downloads?\n"
                    f"(x-zipline-original-name)\n\nCurrent: "
                    f"{'yes' if work.get('original_name') else 'no'}")
                dirty = True
            elif choice == "compress":
                enable = kd_yesno(
                    "Zipline — Compression",
                    f"Enable server-side image compression?\nCurrent: "
                    f"{'%s%% %s' % (work.get('compress_percent'), work.get('compress_type')) if work.get('compress') else 'disabled'}")
                if enable:
                    value = kd_input("Zipline — Compression",
                                     "Compression percent (1-100):",
                                     str(work.get("compress_percent", 80)))
                    if value is None:
                        continue
                    try:
                        work["compress_percent"] = max(1, min(100, int(value)))
                    except ValueError:
                        kd_msgbox("Zipline — Compression",
                                  "Percent must be a number.", error=True)
                        continue
                    ctype = kd_choice("Zipline — Compression",
                                      "Compressed image format",
                                      [(t, t.upper()) for t in COMPRESSION_TYPES],
                                      work.get("compress_type", "jpg"))
                    if ctype is not None:
                        work["compress_type"] = ctype
                    work["compress"] = True
                else:
                    work["compress"] = False
                dirty = True
            elif choice == "password":
                value = kd_input(
                    "Zipline — Password",
                    "Password required to view uploads (empty = none):",
                    work.get("password", ""))
                if value is not None:
                    work["password"] = value
                    dirty = True
            elif choice == "views":
                value = kd_input(
                    "Zipline — Max views",
                    "Delete the file after this many views (empty = unlimited):",
                    str(work.get("max_views") or ""))
                if value is not None:
                    try:
                        work["max_views"] = int(value) if value.strip() else None
                        dirty = True
                    except ValueError:
                        kd_msgbox("Zipline — Max views",
                                  "Max views must be a whole number.", error=True)
            elif choice == "expires":
                value = kd_input(
                    "Zipline — Auto-delete",
                    "Delete the file after this time, e.g. 1d, 12h, 7d\n"
                    "or date=2026-12-31T00:00:00Z (empty = never):",
                    work.get("deletes_at", ""))
                if value is not None:
                    work["deletes_at"] = value.strip()
                    dirty = True
            elif choice == "extless":
                work["extensionless"] = kd_yesno(
                    "Zipline — Extensionless",
                    f"Serve URLs without a file extension? (Requires the "
                    f"server option.)\nCurrent: "
                    f"{'yes' if work.get('extensionless') else 'no'}")
                dirty = True
            elif choice == "extra":
                current = "\n".join(
                    f"{k}={v}" for k, v in (work.get("extra_headers") or {}).items())
                value = kd_input(
                    "Zipline — Extra headers",
                    "Additional x-zipline-* headers, one key=value per line\n"
                    "(e.g. x-zipline-folder=3). Empty = none:", current)
                if value is not None:
                    parsed = {}
                    for line in value.splitlines():
                        line = line.strip()
                        if "=" in line:
                            key, val = line.split("=", 1)
                            if key.strip():
                                parsed[key.strip().lower()] = val.strip()
                    work["extra_headers"] = parsed
                    dirty = True

    def after_upload():
        nonlocal work, dirty
        while True:
            choice = kd_menu("Zipline — After upload", "After-upload behaviour", [
                ("action", "Default action…"),
                ("clip", "Clipboard tool (Wayland/X11)…"),
                ("notify", "Completion notification…"),
                ("back", "← Back"),
            ])
            if choice in (None, "back"):
                return
            if choice == "action":
                value = kd_choice("Zipline — After upload", "Default action",
                                  POST_ACTIONS, work.get("post_action", "copy"))
                if value is not None:
                    work["post_action"] = value
                    dirty = True
            elif choice == "clip":
                value = kd_choice(
                    "Zipline — Clipboard",
                    "Clipboard tool — auto-detect uses Klipper, then wl-copy on "
                    "Wayland or xclip/xsel on X11",
                    CLIPBOARD_TOOLS, work.get("clipboard_tool", "auto"))
                if value is not None:
                    work["clipboard_tool"] = value
                    dirty = True
            elif choice == "notify":
                work["notify_done"] = kd_yesno(
                    "Zipline — Notification",
                    "Show a desktop notification when an upload finishes?\n"
                    f"Current: {'yes' if work.get('notify_done') else 'no'}")
                dirty = True

    def advanced():
        nonlocal work, dirty
        while True:
            choice = kd_menu("Zipline — Advanced", "Advanced settings", [
                ("timeout", "Connection timeout…"),
                ("progress", "Progress display…"),
                ("back", "← Back"),
            ])
            if choice in (None, "back"):
                return
            if choice == "timeout":
                value = kd_input("Zipline — Timeout",
                                 "Connection timeout in seconds:",
                                 str(work.get("timeout", 30)))
                if value is not None:
                    try:
                        work["timeout"] = max(5, min(600, int(value)))
                        dirty = True
                    except ValueError:
                        kd_msgbox("Zipline — Timeout",
                                  "Timeout must be a number.", error=True)
            elif choice == "progress":
                value = kd_choice("Zipline — Progress", "Show upload progress via",
                                  PROGRESS_MODES, work.get("progress_ui", "progressbar"))
                if value is not None:
                    work["progress_ui"] = value
                    dirty = True

    def import_script_dialog(target: dict) -> bool:
        rc, path = kd("Zipline — Import", [
            "--getopenfilename", os.path.expanduser("~/Downloads"),
            "*.sh *.bash|Zipline upload script (*.sh *.bash)"])
        if rc != 0 or not path:
            return False
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                parsed = parse_zipline_script(fh.read())
        except (OSError, ZiplineError) as exc:
            kd_msgbox("Zipline — Import", f"Could not import:\n{exc}", error=True)
            return False
        target.update(reconcile_import(target, parsed))
        headers_desc = "\n".join(f"  {k}: {v}" for k, v in
                                 parsed["headers"].items()) or "  (none)"
        kd_msgbox("Zipline — Import",
                  f"Imported from {path}\n\n"
                  f"Server: {parsed['endpoint']}\n"
                  f"Token: {mask(parsed['token'])}\n"
                  f"Options:\n{headers_desc}\n\n"
                  f"Remember to Save & exit to persist.")
        return True

    while True:
        choice = kd_menu("Zipline Upload — Settings", "Settings", [
            ("server", "Server (URL, token, import, test)…"),
            ("options", "Upload options…"),
            ("after", "After upload…"),
            ("advanced", "Advanced…"),
            ("view", "View current settings"),
            ("done", "Save & exit"),
        ])
        if choice is None:
            if not dirty:
                return False, cfg
            if kd_yesno("Zipline Upload",
                        "Discard unsaved changes and exit?"):
                return False, cfg
            continue
        if choice == "server":
            server_settings()
        elif choice == "options":
            upload_options()
        elif choice == "after":
            after_upload()
        elif choice == "advanced":
            advanced()
        elif choice == "view":
            kd_msgbox("Zipline Upload — Settings", config_summary(work))
        elif choice == "done":
            eff = effective_config(work)
            if not eff.get("url"):
                kd_msgbox("Zipline Upload",
                          "Server URL is required before saving.", error=True)
                continue
            if not eff.get("token"):
                kd_msgbox("Zipline Upload",
                          "Token is required before saving (or choose "
                          "“Use environment variable ZIPLINE_TOKEN”).",
                          error=True)
                continue
            save_config(work)
            return True, work


# --------------------------------------------------------------------------- #
#  Settings UI: Qt window when possible, kdialog menus as fallback
# --------------------------------------------------------------------------- #

def _qt_gui_available() -> bool:
    try:
        import PySide6  # noqa: F401
        return True
    except ImportError:
        return os.path.isfile(VENV_PYTHON)


def setup_qt_gui() -> bool:
    """Offer a one-time download of PySide6 into the private venv.

    Store/GHNS installs cannot run install.sh, so on first --configure we
    offer to create the venv (~150 MB, needs network). Refusing simply keeps
    the kdialog menu UI. Returns True if the venv is ready afterwards.
    """
    if _qt_gui_available():
        return True
    if not have("kdialog"):
        return False
    rc, _ = kd(APP_NAME, ["--yesno",
                          "The windowed settings GUI needs a one-time download "
                          "(about 150 MB of PySide6).\n\n"
                          "Set it up now?\n\n"
                          "Choose No to keep using these simpler menus instead."])
    if rc != 0:
        return False

    progress = None
    try:
        progress = KDialogProgress(APP_NAME)
        progress.set_busy("Downloading and installing PySide6…")
    except RuntimeError:
        progress = None

    python = shutil.which("python3") or "python3"
    ok = False
    try:
        step1 = subprocess.run([python, "-m", "venv", VENV_DIR],
                               capture_output=True, text=True, timeout=300)
        if step1.returncode == 0:
            step2 = subprocess.run(
                [VENV_PYTHON, "-m", "pip", "install", "--quiet",
                 "PySide6-Essentials"],
                capture_output=True, text=True, timeout=900)
            ok = step2.returncode == 0
            if not ok:
                log(f"PySide6 install failed: {step2.stderr[-500:]}")
        else:
            log(f"venv creation failed: {step1.stderr[-500:]}")
    except (subprocess.TimeoutExpired, OSError) as exc:
        log(f"venv setup failed: {exc}")

    if progress is not None:
        progress.close()
    if ok:
        kd(APP_NAME, ["--msgbox",
                      "The windowed settings GUI is ready.\n"
                      "Reopening the settings now…"])
    else:
        kd(APP_NAME, ["--error",
                      "PySide6 setup failed (see "
                      f"{LOG_PATH}).\n"
                      "The kdialog menus remain fully usable."])
    return ok


def open_settings() -> bool:
    """Open the settings UI, preferring the PySide6 window.

    Tries, in order: PySide6 in this interpreter; the addon's venv Python
    (offering a one-time download if missing); the kdialog menu fallback.
    Returns True only if settings were saved.
    """
    if os.path.isfile(GUI_SCRIPT):
        if not _qt_gui_available():
            setup_qt_gui()
        try:
            import PySide6  # noqa: F401
        except ImportError:
            pass
        else:
            try:
                gui_dir = os.path.dirname(GUI_SCRIPT)
                if gui_dir not in sys.path:
                    sys.path.insert(0, gui_dir)
                import zipline_gui
                return zipline_gui.run()
            except Exception as exc:  # GUI crash → fall through to kdialog
                log(f"Qt GUI (inline) failed: {exc}")
        if os.path.isfile(VENV_PYTHON):
            try:
                proc = subprocess.run([VENV_PYTHON, GUI_SCRIPT])
                # GUI exit codes: 0 saved, 1 user-cancelled, 2+ error.
                if proc.returncode == 0:
                    return True
                if proc.returncode == 1:
                    return False
                log(f"Qt GUI (venv) exited rc={proc.returncode}")
            except OSError as exc:
                log(f"Qt GUI (venv) launch failed: {exc}")
    saved, _ = run_kdialog_settings(load_config())
    return saved


# --------------------------------------------------------------------------- #
#  Worker
# --------------------------------------------------------------------------- #

def post_upload(cfg: dict, urls: list, files: list):
    action = cfg.get("post_action", "copy")
    if action in ("copy", "copy_open"):
        ok, tool, error = copy_to_clipboard("\n".join(urls),
                                            cfg.get("clipboard_tool", "auto"))
        if not ok:
            notify("Zipline upload — clipboard failed",
                   f"{error}\nURL: {urls[0]}", urgency="critical")
    if action in ("open", "copy_open"):
        open_urls(urls)
    if cfg.get("notify_done", True):
        suffix = "" if len(files) == 1 else "s"
        notify(f"Uploaded {len(files)} file{suffix} to Zipline", "\n".join(urls))


def do_upload(files: list, cfg: dict) -> int:
    eff = effective_config(cfg)
    endpoint = eff["url"]
    token = eff["token"]
    headers = build_headers(eff)
    timeout = int(eff.get("timeout", 30))
    progress = make_progress(eff.get("progress_ui", "progressbar"))

    all_urls = []
    total_size = 0
    try:
        for index, path in enumerate(files, start=1):
            label = f"{os.path.basename(path)} ({index}/{len(files)})"
            progress.start(f"Uploading {label}")
            urls = upload_file(endpoint, token, path, option_headers=headers,
                               timeout=timeout, progress=progress)
            all_urls.extend(urls)
            total_size += os.path.getsize(path)
        progress.done()
    except UploadCancelled:
        progress.close()
        notify("Zipline upload cancelled", "Upload was cancelled — nothing else "
               "was uploaded.", timeout_ms=4000)
        return 130
    except ZiplineError as exc:
        progress.close()
        notify("Zipline upload failed", str(exc), urgency="critical")
        log(f"ERROR {exc}")
        return 1
    finally:
        progress.close()

    append_history(files, all_urls, total_size)
    post_upload(eff, all_urls, files)
    run_hook(all_urls, files, eff)
    return 0


def main(argv: list) -> int:
    quiet = "--quiet" in argv[1:]
    args = [a for a in argv[1:] if a != "--quiet"]

    if "--version" in args:
        print(f"zipline-upload.py {VERSION}")
        return 0
    if "--status" in args:
        print(config_summary(load_config()))
        return 0
    if "--test" in args:
        print(run_connection_test(load_config()))
        return 0
    if "--configure" in args:
        return 0 if open_settings() else 1
    if "--import-script" in args:
        try:
            script_path = args[args.index("--import-script") + 1]
            with open(script_path, encoding="utf-8", errors="replace") as fh:
                parsed = parse_zipline_script(fh.read())
        except (IndexError, OSError, ZiplineError) as exc:
            print(f"Import failed: {exc}", file=sys.stderr)
            return 1
        cfg = reconcile_import(load_config(), parsed)
        save_config(cfg)
        print(f"Imported settings from {script_path} "
              f"(token {mask(parsed['token'])}).")
        return 0

    files = [a for a in args if not a.startswith("--")]
    unknown = [a for a in args if a.startswith("--")]
    if unknown:
        print(f"Unrecognized option: {unknown[0]}", file=sys.stderr)
        print(__doc__.strip(), file=sys.stderr)
        return 2
    if not files:
        print(__doc__.strip(), file=sys.stderr)
        return 2

    cfg = load_config()
    if not config_is_valid(effective_config(cfg)):
        log("first run: opening settings GUI")
        if not quiet:
            notify("Zipline Upload — first run",
                   "Please configure your Zipline server and token.",
                   timeout_ms=4000)
        saved = open_settings()
        cfg = load_config()
        if not config_is_valid(effective_config(cfg)):
            if saved or not quiet:
                notify("Zipline upload not configured",
                       "No upload was made — run with --configure to set up.",
                       urgency="critical")
            return 2
    return do_upload(files, cfg)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except KeyboardInterrupt:
        sys.exit(130)
