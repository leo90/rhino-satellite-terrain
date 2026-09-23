---
name: rhino-satellite-terrain
description: Select a rectangular area on Tianditu satellite imagery, export its WGS84 bounds, download Tianditu imagery and DEM elevation plus OSM contextual features, and generate a textured Rhino terrain model.
---

# Rhino Satellite Terrain

Create real terrain in Rhino from a rectangle the user draws on the national Tianditu satellite layer. The picker and imagery downloader use the user's `TIANDITU_KEY` from the repository-root `.env` file (copy `.env.example`). Tianditu `img_w` is a Web Mercator WMTS layer; the picker exports its rectangle as WGS84 bounds without GCJ-02 conversion. The user has confirmed that their applicable Tianditu service terms permit downloading the selected tiles and baking them into a private Rhino research model. Preserve Tianditu attribution in the model metadata and report; do not infer permission to redistribute tiles or outputs beyond the user's confirmed scope. This skill adapts the DEM, imagery, Web Mercator, cache, and resampling approach of [chwang9/geo-3d-terrain-skill2.0](https://github.com/chwang9/geo-3d-terrain-skill2.0) and replaces its place-name input and Three.js-only delivery with a map picker and native `.3dm` output.

## Required outcome

- The selection comes from the supplied satellite-map picker. Do not ask the user to type a place name or coordinates unless the picker cannot be used.
- The generated Rhino document uses metres, local coordinates, X=east, Y=north, and includes the exact WGS84 selection bounds as object metadata.
- Use real AWS Terrarium DEM values. Do not invent relief or smooth over missing source data without reporting it.
- Keep the terrain as an editable Rhino mesh. Preserve the satellite texture as a sidecar image and assign it to the mesh material when supported.
- Add OpenStreetMap contextual geometry on separate `OSM::Roads`, `OSM::Water`, `OSM::Buildings`, and `OSM::Building_Footprints` layers. Preserve source attribution and OSM IDs as object metadata.
- Only generate an OSM building solid from a supplied `height` or `building:levels` tag. The latter uses the reported `--osm-level-height` conversion and must be marked `building:levels_estimated`. Missing-height buildings remain footprints unless the user explicitly authorizes a default-height assumption.
- High-resolution imagery is the default acceptance standard: request the highest available Tianditu `img_w` WMTS zoom (maximum 18), preserve up to 4096 pixels on the longest texture edge, and target an effective mapped pixel size of 0.5 m/px or better. Never silently relax this quality gate or upscale imagery to imply finer source detail. If native source imagery at maximum zoom cannot meet the target, report the measured resolution and ask the user whether to accept it before generation.
- Verify the `.3dm` by reopening it with `rhino3dm`, then import it into the live Rhino document through RhinoMCP when the connection is available.

## Workflow

1. Ensure the isolated environment exists. Prefer `.venv/Scripts/python.exe` inside this skill. If missing, create it with Python 3.12+ and install `requirements.txt`; do not install into global Python.
2. Copy `.env.example` to `.env`, enter `TIANDITU_KEY`, then run `scripts/map_picker.py --env-file <private-env-file> --out <work-dir>/terrain-selection.json`. The `.env` file is ignored by Git. The picker proxies only the Tianditu `img_w` and `cia_w` WMTS tile paths through loopback, rejects non-loopback bind addresses, and never embeds or sends the server-side key to the browser. Open the printed local URL if it does not open automatically.
3. Ask the user to pan/zoom, draw one rectangle, and click **确认此范围**. Continue after the picker reports that the selection was saved.
4. Run `scripts/prepare_rhino_terrain.py --env-file <private-env-file> --selection <selection.json> --out <terrain.3dm>`. The script reads `TIANDITU_KEY` from that ignored file (or the environment). Defaults are DEM zoom 14, grid limit 512, satellite zoom target 19 (capped by Tianditu at level 18), texture limit 4096, satellite tile budget 1000, and maximum mapped pixel size 0.5 m/px. It queries OSM by default; use `--no-osm` only when contextual features are not wanted. If the effective pixel size fails the gate, distinguish a texture-size/tile-budget cap from the imagery source's native pixel size: raising limits helps only when a cap is binding. Do not assume that redrawing a smaller area improves native pixel resolution. If the source limit is binding, ask the user to explicitly accept the measured resolution; only then rerun with `--max-ground-resolution` set to a value just above the measured resolution and report both values. Never upscale to claim more detail.
5. Read the generated `<terrain>.report.json`. Report selected width/height, DEM source resolution, elevation range, mesh vertex/face counts, satellite zoom, texture dimensions, effective mapped metres per pixel, OSM feature counts, height-source counts, texture status, and any zoom reduction.
6. If RhinoMCP is available, verify the current document first, then import the generated `.3dm` with Rhino's English `_Import` command. Put imported terrain on `TERRAIN::Mesh`; retain source metadata and do not delete existing scene objects.
7. Capture perspective and top views, visually check orientation, scale, clipping, obvious spikes/voids, and whether the texture follows the terrain. Use `analyze_objects` when the imported mesh can be selected by name.

## Input and coordinate rules

- `terrain-selection.json` must contain `bbox.west`, `bbox.south`, `bbox.east`, and `bbox.north` in WGS84 longitude/latitude.
- Reject antimeridian-crossing rectangles and zero-area selections with a clear message.
- Local origin is the southwest corner of the selected rectangle. The terrain mesh spans positive X and positive Y.
- Default Z origin is the minimum sampled elevation, so the lowest point is Z=0. Store the removed real elevation in `elevation_offset_m`. Use `--z-origin absolute` only when the user explicitly needs absolute elevations.
- Vertical exaggeration defaults to 1.0 and must be reported whenever changed.

## Detail and safety limits

- `--max-grid` controls the maximum terrain samples on either axis. 512 is a practical default; 1024 is high detail and may be heavy.
- DEM tiles are capped by `--max-dem-tiles`; the script lowers DEM zoom until the selection fits the cap.
- Satellite tiles are independently capped by `--max-sat-tiles`; texture detail must not force mesh density higher.
- Default satellite settings are `--sat-extra 5 --max-texture 4096 --max-sat-tiles 1000 --max-ground-resolution 0.5`; Tianditu's published `img_w` WMTS matrix set currently ends at level 18. If the tile budget, source availability, or texture limit cannot meet 0.5 m/px, stop with a clear quality-gate error and explain the measured limit. A user may explicitly accept a lower measured source resolution; record the accepted threshold in the report. Zoom level and texture dimensions do not guarantee equivalent optical detail in every region; the imagery provider's source photography remains the upper bound.
- This is regional DEM terrain, not survey-grade data. Do not describe roads, embankments, shore edges, or building pads as measured geometry.
- OSM roads are centre lines, not legal or surveyed road edges. Water polygons/lines and building footprints may be incomplete, simplified, or outdated. OSM building height tags are contextual; `building:levels` is converted using the stated assumption, not surveyed height.
- Keep downloaded/source files and the report beside the `.3dm` so the model can be regenerated.

## Files

- `scripts/map_picker.py`: local Tianditu satellite-map selection server.
- `assets/map_picker.html`: rectangle-drawing interface.
- `scripts/prepare_rhino_terrain.py`: exact-bounds DEM/imagery processing and `.3dm` generation.
- `references/data-and-accuracy.md`: sources, coordinate handling, OSM attribution, and accuracy limits.
