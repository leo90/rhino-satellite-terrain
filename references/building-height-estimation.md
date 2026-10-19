# Optional estimated building massing

Use only after explicit user authorization. Satellite plan imagery alone does not determine each building's height. Preserve the unestimated source model and footprints; do not describe a type prior as measured floor count, photogrammetry, DEM building height or shadow analysis.

## Evidence and reference pool

- Report separate counts for height-tagged solids, level-derived solids and missing-height footprints. Missing heights do not imply missing footprints; a successful OSM request does not prove complete building coverage.
- Inspect the original tags before selecting references. A 25-storey building tagged 12 m is inconsistent. Flag such cases and exclude them from the reference pool; preserve existing user/source geometry unless correcting it is also authorized.
- References can use explicit height tags or stated floor-height conversions. Both may be inaccurate. Use nearby buildings of compatible type and footprint scale, and avoid propagating a lone tower's height to an entire block.
- Do not infer high-rise status solely from footprint area. OSM `building=yes` is unclassified, not proof of a particular building use.

## Honest estimation methods

When actual floor counts or calibrated shadow observations are available, record those observations and their assumptions. Otherwise choose conservative, explicit type priors, optionally blended with multiple nearby compatible references. Values are task-specific scenario assumptions, not universal standards.

For the 2026-10-15 context model, one heuristic used at least three compatible references within 400 projected metres with comparable footprint scale; otherwise it used type assumptions. It produced mostly mid-rise assumptions and had a large reference leave-one-out error. This is a caution about uncertainty, not a validated general estimator or prescribed recipe.

- Assign `osm_height_source=user_authorized_estimate`, height in metres, method, confidence, broad low/high scenario values, reference IDs, source-footprint GUID and run ID to every new solid. Scenario bounds are not statistical confidence intervals.
- Use low confidence when evidence cannot distinguish competing heights. Publish how many heights use a type prior versus neighbour references. Do not advertise hundreds of type defaults as individually image-measured heights.
- Preserve actual input tags, assumptions and conflict exclusions in JSON/CSV so a user can replace individual heights later.

## Build, verify and continue

- Construct from the existing footprint geometry and its recorded base elevation. Check planar/closed profiles and valid closed extrusions. Regional DEM can contain surface/urban effects; do not imply survey-accurate ground bases.
- Keep estimates on separate `OSM::Estimated_Buildings` sublayers. Preserve original footprints and known-height buildings. Low/Mid/High labels are model organization, not certification of statutory building categories.
- Deliver a complete model and an additions-only `.3dm`. Import only additions into the existing live scene. Check baseline GUIDs, units and footprint bounds before import, and stop if the user edited the footprints.
- Reject already-processed run IDs/source-footprint IDs to prevent duplicates, including after unknown-result timeouts. A new output directory alone does not provide idempotence.
- Reopen saved models, verify original objects remain, and analyze the new live solids. Inspect a rendered overview while distinguishing geometry validity from accuracy of assumed heights.
- Geometry checks do not validate height predictions. Use estimated massing for contextual design only; report the lack of independent height ground truth.

The current default `prepare_rhino_terrain.py` does not implement automated missing-height estimation. For an authorized task, implement and validate a scoped supplemental script or use a separately reviewed estimator; do not invent a nonexistent command-line option.
