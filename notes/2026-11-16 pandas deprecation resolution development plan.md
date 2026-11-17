# `sentinel-tiles` Development Plan: Remove Deprecated `chained_assignment` Option & Fix `Pandas4Warning`

**Date:** 2026-11-16  
**Target Repository:** `sentinel-tiles` (`1.1.1`)  
**Affected File:** `sentinel_tiles/sentinel_tiles.py`

---

## 1. Problem Summary

When importing `sentinel_tiles` under pandas 3.x (used in `ECOv003-L2T-STARS` and downstream ECOSTRESS/SBG environments), module initialization executes line 24 of `sentinel_tiles/sentinel_tiles.py`:

```python
pd.options.mode.chained_assignment = None  # default='warn'
```

In pandas 3.0+, Copy-on-Write (CoW) is enabled by default, `SettingWithCopyWarning` has been removed, and configuring `pd.options.mode.chained_assignment` emits a `Pandas4Warning` on every import—polluting test suites and logs across all downstream consumers:

```text
Pandas4Warning: The 'mode.chained_assignment' option is deprecated. It has had no effect since pandas 3.0, which removed the SettingWithCopyWarning it controlled. Chained assignment now emits a ChainedAssignmentError warning instead; use warnings.filterwarnings with category=ChainedAssignmentError to silence or escalate it. This option will be removed in pandas 4.0.
```

Additionally, mutating global `pd.options` at import time is an anti-pattern for a library because it alters global pandas behavior for the entire Python process.

---

## 2. Root-Cause Audit in `sentinel_tiles/sentinel_tiles.py`

1. **Line 24 (`pd.options.mode.chained_assignment = None`):** Originally added to suppress `SettingWithCopyWarning` in pandas 1.x/2.x when mutating filtered GeoDataFrame slices in `SentinelTileGrid.tile_footprints()`.
2. **Lines 471–474 (`tile_footprints`):** `matches` is a boolean-filtered view/slice of `self.sentinel_polygons`, and `matches.rename(columns={"Name": "tile"}, inplace=True)` mutates that slice in place.
3. **Lines 489–522 (`tile_footprints`):** `tiles_UTM.sort_values(..., inplace=True)` and `tiles_UTM.reset_index(inplace=True)` perform in-place chained mutations on derived GeoDataFrames.

---

## 3. Development Plan

### Step 1: Remove Global `pd.options.mode.chained_assignment` Mutation (`sentinel_tiles/sentinel_tiles.py`)
Delete line 24 (`pd.options.mode.chained_assignment = None`) so importing `sentinel_tiles` emits no `Pandas4Warning` and does not modify global pandas settings.

### Step 2: Replace In-Place Slice Mutations with Copy-on-Write Safe Operations (`sentinel_tiles/sentinel_tiles.py`)
Refactor `SentinelTileGrid.tile_footprints()` to use non-inplace DataFrame/GeoDataFrame operations (`rename(...)`, `sort_values(...)`, `reset_index(drop=True)`), ensuring compatibility across pandas 2.x, 3.x, and 4.0 without triggering `ChainedAssignmentError` or `SettingWithCopyWarning`.

```diff
--- a/sentinel_tiles/sentinel_tiles.py
+++ b/sentinel_tiles/sentinel_tiles.py
@@ -20,8 +20,6 @@ from shapely.geometry.base import BaseGeometry
 
 # from transform.UTM import UTM_proj4_from_latlon, UTM_proj4_from_zone
 
-pd.options.mode.chained_assignment = None  # default='warn'
-
 DEFAULT_ALBEDO_RESOLUTION = 10
 DEFAULT_SEARCH_DAYS = 10
 DEFAULT_CLOUD_MIN = 0
@@ -470,8 +468,8 @@ class SentinelTileGrid(MGRS):
 
         matches = self.sentinel_polygons[
             self.sentinel_polygons.intersects(target_geometry.to_crs(self.sentinel_polygons.crs).union_all())]
-        matches.rename(columns={"Name": "tile"}, inplace=True)
-        tiles = matches[["tile", "geometry"]]
+        tiles = matches.rename(columns={"Name": "tile"})[["tile", "geometry"]].copy()
 
         if calculate_area or eliminate_redundancy:
             centroid = target_geometry.to_crs("EPSG:4326").union_all().centroid
@@ -486,9 +484,11 @@ class SentinelTileGrid(MGRS):
             # Eliminate redundant tiles that don't add new coverage
             if eliminate_redundancy:
                 # Sort by area (largest first) to prioritize tiles with most coverage
-                tiles_UTM.sort_values(by="area", ascending=False, inplace=True)
-                tiles_UTM.reset_index(inplace=True)
-                tiles_UTM = tiles_UTM[["tile", "area", "geometry"]]
+                tiles_UTM = (
+                    tiles_UTM.sort_values(by="area", ascending=False)
+                    .reset_index(drop=True)[["tile", "area", "geometry"]]
+                )
                 
                 # Track remaining uncovered area
                 remaining_target = target_UTM.union_all()
@@ -510,7 +510,7 @@ class SentinelTileGrid(MGRS):
 
                 tiles_UTM = tiles_UTM.iloc[indices, :]
                 tiles = tiles_UTM.to_crs(tiles.crs)
-                tiles.sort_values(by="tile", ascending=True, inplace=True)
+                tiles = tiles.sort_values(by="tile", ascending=True)
                 tiles = tiles[["tile", "area", "geometry"]]
             else:
                 # tiles["area"] = np.array(area)
@@ -532,7 +532,7 @@ class SentinelTileGrid(MGRS):
             tiles["distance"] = tiles_UTM["centroid"].apply(lambda centroid: target_centroid.distance(centroid))
             
             # Sort by distance (nearest first)
-            tiles.sort_values(by="distance", ascending=True, inplace=True)
+            tiles = tiles.sort_values(by="distance", ascending=True)
             
             # Reorder columns to put geometry last
             tiles = tiles[[col for col in tiles.columns if col != 'geometry'] + ['geometry']]
```

---

## 4. Verification Plan

1. **Add warning-strict import/footprint test in `tests/test_sentinel_tiles.py`:**
   - Run `import sentinel_tiles` and `sentinel_tiles.tile_footprints(...)` under `pytest -W error::FutureWarning` (or `warnings.catch_warnings(record=True)`) to confirm zero `Pandas4Warning` or `ChainedAssignmentError` warnings are emitted.
2. **Run full test suite:**
   ```bash
   pytest -W error
   ```
3. **Release:** Bump `version` in `pyproject.toml` (`1.1.1` $\rightarrow$ `1.1.2`) and publish so downstream consumers (`ECOv003-L2T-STARS`, `VCD43NRT`) automatically pick up the clean import.