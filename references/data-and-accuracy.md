# Data, coordinates, and accuracy

## Map picker

The rectangle-selection page uses the national [Tianditu WMTS image service](http://lbs.tianditu.gov.cn/server/MapService.html), layer `img_w` (Web Mercator), with a `TIANDITU_KEY` supplied from the local ignored `.env` file. A loopback-only local proxy requests the `img_w` imagery and optional `cia_w` annotation tiles using the server-side key; the key is never embedded in the page or sent to the browser. The Rhino texture uses the imagery layer alone.

Tianditu `img_w` uses the `w` spherical Web Mercator tile matrix set (EPSG:900913); its current GetCapabilities response exposes matrix identifiers 1 through 18. The picker exports the selected Leaflet bounds as WGS84 longitude/latitude for DEM and OSM requests; it does not apply a GCJ-02 conversion. The user confirmed that the applicable service terms permit fetching the selected Tianditu tiles for baking into their private Rhino research model. Preserve the attribution “Source: National Geographic Information Public Service Platform (Tianditu)” in the Rhino terrain object's metadata and report. Do not assume permission to redistribute the texture or model beyond that confirmed use.

This derivative keeps the source pipeline used by `chwang9/geo-3d-terrain-skill2.0`:

- DEM: AWS Terrain Tiles, Terrarium encoding, `elevation = R*256 + G + B/256 - 32768`.
- Imagery: National Tianditu `img_w` WMTS tiles, mosaicked locally for the selected area.
- Context features: OpenStreetMap data queried from Overpass API for the same selection extent. OSM data is licensed under ODbL 1.0; retain attribution in any displayed or delivered model.
- Selection coordinates: WGS84 longitude/latitude.
- Tile indexing and local XY: Web Mercator. Pixel rows are linear in Mercator Y, not latitude.

The output is suitable for regional terrain context, conceptual site work, views, and massing coordination. It is not a substitute for survey data. Source resolution varies by region and can be much coarser than the generated Rhino mesh spacing; denser sampling does not create new measured detail.

The default imagery quality gate targets satellite zoom 19 (capped by Tianditu at level 18) and an effective mapped texture pixel size of 0.5 metres or better, with 4096 pixels available on the longest edge and a 1000-tile budget. This controls texture sampling in the Rhino model; it cannot improve the optical resolution of the provider's underlying aerial photograph. First identify whether the texture-size/tile budget is actually binding. Raising those limits can help only in that case; it cannot improve native source resolution at maximum zoom, and a smaller selection alone does not change source metres per pixel. If the best available source resolution is coarser than 0.5 m/px, stop and ask whether the user accepts the measured value. Only after explicit acceptance, set `--max-ground-resolution` just above the measurement and report both the measured resolution and the accepted threshold. Never resample/upscale imagery to imply finer source detail.

Rhino coordinates are local metres to avoid large-coordinate precision problems. The southwest selection corner is `(0,0)`. Real-world bounds, centre coordinate, source zoom, and elevation offset are written as user strings on the terrain object and into the report JSON.

The user confirmed permission for private research use of downloaded and baked Tianditu tiles. Preserve source attribution in the model metadata and report. Any public or commercial redistribution remains outside that confirmed scope and must be checked against the applicable terms.

## OSM feature treatment

- Roads are imported as centre-line polylines on `OSM::Roads`, draped to the DEM. They are contextual linework, not measured pavement edges.
- Waterways are imported as OSM polylines; closed water ways become shallow 0.01 m capped solids on `OSM::Water`, located from the local DEM. The script does not infer missing multipolygon members or invent water elevations.
- Buildings with an OSM `height` become capped Rhino extrusions. Buildings with `building:levels` become capped extrusions using `--osm-level-height` (default 3.5 m) and receive `osm_height_source=building:levels_estimated` metadata. Buildings without either value are retained only as `OSM::Building_Footprints` curves.
- Query responses are cached by bounding box for 24 hours by default. The output report records whether cache was used, the endpoint, feature counts, and the level-height assumption.
