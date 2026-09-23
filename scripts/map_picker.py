#!/usr/bin/env python3
"""Serve a local satellite-map rectangle picker and save its WGS84 bbox."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


TIANDITU_SUBDOMAINS = 8
TIANDITU_MAX_ZOOM = 18
TIANDITU_LAYERS = {"img": "img_w", "cia": "cia_w"}
UPSTREAM_TIMEOUT_SECONDS = 20


def tianditu_tile_url(layer: str, zoom: int, x: int, y: int, key: str) -> str:
    service_layer = TIANDITU_LAYERS[layer]
    server = (x + y) % TIANDITU_SUBDOMAINS
    return (
        f"https://t{server}.tianditu.gov.cn/{service_layer}/wmts"
        "?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
        f"&LAYER={layer}&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles"
        f"&TILEMATRIX={zoom}&TILEROW={y}&TILECOL={x}&tk={quote(key, safe='')}"
    )


def fetch_tianditu_tile(layer: str, zoom: int, x: int, y: int, key: str) -> tuple[bytes, str]:
    url = tianditu_tile_url(layer, zoom, x, y, key)
    request = Request(url, headers={"User-Agent": "rhino-satellite-terrain/1.0"})
    try:
        with urlopen(request, timeout=UPSTREAM_TIMEOUT_SECONDS) as response:
            content_type = response.headers.get_content_type()
            body = response.read()
            if not content_type.startswith("image/"):
                raise RuntimeError("Tianditu returned a non-image response")
            return body, response.headers.get("Content-Type", content_type)
    except HTTPError as exc:
        # Never return upstream error bodies; they can contain operational details.
        raise RuntimeError(f"Tianditu rejected the {layer} tile (HTTP {exc.code})") from None
    except URLError:
        raise RuntimeError("Tianditu tile service could not be reached") from None


def read_local_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip("\"'")
        if key.strip():
            values[key.strip()] = value
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description="Satellite map rectangle picker")
    parser.add_argument("--out", required=True, help="Selection JSON path")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--env-file", default=None, help="Local ignored .env file (defaults to repository root)")
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    try:
        bind_ip = ipaddress.ip_address(args.host)
    except ValueError as exc:
        raise SystemExit("--host must be a loopback IP; the local tile proxy carries your Tianditu key") from exc
    if not bind_ip.is_loopback:
        raise SystemExit("--host must be a loopback IP; the local tile proxy carries your Tianditu key")

    out_path = Path(args.out).resolve()
    repo_root = Path(__file__).resolve().parent.parent
    env_path = Path(args.env_file).resolve() if args.env_file else repo_root / ".env"
    local_env = read_local_env(env_path)
    tianditu_key = os.environ.get("TIANDITU_KEY", local_env.get("TIANDITU_KEY", ""))
    if not tianditu_key:
        raise SystemExit("TIANDITU_KEY is missing; set it in the ignored .env file or environment")
    html_path = repo_root / "assets" / "map_picker.html"
    html = html_path.read_text(encoding="utf-8")
    html = html.encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *values: object) -> None:
            print("[picker] " + (fmt % values))

        def send_bytes(self, status: int, data: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                self.send_bytes(200, html, "text/html; charset=utf-8")
            elif path == "/status":
                payload = {"saved": out_path.exists(), "tile_proxy": "ready"}
                self.send_bytes(200, json.dumps(payload).encode(), "application/json")
            elif path.startswith("/tiles/"):
                parts = path.strip("/").split("/")
                if len(parts) != 5:
                    self.send_bytes(404, b"invalid tile path", "text/plain; charset=utf-8")
                    return
                # Expected path is /tiles/{layer}/{z}/{x}/{y}.
                _, layer, zoom_text, x_text, y_text = parts
                if layer not in TIANDITU_LAYERS:
                    self.send_bytes(404, b"unsupported tile layer", "text/plain; charset=utf-8")
                    return
                try:
                    zoom, x, y = int(zoom_text), int(x_text), int(y_text)
                except ValueError:
                    self.send_bytes(400, b"invalid tile coordinates", "text/plain; charset=utf-8")
                    return
                matrix_size = 1 << zoom if 0 <= zoom <= TIANDITU_MAX_ZOOM else 0
                if not matrix_size or not (0 <= x < matrix_size and 0 <= y < matrix_size):
                    self.send_bytes(400, b"tile coordinates out of range", "text/plain; charset=utf-8")
                    return
                try:
                    body, content_type = fetch_tianditu_tile(layer, zoom, x, y, tianditu_key)
                    self.send_bytes(200, body, content_type)
                except RuntimeError as exc:
                    self.log_message("tile proxy failed layer=%s z=%s x=%s y=%s: %s", layer, zoom, x, y, exc)
                    self.send_bytes(502, str(exc).encode("utf-8"), "text/plain; charset=utf-8")
            else:
                self.send_bytes(404, b"not found", "text/plain")

        def do_POST(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/selection":
                self.send_bytes(404, b"not found", "text/plain")
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(size).decode("utf-8"))
                bbox = payload["bbox"]
                west, south = float(bbox["west"]), float(bbox["south"])
                east, north = float(bbox["east"]), float(bbox["north"])
                if not (-180 <= west < east <= 180 and -85.05112878 <= south < north <= 85.05112878):
                    raise ValueError("invalid or antimeridian-crossing bbox")
                payload["crs"] = "EPSG:4326"
                payload.setdefault("source", f"{payload.get('map_provider', 'satellite')}-satellite-map-rectangle")
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                body = json.dumps({"ok": True, "path": str(out_path)}, ensure_ascii=False).encode("utf-8")
                self.send_bytes(200, body, "application/json; charset=utf-8")
                print(f"SELECTION_SAVED={out_path}", flush=True)
            except Exception as exc:
                body = json.dumps({"ok": False, "error": str(exc)}).encode("utf-8")
                self.send_bytes(400, body, "application/json")

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{server.server_address[1]}/"
    print(f"MAP_PICKER_URL={url}", flush=True)
    print(f"SELECTION_FILE={out_path}", flush=True)
    if not args.no_open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
