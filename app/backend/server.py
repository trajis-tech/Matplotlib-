# -*- coding: utf-8 -*-
"""
X-ray 單高斯找矩形 / 四重高斯找黑線 — local backend

- No Flask
- Python standard library HTTP server
- OpenCV / NumPy pipeline

Run:
    python app/backend/server.py

Open:
    http://127.0.0.1:8767
"""

from __future__ import annotations

import json
import mimetypes
import re
import sys
import threading
import traceback
import uuid
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Tuple
from urllib.parse import parse_qs, unquote, urlparse

HOST = "127.0.0.1"
PORT = 8767
APP_VERSION = "0.1"
_PROCESS_LOCK = threading.Lock()

BACKEND_DIR = Path(__file__).resolve().parent
APP_DIR = BACKEND_DIR.parent
PROJECT_ROOT = APP_DIR.parent
PORTABLE_SITE_PACKAGES = PROJECT_ROOT / "portable_python" / "Lib" / "site-packages"
if PORTABLE_SITE_PACKAGES.is_dir() and str(PORTABLE_SITE_PACKAGES) not in sys.path:
    sys.path.insert(0, str(PORTABLE_SITE_PACKAGES))
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from pipeline import run_pipeline, save_png  # noqa: E402

FRONTEND_DIR = APP_DIR / "frontend"
CONFIG_DIR = APP_DIR / "config"
OUTPUT_DIR = PROJECT_ROOT / "output"
TEMP_DIR = PROJECT_ROOT / "temp"
UPLOADS_DIR = PROJECT_ROOT / "workspace" / "uploads"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
MAX_UPLOAD_BYTES = 80 * 1024 * 1024
MAX_JSON_BYTES = 2 * 1024 * 1024


def json_ready(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): json_ready(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_ready(v) for v in obj]
    mod = str(getattr(type(obj), "__module__", "") or "")
    if mod.startswith("numpy"):
        ndim = getattr(obj, "ndim", None)
        if ndim not in (None, 0) and hasattr(obj, "tolist"):
            return json_ready(obj.tolist())
        if hasattr(obj, "item"):
            return obj.item()
    return obj


def json_response(handler: BaseHTTPRequestHandler, data: Dict[str, Any], status: int = 200) -> None:
    payload = json.dumps(json_ready(data), ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(payload)))
    handler.send_header("Cache-Control", "no-store, max-age=0")
    handler.end_headers()
    handler.wfile.write(payload)


def read_request_json(handler: BaseHTTPRequestHandler, max_bytes: int = MAX_JSON_BYTES) -> Dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0") or 0)
    if length < 0:
        raise ValueError("Invalid Content-Length.")
    if length > int(max_bytes):
        raise ValueError(f"Request body too large ({length} bytes).")
    raw = handler.rfile.read(length) if length else b"{}"
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def check_package(name: str) -> Dict[str, Any]:
    import_name = "cv2" if name == "opencv" else name
    try:
        mod = __import__(import_name)
        version = str(getattr(mod, "__version__", ""))
        if import_name == "cv2" and not version:
            version = str(getattr(mod, "version", ""))
        return {
            "ok": True,
            "version": version,
            "path": str(getattr(mod, "__file__", "")),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def sanitize_upload_name(name: str) -> str:
    text = Path(str(name or "upload")).name
    text = re.sub(r"[^\w.\u4e00-\u9fff\- ]+", "_", text).strip(" ._")
    return text or "upload"


def extract_multipart_file(body: bytes, boundary: str, field_name: str = "file") -> Tuple[str, bytes]:
    if not boundary:
        raise ValueError("Missing multipart boundary.")
    boundary_bytes = ("--" + boundary).encode("utf-8")
    for raw_part in body.split(boundary_bytes):
        if not raw_part or raw_part.startswith(b"--"):
            continue
        if raw_part.startswith(b"\r\n"):
            raw_part = raw_part[2:]
        if raw_part.endswith(b"\r\n"):
            raw_part = raw_part[:-2]
        header_end = raw_part.find(b"\r\n\r\n")
        if header_end < 0:
            continue
        header_blob = raw_part[:header_end].decode("utf-8", errors="replace")
        content = raw_part[header_end + 4 :]
        disp = ""
        for line in header_blob.split("\r\n"):
            if line.lower().startswith("content-disposition:"):
                disp = line
                break
        if not disp:
            continue
        name_match = re.search(r'name="(?P<name>[^"]+)"', disp)
        if not name_match or name_match.group("name") != field_name:
            continue
        fn_star = re.search(r"filename\*=(?:UTF-8''|utf-8'')(?P<fn>[^;]+)", disp)
        fn_plain = re.search(r'filename="(?P<fn>[^"]*)"', disp)
        if fn_star:
            filename = unquote(fn_star.group("fn"))
        elif fn_plain:
            filename = fn_plain.group("fn")
        else:
            filename = "upload"
        return filename or "upload", bytes(content)
    raise ValueError(f"Missing upload field: {field_name}")


def relative_posix(path: Path) -> str:
    return str(path.resolve().relative_to(PROJECT_ROOT.resolve())).replace("\\", "/")


def is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def sample_search_roots() -> list:
    roots = [PROJECT_ROOT.resolve()]
    parent = PROJECT_ROOT.parent.resolve()
    if parent != roots[0]:
        roots.append(parent)
    return roots


def sample_source_path(name: str) -> Path:
    raw = str(name or "").replace("\\", "/").strip()
    if not raw or "/" in raw or raw in {".", ".."}:
        raise ValueError("範例檔名不合法。")
    base = Path(raw).name
    if base != raw:
        raise ValueError("範例檔名不合法。")
    for root in sample_search_roots():
        src = (root / base).resolve()
        if not is_within(src, root) or src.parent.resolve() != root:
            continue
        if src.is_file() and src.suffix.lower() in IMAGE_SUFFIXES:
            return src
    raise ValueError("找不到範例影像。")


def resolve_under(root: Path, rel: str) -> Path:
    text = str(rel or "").replace("\\", "/").lstrip("/")
    path = (PROJECT_ROOT / text).resolve()
    if not is_within(path, root):
        raise ValueError("Path is outside the allowed directory.")
    return path


def list_sample_images() -> list:
    items = []
    seen = set()
    for root in sample_search_roots():
        if not root.is_dir():
            continue
        for p in sorted(root.iterdir()):
            if not p.is_file() or p.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            if p.name in seen:
                continue
            seen.add(p.name)
            items.append({"name": p.name, "path": p.name, "size": p.stat().st_size})
    return items


def list_output_images(limit: int = 200) -> Dict[str, Any]:
    files = []
    for p in sorted(OUTPUT_DIR.glob("*.png"), key=lambda x: x.stat().st_mtime, reverse=True):
        files.append(
            {
                "name": p.name,
                "path": relative_posix(p),
                "mtime": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"),
            }
        )
        if len(files) >= limit:
            break
    return {"ok": True, "files": files}


class Handler(BaseHTTPRequestHandler):
    server_version = "XraySingleGaussLines/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {self.address_string()} - {fmt % args}")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        if path in ("/", "/index.html"):
            return self.serve_file(FRONTEND_DIR / "index.html")

        if path == "/favicon.ico":
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if path.startswith("/frontend/"):
            rel = path.removeprefix("/frontend/").lstrip("/")
            if not rel:
                return self.serve_file(FRONTEND_DIR / "index.html")
            return self.serve_file(FRONTEND_DIR / rel)

        if path.lstrip("/") in {"styles.css", "app.js"}:
            return self.serve_file(FRONTEND_DIR / path.lstrip("/"))

        if path == "/api/health":
            return json_response(self, {
                "ok": True,
                "appVersion": APP_VERSION,
                "version": APP_VERSION,
                "python": {
                    "executable": sys.executable,
                    "version": sys.version,
                },
                "paths": {
                    "projectRoot": str(PROJECT_ROOT),
                    "portableSitePackages": str(PORTABLE_SITE_PACKAGES),
                },
                "packages": {
                    "numpy": check_package("numpy"),
                    "opencv": check_package("opencv"),
                },
            })

        if path == "/api/param-templates":
            tpl = CONFIG_DIR / "param_templates.json"
            try:
                data = json.loads(tpl.read_text(encoding="utf-8"))
                return json_response(self, {
                    "ok": True,
                    "templates": data.get("templates") or [],
                    "version": data.get("version"),
                })
            except Exception as exc:
                return json_response(self, {"ok": False, "error": str(exc), "templates": []}, status=500)

        if path == "/api/samples":
            return json_response(self, {"ok": True, "files": list_sample_images()})

        if path == "/api/output/images":
            qs = parse_qs(parsed.query or "")
            try:
                limit = int((qs.get("limit") or ["200"])[0])
            except Exception:
                limit = 200
            return json_response(self, list_output_images(limit=limit))

        self.send_error(404, "Not found")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/upload-image":
            try:
                content_type = self.headers.get("Content-Type", "") or ""
                if "multipart/form-data" not in content_type:
                    return json_response(self, {
                        "ok": False,
                        "error": "Invalid content type. Expected multipart/form-data.",
                    }, status=400)
                m = re.search(r"boundary=(?P<b>[^;]+)", content_type)
                if not m:
                    return json_response(self, {"ok": False, "error": "Missing multipart boundary."}, status=400)
                boundary = m.group("b").strip().strip('"')
                try:
                    content_length = int(self.headers.get("Content-Length", "") or 0)
                except Exception:
                    content_length = 0
                if content_length <= 0:
                    return json_response(self, {"ok": False, "error": "Missing Content-Length."}, status=400)
                if content_length > MAX_UPLOAD_BYTES:
                    return json_response(self, {"ok": False, "error": "Upload too large."}, status=413)
                body = self.rfile.read(content_length)
                filename, raw = extract_multipart_file(body, boundary, "file")
                original_name = sanitize_upload_name(filename)
                suffix = Path(original_name).suffix.lower()
                if suffix not in IMAGE_SUFFIXES:
                    return json_response(self, {
                        "ok": False,
                        "error": "僅支援 jpg / png / bmp / tif / webp。",
                    }, status=400)
                if not raw:
                    return json_response(self, {"ok": False, "error": "上傳檔為空。"}, status=400)
                unique = uuid.uuid4().hex[:12]
                saved_name = sanitize_upload_name(f"{Path(original_name).stem}_{unique}{suffix}")
                save_path = (UPLOADS_DIR / saved_name).resolve()
                if not is_within(save_path, UPLOADS_DIR):
                    return json_response(self, {"ok": False, "error": "Invalid upload path."}, status=400)
                save_path.write_bytes(raw)
                rel_path = relative_posix(save_path)
                return json_response(self, {
                    "ok": True,
                    "path": rel_path,
                    "originalName": original_name,
                    "savedName": saved_name,
                })
            except Exception as exc:
                return json_response(self, {
                    "ok": False,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }, status=400)

        if path == "/api/use-sample":
            try:
                payload = read_request_json(self)
                src = sample_source_path(str(payload.get("name") or ""))
                unique = uuid.uuid4().hex[:12]
                saved_name = sanitize_upload_name(f"{src.stem}_{unique}{src.suffix.lower()}")
                dest = UPLOADS_DIR / saved_name
                dest.write_bytes(src.read_bytes())
                return json_response(self, {
                    "ok": True,
                    "path": relative_posix(dest),
                    "originalName": src.name,
                    "savedName": saved_name,
                })
            except Exception as exc:
                return json_response(self, {"ok": False, "error": str(exc)}, status=400)

        if path == "/api/process":
            try:
                payload = read_request_json(self)
                image_path = str(payload.get("imagePath") or "").strip()
                if not image_path:
                    return json_response(self, {"ok": False, "error": "缺少 imagePath。"}, status=400)
                try:
                    abs_path = resolve_under(UPLOADS_DIR, image_path)
                except Exception:
                    return json_response(self, {"ok": False, "error": "影像路徑不合法。"}, status=400)
                if not abs_path.is_file():
                    return json_response(self, {"ok": False, "error": "找不到已上傳的影像。"}, status=400)
                param_values = payload.get("paramValues") or {}
                if not isinstance(param_values, dict):
                    param_values = {}
                with _PROCESS_LOCK:
                    result = run_pipeline(str(abs_path), param_values)
                    overlay = result.pop("overlayBgr")
                    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"overlay_{stamp}.png"
                    saved_path = OUTPUT_DIR / filename
                    save_png(str(saved_path), overlay)
                    save_png(str(TEMP_DIR / "latest_overlay.png"), overlay)
                result["filename"] = filename
                result["savedPath"] = relative_posix(saved_path)
                return json_response(self, result)
            except Exception as exc:
                return json_response(self, {
                    "ok": False,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }, status=400)

        self.send_error(404, "Not found")

    def serve_file(self, path: Path) -> None:
        try:
            path = path.resolve()
            frontend_root = FRONTEND_DIR.resolve()
            if not is_within(path, frontend_root):
                self.send_error(403, "Forbidden")
                return
            if not path.exists() or not path.is_file():
                self.send_error(404, f"找不到檔案：{path.name}")
                return
            content = path.read_bytes()
            mime, _ = mimetypes.guess_type(str(path))
            if not mime:
                mime = "application/octet-stream"
            if path.suffix.lower() in {".html", ".css", ".js"}:
                mime += "; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(content)))
            if path.suffix.lower() in {".html", ".css", ".js"}:
                self.send_header("Cache-Control", "no-store, max-age=0")
                self.send_header("Pragma", "no-cache")
            self.end_headers()
            self.wfile.write(content)
        except Exception:
            self.send_error(500, traceback.format_exc())


class ReusableServer(ThreadingHTTPServer):
    allow_reuse_address = False


def main() -> None:
    index = FRONTEND_DIR / "index.html"
    if not index.is_file():
        print("=" * 72)
        print("ERROR: 找不到前端頁面")
        print(f"Expected : {index}")
        print("請在「Python New」資料夾執行 點此開始.bat")
        print("=" * 72)
        sys.stdout.flush()
        raise SystemExit(1)
    url = f"http://{HOST}:{PORT}"
    print("=" * 72)
    print("X-ray 單高斯找矩形 / 四重高斯找黑線")
    print(f"Project root : {PROJECT_ROOT}")
    print(f"Python       : {sys.executable}")
    print(f"Open         : {url}")
    print("Stop         : Ctrl + C")
    print("=" * 72)
    sys.stdout.flush()
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        httpd = ReusableServer((HOST, PORT), Handler)
    except OSError as exc:
        print(f"ERROR: cannot bind {url} ({exc})")
        print("若先前已啟動伺服器，請先關閉該視窗或改用已開啟的瀏覽器分頁。")
        sys.stdout.flush()
        raise SystemExit(1) from exc
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
