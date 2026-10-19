#!/usr/bin/env python3
"""Build a native Rhino terrain mesh from a satellite-map bbox selection."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import math
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote

import numpy as np
import requests
import rhino3dm
from PIL import Image
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


EARTH_RADIUS = 6378137.0
EARTH_CIRCUMFERENCE = 2.0 * math.pi * EARTH_RADIUS
TILE_SIZE = 256
MIN_ZOOM = 3
MAX_DEM_ZOOM = 15
MAX_SAT_ZOOM = 18
UA = "rhino-satellite-terrain/1.2"
CACHE_ROOT = Path(os.environ.get("RHINO_TERRAIN_CACHE", Path.home() / ".cache" / "rhino-satellite-terrain"))
OSM_ENDPOINT = "https://overpass-api.de/api/interpreter"
TIANDITU_SUBDOMAINS = 8
_tls = threading.local()


def read_local_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def session() -> requests.Session:
    current = getattr(_tls, "session", None)
    if current is None:
        current = requests.Session()
        current.headers.update({"User-Agent": UA})
        retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry, pool_connections=24, pool_maxsize=24)
        current.mount("https://", adapter)
        _tls.session = current
    return current


def lon_to_pixel_x(lon: float, zoom: int) -> float:
    return (lon + 180.0) / 360.0 * TILE_SIZE * (1 << zoom)


def lat_to_pixel_y(lat: float, zoom: int) -> float:
    lat = max(-85.05112878, min(85.05112878, lat))
    r = math.radians(lat)
    merc = math.log(math.tan(math.pi / 4.0 + r / 2.0))
    return (1.0 - merc / math.pi) / 2.0 * TILE_SIZE * (1 << zoom)


def mercator_x(lon: float) -> float:
    return EARTH_RADIUS * math.radians(lon)


def mercator_y(lat: float) -> float:
    lat = max(-85.05112878, min(85.05112878, lat))
    return EARTH_RADIUS * math.log(math.tan(math.pi / 4.0 + math.radians(lat) / 2.0))


def tile_window(bbox: dict[str, float], zoom: int) -> dict[str, float | int]:
    px_w = lon_to_pixel_x(bbox["west"], zoom)
    px_e = lon_to_pixel_x(bbox["east"], zoom)
    py_n = lat_to_pixel_y(bbox["north"], zoom)
    py_s = lat_to_pixel_y(bbox["south"], zoom)
    x0, x1 = math.floor(px_w / TILE_SIZE), math.floor((px_e - 1e-9) / TILE_SIZE)
    y0, y1 = math.floor(py_n / TILE_SIZE), math.floor((py_s - 1e-9) / TILE_SIZE)
    return {
        "px_w": px_w, "px_e": px_e, "py_n": py_n, "py_s": py_s,
        "x0": x0, "x1": x1, "y0": y0, "y1": y1,
        "tiles": (x1 - x0 + 1) * (y1 - y0 + 1),
    }


def fit_zoom(bbox: dict[str, float], requested: int, maximum: int, tile_cap: int) -> tuple[int, dict]:
    zoom = max(MIN_ZOOM, min(maximum, requested))
    while zoom > MIN_ZOOM:
        window = tile_window(bbox, zoom)
        if window["tiles"] <= tile_cap:
            return zoom, window
        zoom -= 1
    window = tile_window(bbox, zoom)
    if window["tiles"] > tile_cap:
        raise ValueError(f"Selection is too large even at zoom {zoom}: {window['tiles']} tiles > cap {tile_cap}")
    return zoom, window


def tile_url(kind: str, zoom: int, x: int, y: int, tianditu_key: str = "") -> str:
    if kind == "dem":
        return f"https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{zoom}/{x}/{y}.png"
    if kind == "tianditu_sat":
        server = (x + y) % TIANDITU_SUBDOMAINS
        return (
            f"https://t{server}.tianditu.gov.cn/img_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
            f"&LAYER=img&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX={zoom}"
            f"&TILEROW={y}&TILECOL={x}&tk={quote(tianditu_key, safe='')}"
        )
    raise ValueError(f"Unsupported tile kind: {kind}")


def fetch_tile(kind: str, zoom: int, x: int, y: int, tianditu_key: str = "") -> bytes | None:
    cache = CACHE_ROOT / kind / str(zoom) / str(x) / f"{y}.bin"
    if cache.exists():
        data = cache.read_bytes()
        return data or None
    url = tile_url(kind, zoom, x, y, tianditu_key)
    try:
        response = session().get(url, timeout=30)
    except requests.RequestException:
        if kind == "tianditu_sat":
            raise RuntimeError("Tianditu imagery request failed due to a network or service error.") from None
        raise
    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        if kind == "tianditu_sat":
            raise RuntimeError(
                f"Tianditu imagery request failed (HTTP {response.status_code}); "
                "check TIANDITU_KEY, enabled services, quota, and network access."
            )
        response.raise_for_status()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(response.content)
    return response.content


def mosaic_exact(
    bbox: dict[str, float], zoom: int, kind: str, workers: int, tianditu_key: str = ""
) -> tuple[Image.Image, int]:
    window = tile_window(bbox, zoom)
    x0, x1 = int(window["x0"]), int(window["x1"])
    y0, y1 = int(window["y0"]), int(window["y1"])
    mode = "RGB"
    mosaic = Image.new(mode, ((x1 - x0 + 1) * TILE_SIZE, (y1 - y0 + 1) * TILE_SIZE))
    futures = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                futures[pool.submit(fetch_tile, kind, zoom, x, y, tianditu_key)] = (x, y)
        missing = 0
        for future in as_completed(futures):
            x, y = futures[future]
            data = future.result()
            if data is None:
                missing += 1
                if kind == "dem":
                    raise RuntimeError(f"Missing DEM tile {zoom}/{x}/{y}; terrain was not fabricated")
                tile = Image.new("RGB", (TILE_SIZE, TILE_SIZE), (90, 90, 90))
            else:
                tile = Image.open(io.BytesIO(data)).convert("RGB")
            mosaic.paste(tile, ((x - x0) * TILE_SIZE, (y - y0) * TILE_SIZE))
    left = int(math.floor(float(window["px_w"]) - x0 * TILE_SIZE))
    top = int(math.floor(float(window["py_n"]) - y0 * TILE_SIZE))
    right = int(math.ceil(float(window["px_e"]) - x0 * TILE_SIZE))
    bottom = int(math.ceil(float(window["py_s"]) - y0 * TILE_SIZE))
    return mosaic.crop((left, top, right, bottom)), missing


def decode_terrarium(image: Image.Image, max_grid: int) -> np.ndarray:
    rgb = np.asarray(image, dtype=np.float32)
    elevation = rgb[:, :, 0] * 256.0 + rgb[:, :, 1] + rgb[:, :, 2] / 256.0 - 32768.0
    height, width = elevation.shape
    scale = min(1.0, max_grid / max(height, width))
    if scale < 1.0:
        size = (max(2, round(width * scale)), max(2, round(height * scale)))
        elevation = np.asarray(Image.fromarray(elevation, mode="F").resize(size, Image.Resampling.BILINEAR), dtype=np.float32)
    return elevation


def repair_isolated_spikes(elevation: np.ndarray, threshold_m: float = 80.0) -> tuple[np.ndarray, int]:
    """Replace only single-cell extreme spikes and report the repair count."""
    fixed = elevation.copy()
    repairs: list[tuple[int, int, float]] = []
    rows, cols = elevation.shape
    for row in range(1, rows - 1):
        for col in range(1, cols - 1):
            window = elevation[row - 1:row + 2, col - 1:col + 2]
            neighbors = np.delete(window.reshape(-1), 4)
            median = float(np.median(neighbors))
            if abs(float(elevation[row, col]) - median) > threshold_m:
                # Preserve real cliffs: repair only when the eight neighbors are locally coherent.
                if float(np.max(neighbors) - np.min(neighbors)) < threshold_m / 2.0:
                    repairs.append((row, col, median))
    for row, col, median in repairs:
        fixed[row, col] = median
    return fixed, len(repairs)


def add_layer(model: rhino3dm.File3dm, name: str, parent_id=None, color=None) -> int:
    layer = rhino3dm.Layer()
    layer.Name = name
    if parent_id is not None:
        layer.ParentLayerId = parent_id
    if color is not None:
        layer.Color = color
    return model.Layers.Add(layer)


def make_layers(model: rhino3dm.File3dm) -> dict[str, int]:
    terrain_root = rhino3dm.Layer()
    terrain_root.Name = "TERRAIN"
    terrain_root_idx = model.Layers.Add(terrain_root)
    osm_root = rhino3dm.Layer()
    osm_root.Name = "OSM"
    osm_root_idx = model.Layers.Add(osm_root)
    terrain_id = model.Layers[terrain_root_idx].Id
    osm_id = model.Layers[osm_root_idx].Id
    return {
        "terrain_mesh": add_layer(model, "Mesh", terrain_id),
        "osm_roads": add_layer(model, "Roads", osm_id, (225, 125, 35, 255)),
        "osm_water": add_layer(model, "Water", osm_id, (55, 145, 220, 255)),
        "osm_buildings": add_layer(model, "Buildings", osm_id, (185, 185, 185, 255)),
        "osm_building_footprints": add_layer(model, "Building_Footprints", osm_id, (120, 120, 120, 255)),
    }


def local_xy(lon: float, lat: float, bbox: dict[str, float]) -> tuple[float, float]:
    return mercator_x(lon) - mercator_x(bbox["west"]), mercator_y(lat) - mercator_y(bbox["south"])


def points_from_geometry(geometry: list[dict], bbox: dict[str, float], closed: bool = False) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for point in geometry:
        if "lon" not in point or "lat" not in point:
            continue
        xy = local_xy(float(point["lon"]), float(point["lat"]), bbox)
        if not points or abs(xy[0] - points[-1][0]) > 0.001 or abs(xy[1] - points[-1][1]) > 0.001:
            points.append(xy)
    if closed and len(points) >= 3 and (abs(points[0][0] - points[-1][0]) > 0.001 or abs(points[0][1] - points[-1][1]) > 0.001):
        points.append(points[0])
    return points


def clip_segment(start: tuple[float, float], end: tuple[float, float], width_m: float, height_m: float) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Liang-Barsky clip of a segment to the selected local XY rectangle."""
    x0, y0 = start
    dx, dy = end[0] - x0, end[1] - y0
    lower, upper = 0.0, 1.0
    for p, q in ((-dx, x0), (dx, width_m - x0), (-dy, y0), (dy, height_m - y0)):
        if abs(p) < 1e-12:
            if q < 0:
                return None
            continue
        ratio = q / p
        if p < 0:
            if ratio > upper:
                return None
            lower = max(lower, ratio)
        else:
            if ratio < lower:
                return None
            upper = min(upper, ratio)
    return (x0 + lower * dx, y0 + lower * dy), (x0 + upper * dx, y0 + upper * dy)


def clip_polyline(points: list[tuple[float, float]], width_m: float, height_m: float) -> list[list[tuple[float, float]]]:
    parts: list[list[tuple[float, float]]] = []
    for start, end in zip(points, points[1:]):
        clipped = clip_segment(start, end, width_m, height_m)
        if clipped is None:
            continue
        first, last = clipped
        if parts and abs(parts[-1][-1][0] - first[0]) < 0.001 and abs(parts[-1][-1][1] - first[1]) < 0.001:
            parts[-1].append(last)
        else:
            parts.append([first, last])
    return [part for part in parts if len(part) >= 2]


def clip_polygon(points: list[tuple[float, float]], width_m: float, height_m: float) -> list[tuple[float, float]]:
    """Sutherland-Hodgman clip of one simple OSM ring to the selection rectangle."""
    ring = points[:-1] if len(points) > 1 and points[0] == points[-1] else points[:]
    for inside, intersect in (
        (lambda p: p[0] >= 0, lambda a, b: (0.0, a[1] + (b[1] - a[1]) * (-a[0]) / (b[0] - a[0]))),
        (lambda p: p[0] <= width_m, lambda a, b: (width_m, a[1] + (b[1] - a[1]) * (width_m - a[0]) / (b[0] - a[0]))),
        (lambda p: p[1] >= 0, lambda a, b: (a[0] + (b[0] - a[0]) * (-a[1]) / (b[1] - a[1]), 0.0)),
        (lambda p: p[1] <= height_m, lambda a, b: (a[0] + (b[0] - a[0]) * (height_m - a[1]) / (b[1] - a[1]), height_m)),
    ):
        if not ring:
            break
        output: list[tuple[float, float]] = []
        previous = ring[-1]
        previous_inside = inside(previous)
        for current in ring:
            current_inside = inside(current)
            if current_inside != previous_inside:
                # Intersections are only requested for a segment crossing the active boundary.
                try:
                    output.append(intersect(previous, current))
                except ZeroDivisionError:
                    pass
            if current_inside:
                output.append(current)
            previous, previous_inside = current, current_inside
        ring = output
    if len(ring) >= 3:
        ring.append(ring[0])
    return ring


def elevation_at(x: float, y: float, width_m: float, height_m: float, elevation: np.ndarray, z_offset: float, vertical_scale: float) -> float:
    rows, cols = elevation.shape
    col = min(cols - 1, max(0, round(x / width_m * (cols - 1))))
    row = min(rows - 1, max(0, round((1.0 - y / height_m) * (rows - 1))))
    return (float(elevation[row, col]) - z_offset) * vertical_scale


def parse_metric(tags: dict[str, str], key: str) -> float | None:
    value = tags.get(key, "").strip().lower().replace("m", "")
    try:
        parsed = float(value)
        return parsed if parsed >= 0 else None
    except ValueError:
        return None


def building_height(tags: dict[str, str], level_height: float) -> tuple[float | None, str]:
    height = parse_metric(tags, "height")
    if height is not None and height > 0:
        return height, "height"
    levels = parse_metric(tags, "building:levels")
    if levels is not None and levels > 0:
        return levels * level_height, "building:levels_estimated"
    return None, "missing"


def object_attributes(name: str, layer_idx: int, metadata: dict[str, str | float | int]) -> rhino3dm.ObjectAttributes:
    attrs = rhino3dm.ObjectAttributes()
    attrs.Name = name
    attrs.LayerIndex = layer_idx
    for key, value in metadata.items():
        attrs.SetUserString(str(key), str(value))
    return attrs


def osm_cache_path(bbox: dict[str, float]) -> Path:
    key = hashlib.sha256(json.dumps(bbox, sort_keys=True).encode("utf-8")).hexdigest()[:20]
    return CACHE_ROOT / "osm" / f"{key}.json"


def fetch_osm(bbox: dict[str, float], endpoint: str, timeout_s: int, cache_hours: float) -> tuple[dict, bool]:
    cache = osm_cache_path(bbox)
    if cache.exists() and (dt.datetime.now().timestamp() - cache.stat().st_mtime) <= cache_hours * 3600:
        return json.loads(cache.read_text(encoding="utf-8")), True
    bounds = ",".join(str(bbox[key]) for key in ("south", "west", "north", "east"))
    query = "\n".join([
        f"[out:json][timeout:{timeout_s}];",
        "(",
        f"  way[highway]({bounds});",
        f"  way[waterway]({bounds});",
        f"  way[natural=water]({bounds});",
        f"  way[water]({bounds});",
        f"  way[building]({bounds});",
        ");",
        "out tags geom;",
    ])
    response = session().post(endpoint, data={"data": query}, timeout=timeout_s + 30)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload.get("elements"), list):
        raise RuntimeError("Overpass response did not include OSM elements")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload, False


def add_osm_features(
    model: rhino3dm.File3dm,
    layers: dict[str, int],
    bbox: dict[str, float],
    elevation: np.ndarray,
    width_m: float,
    height_m: float,
    z_offset: float,
    vertical_scale: float,
    osm: dict,
    level_height: float,
) -> dict[str, int]:
    counts = {"roads": 0, "water_lines": 0, "water_areas": 0, "building_solids": 0, "building_footprints": 0, "skipped_buildings": 0}
    for element in osm["elements"]:
        tags = element.get("tags", {})
        geometry = element.get("geometry", [])
        if not geometry:
            continue
        osm_id = element.get("id", "unknown")
        base_meta = {"source": "OpenStreetMap (ODbL)", "osm_type": element.get("type", "way"), "osm_id": osm_id}
        if "highway" in tags:
            points = points_from_geometry(geometry, bbox)
            for part_index, part in enumerate(clip_polyline(points, width_m, height_m)):
                polyline = rhino3dm.Polyline([rhino3dm.Point3d(x, y, elevation_at(x, y, width_m, height_m, elevation, z_offset, vertical_scale) + 0.05) for x, y in part])
                attrs = object_attributes(f"OSM_Road_{osm_id}_{part_index}", layers["osm_roads"], {**base_meta, "highway": tags["highway"], "name": tags.get("name", "")})
                model.Objects.AddPolyline(polyline, attrs)
                counts["roads"] += 1
            continue
        is_water = "waterway" in tags or tags.get("natural") == "water" or "water" in tags
        if is_water:
            closed = len(geometry) >= 3 and geometry[0] == geometry[-1]
            if closed:
                points = clip_polygon(points_from_geometry(geometry, bbox, closed=True), width_m, height_m)
                if len(points) < 4:
                    continue
                water_z = min(elevation_at(x, y, width_m, height_m, elevation, z_offset, vertical_scale) for x, y in points) + 0.08
                polyline = rhino3dm.Polyline([rhino3dm.Point3d(x, y, water_z) for x, y in points])
                attrs = object_attributes(f"OSM_Water_{osm_id}", layers["osm_water"], {**base_meta, "waterway": tags.get("waterway", tags.get("natural", tags.get("water", ""))), "name": tags.get("name", "")})
                extrusion = rhino3dm.Extrusion.CreateWithPlane(
                    polyline.ToNurbsCurve(), rhino3dm.Plane(rhino3dm.Point3d(0, 0, water_z), rhino3dm.Vector3d(0, 0, 1)), 0.01, True,
                )
                if extrusion is not None:
                    model.Objects.AddExtrusion(extrusion, attrs)
                    counts["water_areas"] += 1
                else:
                    model.Objects.AddPolyline(polyline, attrs)
                    counts["water_lines"] += 1
            else:
                points = points_from_geometry(geometry, bbox)
                for part_index, part in enumerate(clip_polyline(points, width_m, height_m)):
                    water_z = min(elevation_at(x, y, width_m, height_m, elevation, z_offset, vertical_scale) for x, y in part) + 0.08
                    polyline = rhino3dm.Polyline([rhino3dm.Point3d(x, y, water_z) for x, y in part])
                    attrs = object_attributes(f"OSM_Water_{osm_id}_{part_index}", layers["osm_water"], {**base_meta, "waterway": tags.get("waterway", tags.get("natural", tags.get("water", ""))), "name": tags.get("name", "")})
                    model.Objects.AddPolyline(polyline, attrs)
                    counts["water_lines"] += 1
            continue
        if "building" not in tags:
            continue
        points = clip_polygon(points_from_geometry(geometry, bbox, closed=True), width_m, height_m)
        if len(points) < 4:
            counts["skipped_buildings"] += 1
            continue
        base_z = min(elevation_at(x, y, width_m, height_m, elevation, z_offset, vertical_scale) for x, y in points[:-1]) + 0.1
        profile = rhino3dm.Polyline([rhino3dm.Point3d(x, y, base_z) for x, y in points])
        height, height_source = building_height(tags, level_height)
        metadata = {**base_meta, "building": tags.get("building", "yes"), "name": tags.get("name", ""), "osm_height_source": height_source}
        if height is None:
            attrs = object_attributes(f"OSM_Building_Footprint_{osm_id}", layers["osm_building_footprints"], metadata)
            model.Objects.AddPolyline(profile, attrs)
            counts["building_footprints"] += 1
            continue
        min_height = parse_metric(tags, "min_height") or 0.0
        if min_height > 0:
            profile = rhino3dm.Polyline([rhino3dm.Point3d(x, y, base_z + min_height) for x, y in points])
        extrusion = rhino3dm.Extrusion.CreateWithPlane(
            profile.ToNurbsCurve(), rhino3dm.Plane(rhino3dm.Point3d(0, 0, base_z + min_height), rhino3dm.Vector3d(0, 0, 1)), height, True,
        )
        if extrusion is None:
            counts["skipped_buildings"] += 1
            continue
        attrs = object_attributes(f"OSM_Building_{osm_id}", layers["osm_buildings"], {**metadata, "height_m": height, "min_height_m": min_height})
        model.Objects.AddExtrusion(extrusion, attrs)
        counts["building_solids"] += 1
    return counts


def build_model(
    out_path: Path,
    bbox: dict[str, float],
    elevation: np.ndarray,
    texture_path: Path | None,
    dem_zoom: int,
    vertical_scale: float,
    z_origin: str,
    osm_payload: dict | None,
    osm_level_height: float,
) -> dict:
    rows, cols = elevation.shape
    width_m = mercator_x(bbox["east"]) - mercator_x(bbox["west"])
    height_m = mercator_y(bbox["north"]) - mercator_y(bbox["south"])
    min_elev, max_elev = float(np.nanmin(elevation)), float(np.nanmax(elevation))
    z_offset = min_elev if z_origin == "min" else 0.0

    mesh = rhino3dm.Mesh()
    for row in range(rows):
        y = height_m * (1.0 - row / (rows - 1))
        for col in range(cols):
            x = width_m * col / (cols - 1)
            z = (float(elevation[row, col]) - z_offset) * vertical_scale
            mesh.Vertices.Add(x, y, z)
    for row in range(rows - 1):
        for col in range(cols - 1):
            a = row * cols + col
            b = a + 1
            d = (row + 1) * cols + col
            c = d + 1
            mesh.Faces.AddFace(a, d, c, b)
    mesh.Normals.ComputeNormals()
    mesh.Compact()

    model = rhino3dm.File3dm()
    model.Settings.ModelUnitSystem = rhino3dm.UnitSystem.Meters
    layers = make_layers(model)
    material_idx = -1
    texture_assigned = False
    if texture_path and texture_path.exists():
        mapping = rhino3dm.TextureMapping.CreatePlaneMapping(
            rhino3dm.Plane.WorldXY(),
            rhino3dm.Interval(0.0, width_m),
            rhino3dm.Interval(0.0, height_m),
            rhino3dm.Interval(-1.0, max(1.0, (max_elev - z_offset) * vertical_scale + 1.0)),
        )
        mesh.SetTextureCoordinates(mapping, rhino3dm.Transform.Identity(), False)
        material = rhino3dm.Material()
        # Rhino can reuse a same-named material from a previously cleared site.
        material.Name = "Tianditu_" + hashlib.sha256(texture_path.read_bytes()).hexdigest()[:16]
        material.DiffuseColor = (255, 255, 255, 255)
        material.SetBitmapTexture(str(texture_path))
        texture_assigned = material.GetBitmapTexture() is not None
        material_idx = model.Materials.Add(material)

    attrs = rhino3dm.ObjectAttributes()
    attrs.Name = "Terrain_Mesh"
    attrs.LayerIndex = layers["terrain_mesh"]
    if material_idx >= 0:
        attrs.MaterialIndex = material_idx
        attrs.MaterialSource = rhino3dm.ObjectMaterialSource.MaterialFromObject
    metadata = {
        "crs": "EPSG:4326",
        "west": bbox["west"], "south": bbox["south"], "east": bbox["east"], "north": bbox["north"],
        "local_origin": "southwest", "axis": "X=east,Y=north,Z=up", "units": "metres",
        "dem_source": "AWS Terrarium", "dem_zoom": dem_zoom,
        "imagery_source": "National Geographic Information Public Service Platform (Tianditu)",
        "imagery_attribution": "Source: National Geographic Information Public Service Platform (Tianditu)",
        "elevation_offset_m": z_offset, "vertical_scale": vertical_scale,
    }
    for key, value in metadata.items():
        attrs.SetUserString(key, str(value))
    model.Objects.AddMesh(mesh, attrs)
    osm_counts = None
    if osm_payload is not None:
        osm_counts = add_osm_features(
            model, layers, bbox, elevation, width_m, height_m, z_offset, vertical_scale,
            osm_payload, osm_level_height,
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not model.Write(str(out_path), 8):
        raise RuntimeError(f"Failed to write Rhino file: {out_path}")
    reopened = rhino3dm.File3dm.Read(str(out_path))
    if reopened is None or len(reopened.Objects) < 1:
        raise RuntimeError("Generated Rhino file could not be verified by reopening")
    return {
        "width_m": width_m, "height_m": height_m,
        "min_elevation_m": min_elev, "max_elevation_m": max_elev,
        "elevation_offset_m": z_offset,
        "grid_rows": rows, "grid_columns": cols,
        "vertices": rows * cols, "quad_faces": (rows - 1) * (cols - 1),
        "texture_assigned": texture_assigned,
        "osm": osm_counts,
        "object_count": len(reopened.Objects),
    }


def read_bbox(path: Path) -> dict[str, float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    bbox = {key: float(payload["bbox"][key]) for key in ("west", "south", "east", "north")}
    if not (-180 <= bbox["west"] < bbox["east"] <= 180):
        raise ValueError("Selection must not cross the antimeridian")
    if not (-85.05112878 <= bbox["south"] < bbox["north"] <= 85.05112878):
        raise ValueError("Selection latitude is outside Web Mercator limits")
    return bbox


def main() -> int:
    parser = argparse.ArgumentParser(description="Create Rhino terrain from a saved map rectangle")
    parser.add_argument("--selection", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--env-file", default=None, help="Local .env file containing TIANDITU_KEY")
    parser.add_argument("--dem-zoom", type=int, default=14)
    parser.add_argument("--sat-extra", type=int, default=5)
    parser.add_argument("--max-grid", type=int, default=512)
    parser.add_argument("--max-texture", type=int, default=4096)
    parser.add_argument("--max-dem-tiles", type=int, default=256)
    parser.add_argument("--max-sat-tiles", type=int, default=1000)
    parser.add_argument("--max-ground-resolution", type=float, default=0.5,
                        help="Maximum allowed mapped texture pixel size in metres")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--vertical-scale", type=float, default=1.0)
    parser.add_argument("--z-origin", choices=["min", "absolute"], default="min")
    parser.add_argument("--no-texture", action="store_true")
    parser.add_argument("--no-osm", action="store_true", help="Skip OSM roads, water, and buildings")
    parser.add_argument("--osm-endpoint", default=OSM_ENDPOINT)
    parser.add_argument("--osm-timeout", type=int, default=90)
    parser.add_argument("--osm-cache-hours", type=float, default=24.0)
    parser.add_argument("--osm-level-height", type=float, default=3.5,
                        help="Metres per OSM building:levels value; derived heights are marked as estimated")
    args = parser.parse_args()
    if args.max_grid < 2 or args.max_texture < 32 or args.vertical_scale <= 0 or args.max_ground_resolution <= 0 or args.osm_timeout < 1 or args.osm_cache_hours < 0 or args.osm_level_height <= 0:
        raise ValueError("Invalid limits: grid >= 2, texture >= 32, positive scales/timeouts, and non-negative OSM cache hours are required")

    selection_path = Path(args.selection).resolve()
    out_path = Path(args.out).resolve()
    env_path = Path(args.env_file).resolve() if args.env_file else Path(__file__).resolve().parent.parent / ".env"
    env_values = read_local_env(env_path)
    tianditu_key = os.environ.get("TIANDITU_KEY", env_values.get("TIANDITU_KEY", ""))
    if not args.no_texture and not tianditu_key:
        raise ValueError("TIANDITU_KEY is missing; set it in the skill repository .env or environment.")
    bbox = read_bbox(selection_path)
    selected_width_m = mercator_x(bbox["east"]) - mercator_x(bbox["west"])
    selected_height_m = mercator_y(bbox["north"]) - mercator_y(bbox["south"])
    dem_zoom, dem_window = fit_zoom(bbox, args.dem_zoom, MAX_DEM_ZOOM, args.max_dem_tiles)
    print(f"DEM_ZOOM={dem_zoom} DEM_TILES={dem_window['tiles']}", flush=True)
    dem_image, _ = mosaic_exact(bbox, dem_zoom, "dem", args.workers)
    elevation = decode_terrarium(dem_image, args.max_grid)
    elevation, repaired_spikes = repair_isolated_spikes(elevation)

    osm_payload = None
    osm_cache_used = None
    if not args.no_osm:
        print("OSM_QUERY=roads,water,buildings", flush=True)
        osm_payload, osm_cache_used = fetch_osm(bbox, args.osm_endpoint, args.osm_timeout, args.osm_cache_hours)

    texture_path = None
    texture_size = None
    texture_resolution = None
    missing_sat = 0
    sat_zoom = None
    if not args.no_texture:
        sat_zoom, sat_window = fit_zoom(bbox, dem_zoom + args.sat_extra, MAX_SAT_ZOOM, args.max_sat_tiles)
        print(f"SAT_ZOOM={sat_zoom} SAT_TILES={sat_window['tiles']}", flush=True)
        sat_image, missing_sat = mosaic_exact(bbox, sat_zoom, "tianditu_sat", args.workers, tianditu_key)
        sat_scale = min(1.0, args.max_texture / max(sat_image.size))
        if sat_scale < 1.0:
            sat_image = sat_image.resize(
                (max(32, round(sat_image.width * sat_scale)), max(32, round(sat_image.height * sat_scale))),
                Image.Resampling.LANCZOS,
            )
        texture_size = [sat_image.width, sat_image.height]
        texture_resolution = max(selected_width_m / sat_image.width, selected_height_m / sat_image.height)
        if texture_resolution > args.max_ground_resolution:
            raise RuntimeError(
                f"Imagery quality gate failed: {texture_resolution:.3f} m/px exceeds "
                f"{args.max_ground_resolution:.3f} m/px. Draw a smaller selection or raise --max-texture/--max-sat-tiles."
            )
        texture_buffer = io.BytesIO()
        sat_image.save(texture_buffer, "JPEG", quality=90, optimize=True)
        texture_data = texture_buffer.getvalue()
        texture_id = hashlib.sha256(texture_data).hexdigest()[:16]
        # Rhino also resolves/caches bitmaps by filename across imported models.
        texture_path = out_path.with_name(out_path.stem + "_satellite_" + texture_id + ".jpg")
        texture_path.parent.mkdir(parents=True, exist_ok=True)
        texture_path.write_bytes(texture_data)

    npz_path = out_path.with_name(out_path.stem + "_elevation.npz")
    np.savez_compressed(npz_path, elevation=elevation, bbox=np.array([bbox[k] for k in ("west", "south", "east", "north")]))
    model_report = build_model(
        out_path, bbox, elevation, texture_path, dem_zoom, args.vertical_scale, args.z_origin,
        osm_payload, args.osm_level_height,
    )
    centre_lat = (bbox["south"] + bbox["north"]) / 2.0
    source_resolution = EARTH_CIRCUMFERENCE * math.cos(math.radians(centre_lat)) / (TILE_SIZE * (1 << dem_zoom))
    report = {
        "ok": True,
        "selection_file": str(selection_path), "rhino_file": str(out_path),
        "texture_file": str(texture_path) if texture_path else None,
        "elevation_file": str(npz_path), "bbox_wgs84": bbox,
        "dem_zoom_requested": args.dem_zoom, "dem_zoom_used": dem_zoom,
        "dem_tiles": dem_window["tiles"], "dem_source_resolution_m_per_pixel": source_resolution,
        "repaired_isolated_dem_spikes": repaired_spikes,
        "sat_zoom_used": sat_zoom, "missing_satellite_tiles": missing_sat,
        "texture_size_pixels": texture_size,
        "texture_ground_resolution_m_per_pixel": texture_resolution,
        "texture_quality_limit_m_per_pixel": args.max_ground_resolution,
        "vertical_scale": args.vertical_scale, "z_origin": args.z_origin,
        **model_report,
        "osm_query": {
            "enabled": not args.no_osm, "endpoint": args.osm_endpoint if not args.no_osm else None,
            "cache_used": osm_cache_used, "level_height_m": args.osm_level_height,
            "licence": "Open Database License (ODbL) 1.0; attribution required",
            "note": "Road centre lines and OSM water/building geometry are contextual, not survey-grade.",
        },
        "imagery_attribution": "Source: National Geographic Information Public Service Platform (Tianditu)",
        "sources": {"dem": "AWS Terrarium", "imagery": "Tianditu img_w WMTS", "osm": "OpenStreetMap (ODbL)"},
        "accuracy_note": "Regional DEM and OSM context only; not survey-grade terrain or feature geometry.",
    }
    report_path = out_path.with_name(out_path.stem + ".report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
