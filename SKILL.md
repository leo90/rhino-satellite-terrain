---
name: rhino-satellite-terrain
description: Select a rectangular area on Tianditu satellite imagery, export its WGS84 bounds, download Tianditu imagery and DEM elevation plus OSM contextual features, and generate a textured Rhino terrain model.
---

# Rhino Satellite Terrain

Create real terrain in Rhino from a rectangle the user draws on the national Tianditu satellite layer. The picker and imagery downloader use the user's `TIANDITU_KEY` from the repository-root `.env` file (copy `.env.example`). Tianditu `img_w` is a Web Mercator WMTS layer; the picker exports its rectangle as WGS84 bounds without GCJ-02 conversion. The user has confirmed that their applicable Tianditu service terms permit downloading the selected tiles and baking them into a private Rhino research model. Preserve Tianditu attribution in the model metadata and report; do not infer permission to redistribute tiles or outputs beyond the user's confirmed scope. This skill adapts the DEM, imagery, Web Mercator, cache, and resampling approach of [chwang9/geo-3d-terrain-skill2.0](https://github.com/chwang9/geo-3d-terrain-skill2.0) and replaces its place-name input and Three.js-only delivery with a map picker and native `.3dm` output.

## Required outcome

- The selection comes from the supplied satellite-map picker. Do not ask the user to type a place name or coordinates unless the picker cannot be used.
- The generated Rhino document uses metres, local coordinates, X=east, Y=north, and includes the exact WGS84 selection bounds as object metadata.
- Use real AWS Terrarium DEM values by default. Do not invent relief or smooth over missing source data without reporting it. When the user says **忽略地形标高**, apply the explicit zero-elevation mode below; keep the original DEM as source data and label the flattened geometry as a design representation.
- Keep the terrain as an editable Rhino mesh. Preserve the satellite texture as a sidecar image and assign it to the mesh material when supported.
- Add OpenStreetMap contextual geometry on separate `OSM::Roads`, `OSM::Water`, `OSM::Buildings`, and `OSM::Building_Footprints` layers. Preserve source attribution and OSM IDs as object metadata.
- Only generate an OSM building solid from a supplied `height` or `building:levels` tag. The latter uses the reported `--osm-level-height` conversion and must be marked `building:levels_estimated`. Missing-height buildings remain footprints unless the user explicitly authorizes a default-height assumption.
- High-resolution imagery is the default acceptance standard: request the highest available Tianditu `img_w` WMTS zoom (maximum 18), preserve up to 4096 pixels on the longest texture edge, and target an effective mapped pixel size of 0.5 m/px or better. Never silently relax this quality gate or upscale imagery to imply finer source detail. If native source imagery at maximum zoom cannot meet the target, report the measured resolution and ask the user whether to accept it before generation.
- Verify the `.3dm` by reopening it with `rhino3dm`, then import it into the live Rhino document through RhinoMCP when the connection is available.

## Workflow

1. Ensure the isolated environment exists. Prefer `.venv/Scripts/python.exe` inside this skill. If missing, create it with Python 3.12+ and install `requirements.txt`; do not install into global Python.
2. Copy `.env.example` to `.env`, enter `TIANDITU_KEY`, then run `scripts/map_picker.py --env-file <private-env-file> --out <work-dir>/terrain-selection.json`. The `.env` file is ignored by Git. The picker proxies only the Tianditu `img_w` and `cia_w` WMTS tile paths through loopback, rejects non-loopback bind addresses, and never embeds or sends the server-side key to the browser. Open the printed local URL if it does not open automatically.
3. Ask the user to pan/zoom, draw one rectangle, and click **确认此范围**. Continue after the picker reports that the selection was saved. On each new selection, read the latest saved bbox and timestamp, then snapshot that JSON into a new versioned output directory before generation. Preserve previous models, textures and reports; do not assume the picker still contains the previous rectangle.
4. Run `scripts/prepare_rhino_terrain.py --env-file <private-env-file> --selection <selection.json> --out <terrain.3dm>`. The script reads `TIANDITU_KEY` from that ignored file (or the environment). Defaults are DEM zoom 14, grid limit 512, satellite zoom target 19 (capped by Tianditu at level 18), texture limit 4096, satellite tile budget 1000, and maximum mapped pixel size 0.5 m/px. It queries OSM by default; use `--no-osm` only when contextual features are not wanted. If the effective pixel size fails the gate, distinguish a texture-size/tile-budget cap from the imagery source's native pixel size: raising limits helps only when a cap is binding. Do not assume that redrawing a smaller area improves native pixel resolution. If the source limit is binding, ask the user to explicitly accept the measured resolution; only then rerun with `--max-ground-resolution` set to a value just above the measured resolution and report both values. Never upscale to claim more detail.
5. Read the generated `<terrain>.report.json`. Report selected width/height, DEM source resolution, elevation range, mesh vertex/face counts, satellite zoom, texture dimensions, effective mapped metres per pixel, OSM feature counts, height-source counts, texture status, and any zoom reduction.
6. If RhinoMCP is available, verify the current document first, then import the generated `.3dm` with Rhino's English `_Import` command. Put imported terrain on `TERRAIN::Mesh`; retain source metadata and do not delete existing scene objects. Verify units and the imported world's bounds. An empty document can retain old materials: use the image-content-based material identity produced by the generator and follow [Rhino import and verification](references/rhino-import-and-verification.md) for actual bitmap binding and recovery.
7. Capture perspective and a genuinely top-down rendered view, visually check orientation, scale, clipping, obvious spikes/voids, and whether river crossings, roads and representative footprints correspond to the image. Check that the captured viewport actually uses the intended display mode. Use `analyze_objects` for the imported mesh. Read the material again after redraw/capture and after saving a new copy; reopen that file with `rhino3dm` to verify the terrain's referenced material and bitmap content, not merely the existence of a texture somewhere in the material table.

## Input and coordinate rules

- `terrain-selection.json` must contain `bbox.west`, `bbox.south`, `bbox.east`, and `bbox.north` in WGS84 longitude/latitude.
- Reject antimeridian-crossing rectangles and zero-area selections with a clear message.
- Local origin is the southwest corner of the selected rectangle. The terrain mesh spans positive X and positive Y.
- Default Z origin is the minimum sampled elevation, so the lowest point is Z=0. Store the removed real elevation in `elevation_offset_m`. Use `--z-origin absolute` only when the user explicitly needs absolute elevations.
- Vertical exaggeration defaults to 1.0 and must be reported whenever changed.
- Local XY currently uses Web Mercator projected metres without a ground-scale correction. Label reported widths/heights as projected dimensions; do not claim survey ground distances or silently rescale the model.

## Optional building-height estimation

When the user explicitly authorizes estimated massing for missing-height footprints, follow [Building-height estimation](references/building-height-estimation.md). Preserve tagged buildings and original footprints; put assumptions in separate `OSM::Estimated_Buildings` layers with per-building methods, broad scenario bounds and confidence labels. The default generator still leaves missing-height buildings as footprints. Estimation authorization does not permit inventing extra footprints or treating assumptions as measurements.

## 忽略地形标高 / zero-elevation mode

Treat the user's phrase **“忽略地形标高”** as authorization for this exact operation within the requested site, without asking again whether buildings should keep their height:

- **地形高差归零**：set every vertex of the terrain mesh to Z=0; preserve XY, topology, UV coordinates and the correct satellite bitmap.
- **OSM 道路归零**：project every road curve onto world XY so all its geometry is at Z=0. Translating a nonplanar road's minimum Z to zero is insufficient.
- **建筑底标高归零**：translate each building individually by `-minimum_world_Z`; preserve its height, form and XY position. Include source-tagged buildings and all authorized estimated-building layers, including their root and children. Never flatten the building solids themselves with Z scaling or planar projection.
- **建筑轮廓同步归零**：project the corresponding footprint curves to Z=0.
- **水体保持原状** unless the user separately includes it. Do not silently change other site objects.

For an existing scene, save and verify a pre-operation backup, then work on duplicated geometry and validate before committing. Preserve object identities/attributes where supported. For a new site, complete any authorized building estimation before flattening the final model so later additions do not reintroduce elevated bases. This is a post-processing workflow, not an existing generator flag; `--vertical-scale 0` is invalid and does not implement these rules.

After execution and saved-file reopening, verify terrain/road/footprint Zmin=Zmax=0, each building Zmin=0 with unchanged height and XY bounds, mesh UVs/bitmap unchanged, and the requested target counts. Record intentional flattening and the retained source elevations in the report. If scene objects changed concurrently, inspect the actual differences rather than restoring unrelated user deletions to force a total-count match. Skill updates alone do not authorize applying this mode to the current scene.

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
- `references/rhino-import-and-verification.md`: material reuse, actual viewport checks, saved-file verification, and bounded request recovery.
- `references/building-height-estimation.md`: opt-in contextual height assumptions, noisy reference tags, and traceable incremental delivery.
