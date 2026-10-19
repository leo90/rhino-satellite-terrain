# Rhino import, bitmap identity, and alignment checks

## Preserve the correct selection and source

- The live picker output is mutable. Snapshot the confirmed bbox and timestamp into each new output directory before downloads. Keep that version's model, texture, DEM, and report together.
- Use the user's supplied private env file through `--env-file` when available; it need not be named `.env`. Never print its contents, embed the key in a page, copy it into public skill resources, or store it in a report.
- Reuse an explicit quality exception only within its authorized scope. A previously accepted 0.60 projected m/px does not change the skill's 0.5 default for unrelated work. A texture-size cap can be raised to preserve native pixels; it cannot improve native imagery detail.

## Empty geometry does not mean empty materials

Rhino may retain materials after the user clears geometry. Repeated imports with a fixed name such as `Tianditu Satellite Imagery` can reuse an earlier site's material. This was observed with correct site-03 bbox metadata and OSM geometry while the actual material still referenced the first site's bitmap.

The generator now names both materials and bitmap files by actual JPEG content: `Tianditu_<hash>` and `<model>_satellite_<hash>.jpg`, where `<hash>` is the first 16 hex characters of SHA256. Read the report's `texture_file` rather than assuming a fixed filename. A live rebuild demonstrated that unique material names alone were insufficient: Rhino still resolved a generic `site-terrain_satellite.jpg` to an earlier bitmap. Use both identities, and still perform live and saved-file checks.

When image and OSM appear misaligned:

1. Read the actual terrain GUID, bbox metadata, world bounds, units, material source/index, and that referenced material's bitmap filename. Do not inspect only an unused material or a sidecar file.
2. Compare the referenced bitmap's content hash to the expected image for the immutable selection snapshot. Equal file basenames or an existing file are insufficient; equivalent copies with different paths may be accepted when hashes match.
3. Inspect UV direction and bounds. In the current planar mapping, NW=(0,1), NE=(1,1), SW=(0,0), SE=(1,0). Compare a rendered top view to the raw satellite image and known river crossings/major streets. Preserve the user's view and display settings after inspection.
4. Fix a demonstrated wrong bitmap before considering coordinate corrections. Do not blindly apply GCJ-02 conversion, translation, rotation or scale to make two sources look similar.
5. If the correct bitmap still shows disagreement, inspect independent control features and quantify the remaining offsets; distinguish source age, footprint quality, raster crop, UV and coordinate issues. Do not claim survey alignment from a few visual correspondences.

## Repair a legacy/renderer mismatch

Consult the current API/tool documentation before scripting. A legacy `rs.MaterialTexture` edit alone may not durably update Rhino's render material. On the exact terrain object:

- Create or reuse one uniquely named, site-specific `Rhino.Render.RenderMaterial`, constructed from a `Rhino.DocObjects.Material` with the correct bitmap. Use `RenderMaterial.CreateBasicMaterial(material, doc)`, add it to `doc.RenderMaterials`, assign `obj.RenderMaterial`, and commit changes. Check the actual API signatures in the installed Rhino version.
- Do not modify a shared material used by unrelated objects. Keep original material information and object IDs for diagnosis; do not purge the document or rebuild geometry to repair a bitmap.
- Renderer-to-legacy synchronization can finish after a subsequent UI event. Mark an immediate mismatch as pending, redraw/capture, and verify in a separate tool call. A pending state is not acceptance. If unresolved, stop and inspect rather than repeatedly creating materials.
- Verify object identities and terrain bounds remain unchanged. Geometry edited by the user is preserved; do not overwrite it from an older generated source file.

API sources: [McNeel material example](https://github.com/mcneel/rhino-developer-samples/blob/8/rhinopython/SampleAddRenderMaterials.py), [two-argument material constructor](https://mcneel.github.io/rhinocommon-api-docs/api/RhinoCommon/html/M_Rhino_Render_RenderMaterial_CreateBasicMaterial_1.htm).

## Actual image and saved-copy acceptance

- If `capture_viewport(viewport="top")` yields wireframe despite a requested rendered inspection, verify the actual active viewport. Use the documented `CurrentView` and `ViewDisplayMode` interfaces to activate the intended top view and capture `active`. Restore the previous active view and display mode afterward.
- Inspect the returned image, not a success flag. Record the views actually inspected, representative correspondences and unresolved differences. Top orthographic checks avoid perspective/roof parallax being mistaken for a global offset.
- Save a new corrected copy without overwriting a user-edited source file. When an interactive command blocks, use the documented `doc.Write3dmFile(path, FileWriteOptions)` with input/dialog suppression and `UpdateDocumentPath=False` to write a copy. Verify support in the current Rhino API. See [Write3dmFile](https://mcneel.github.io/rhinocommon-api-docs/api/RhinoCommon/html/M_Rhino_RhinoDoc_Write3dmFile.htm).
- Reopen that copy with `rhino3dm`; locate the terrain by GUID and inspect its `Attributes.MaterialIndex`, the referenced material and bitmap hash. Verify object count, units, UVs and expected bounds. Keep the sidecar bitmap with the deliverable.
- A timeout or post-save output-encoding error does not prove failure. Check whether the new file exists and can be read before retrying. For scene operations, check existing object IDs/run tags and current geometry; avoid duplicate imports or double transforms.

## OSM request recovery

If Overpass fails, retain the exact bbox and requested feature set. Use bounded sequential retries or another currently verified public endpoint; GET succeeded when POST failed in one run. Check the [OSM public instance list](https://wiki.openstreetmap.org/wiki/Overpass_API#Public_Overpass_API_instances) and respect its usage rules instead of treating a historical endpoint as permanent.

Validate HTTP status, JSON `elements`, and absence of an error/partial-result `remark` before caching. Record the actual endpoint/method. Do not cache a failed response as empty valid coverage, silently drop OSM, or relabel earlier/different-bbox data as current. If service remains unavailable, preserve the prepared sources and report the missing context separately.
