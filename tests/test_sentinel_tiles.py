"""
Unit tests for the sentinel_tiles module.

Tests cover all utility functions, the MGRS class, and the SentinelTileGrid class.
"""

import pytest
from datetime import datetime, timedelta
from shapely.geometry import Point, box, Polygon as ShapelyPolygon
import geopandas as gpd
from affine import Affine

from sentinel_tiles import (
    UTM_proj4_from_latlon,
    UTM_proj4_from_zone,
    load_geojson_as_wkt,
    parse_sentinel_granule_id,
    resize_affine,
    UTC_to_solar,
    MGRS,
    SentinelTileGrid,
    sentinel_tiles
)


class TestUTMProjections:
    """Test UTM projection utility functions."""
    
    def test_UTM_proj4_from_latlon_northern_hemisphere(self):
        """Test UTM projection generation for northern hemisphere."""
        proj4 = UTM_proj4_from_latlon(34.5, -118.2)
        assert "+proj=utm" in proj4
        assert "+zone=11" in proj4
        assert "+south" not in proj4
        assert "+datum=WGS84" in proj4
        assert "+units=m" in proj4
    
    def test_UTM_proj4_from_latlon_southern_hemisphere(self):
        """Test UTM projection generation for southern hemisphere."""
        proj4 = UTM_proj4_from_latlon(-34.5, 150.0)
        assert "+proj=utm" in proj4
        assert "+zone=56" in proj4
        assert "+south" in proj4
        assert "+datum=WGS84" in proj4
    
    def test_UTM_proj4_from_latlon_edge_cases(self):
        """Test UTM projection at zone boundaries."""
        # Test at prime meridian
        proj4 = UTM_proj4_from_latlon(0, 0)
        assert "+zone=31" in proj4
        
        # Test at antimeridian
        proj4 = UTM_proj4_from_latlon(0, 180)
        assert "+zone=1" in proj4
    
    def test_UTM_proj4_from_zone_north(self):
        """Test UTM projection from zone string (northern)."""
        proj4 = UTM_proj4_from_zone('11N')
        assert "+proj=utm" in proj4
        assert "+zone=11" in proj4
        assert "+south" not in proj4
        assert "+datum=WGS84" in proj4
    
    def test_UTM_proj4_from_zone_south(self):
        """Test UTM projection from zone string (southern)."""
        proj4 = UTM_proj4_from_zone('11S')
        assert "+proj=utm" in proj4
        assert "+zone=11" in proj4
        assert "+south" in proj4
        assert "+datum=WGS84" in proj4
    
    def test_UTM_proj4_from_zone_invalid_hemisphere(self):
        """Test UTM projection with invalid hemisphere."""
        with pytest.raises(ValueError, match="invalid hemisphere"):
            UTM_proj4_from_zone('11X')
    
    def test_UTM_proj4_from_zone_case_insensitive(self):
        """Test that hemisphere specification is case-insensitive."""
        proj4_upper = UTM_proj4_from_zone('11N')
        proj4_lower = UTM_proj4_from_zone('11n')
        assert proj4_upper == proj4_lower


class TestGranuleIDParsing:
    """Test Sentinel-2 granule ID parsing."""
    
    def test_parse_sentinel_granule_id_valid(self):
        """Test parsing a valid Sentinel-2 granule ID."""
        granule_id = 'S2A_MSIL1C_20170105T013442_N0204_R031_T53NMJ_20170105T013443.SAFE'
        metadata = parse_sentinel_granule_id(granule_id)
        
        assert metadata['mission_id'] == 'S2A'
        assert metadata['product'] == 'MSIL1C'
        assert isinstance(metadata['date'], datetime)
        assert metadata['date'].year == 2017
        assert metadata['date'].month == 1
        assert metadata['date'].day == 5
        assert metadata['baseline'] == 'N0204'
        assert metadata['orbit'] == 'R031'
        assert metadata['tile'] == '53NMJ'
    
    def test_parse_sentinel_granule_id_s2b(self):
        """Test parsing a Sentinel-2B granule ID."""
        granule_id = 'S2B_MSIL2A_20200315T103639_N0214_R008_T32TPS_20200315T141522.SAFE'
        metadata = parse_sentinel_granule_id(granule_id)
        
        assert metadata['mission_id'] == 'S2B'
        assert metadata['product'] == 'MSIL2A'
        assert metadata['tile'] == '32TPS'
        assert metadata['orbit'] == 'R008'


class TestAffineTransform:
    """Test affine transformation utilities."""
    
    def test_resize_affine_valid(self):
        """Test resizing an affine transformation."""
        original = Affine(10, 0, 100, 0, -10, 200)
        resized = resize_affine(original, 30)
        
        assert resized.a == 30  # Cell width
        assert resized.e == -30  # Cell height (negative)
        assert resized.c == original.c  # X offset preserved
        assert resized.f == original.f  # Y offset preserved
    
    def test_resize_affine_invalid_input(self):
        """Test that invalid affine input raises ValueError."""
        with pytest.raises(ValueError, match="invalid affine transform"):
            resize_affine("not an affine", 30)
    
    def test_resize_affine_preserves_translation(self):
        """Test that translation components are preserved."""
        original = Affine(10, 0, 500000, 0, -10, 6000000)
        resized = resize_affine(original, 20)
        
        assert resized.c == 500000
        assert resized.f == 6000000


class TestTimeConversion:
    """Test time conversion utilities."""
    
    def test_UTC_to_solar_westward(self):
        """Test UTC to solar time conversion for western longitudes."""
        utc_time = datetime(2017, 1, 5, 12, 0, 0)
        lon = -120.0  # 8 hours behind
        solar_time = UTC_to_solar(utc_time, lon)
        
        # Solar time should be earlier
        assert solar_time < utc_time
    
    def test_UTC_to_solar_eastward(self):
        """Test UTC to solar time conversion for eastern longitudes."""
        utc_time = datetime(2017, 1, 5, 12, 0, 0)
        lon = 120.0  # 8 hours ahead
        solar_time = UTC_to_solar(utc_time, lon)
        
        # Solar time should be later
        assert solar_time > utc_time
    
    def test_UTC_to_solar_prime_meridian(self):
        """Test UTC to solar time at prime meridian."""
        utc_time = datetime(2017, 1, 5, 12, 0, 0)
        lon = 0.0
        solar_time = UTC_to_solar(utc_time, lon)
        
        # Should be approximately the same (within seconds)
        assert abs((solar_time - utc_time).total_seconds()) < 1


class TestMGRSClass:
    """Test the MGRS class functionality."""
    
    def test_mgrs_bbox_100km(self):
        """Test bounding box for 100km tile."""
        mgrs = MGRS()
        bbox = mgrs.bbox('53NMJ')
        
        assert bbox.x_max - bbox.x_min == 100000
        assert bbox.y_max - bbox.y_min == 100000
        assert bbox.crs is not None
    
    def test_mgrs_bbox_10km(self):
        """Test bounding box for 10km tile."""
        mgrs = MGRS()
        bbox = mgrs.bbox('53NMJ12')
        
        assert bbox.x_max - bbox.x_min == 10000
        assert bbox.y_max - bbox.y_min == 10000
    
    def test_mgrs_bbox_1km(self):
        """Test bounding box for 1km tile."""
        mgrs = MGRS()
        bbox = mgrs.bbox('53NMJ1234')
        
        assert bbox.x_max - bbox.x_min == 1000
        assert bbox.y_max - bbox.y_min == 1000
    
    def test_mgrs_bbox_invalid_length(self):
        """Test that invalid tile length raises error."""
        mgrs = MGRS()
        with pytest.raises(ValueError, match="unrecognized MGRS tile"):
            mgrs.bbox('53N')


class TestSentinelTileGrid:
    """Test the SentinelTileGrid class."""
    
    def test_initialization_default_resolution(self):
        """Test default initialization."""
        grid = SentinelTileGrid()
        assert grid.target_resolution == 30
    
    def test_initialization_custom_resolution(self):
        """Test initialization with custom resolution."""
        grid = SentinelTileGrid(target_resolution=10)
        assert grid.target_resolution == 10
    
    def test_sentinel_polygons_loaded(self):
        """Test that sentinel polygons are loaded."""
        grid = SentinelTileGrid()
        polygons = grid.sentinel_polygons
        
        assert isinstance(polygons, gpd.GeoDataFrame)
        assert len(polygons) > 0
        assert 'Name' in polygons.columns
        assert 'geometry' in polygons.columns
    
    def test_crs_property(self):
        """Test CRS property."""
        grid = SentinelTileGrid()
        # Access sentinel_polygons first to trigger loading
        _ = grid.sentinel_polygons
        crs = grid.crs
        
        assert crs is not None
    
    def test_UTM_proj4(self):
        """Test UTM projection retrieval for a tile."""
        grid = SentinelTileGrid()
        proj4 = grid.UTM_proj4('53NMJ')
        
        assert "+proj=utm" in proj4
        assert "+zone=53" in proj4
    
    def test_footprint_geographic(self):
        """Test footprint in geographic coordinates."""
        grid = SentinelTileGrid()
        footprint = grid.footprint('11SLA')
        
        assert footprint is not None
        assert footprint.crs is not None
        assert len(footprint.exterior.coords) > 0
    
    def test_footprint_UTM(self):
        """Test footprint in UTM coordinates."""
        grid = SentinelTileGrid()
        footprint = grid.footprint_UTM('11SLA')
        
        assert footprint is not None
        # UTM coordinates should be in meters (large values)
        bounds = footprint.bounds
        assert bounds[0] > 100000  # xmin
    
    def test_footprint_invalid_tile(self):
        """Test that invalid tile raises error."""
        grid = SentinelTileGrid()
        with pytest.raises(ValueError, match="polygon for target .* not found"):
            grid.footprint('INVALID')
    
    def test_bbox(self):
        """Test bounding box retrieval."""
        grid = SentinelTileGrid()
        bbox = grid.bbox('11SLA')
        
        assert bbox is not None
        assert bbox.x_max > bbox.x_min
        assert bbox.y_max > bbox.y_min
    
    def test_tiles_from_point(self):
        """Test finding tiles from a point."""
        grid = SentinelTileGrid()
        point = Point(-118.2, 34.5)
        tiles = grid.tiles(point.buffer(0.1))
        
        assert isinstance(tiles, set)
        assert len(tiles) > 0
    
    def test_tiles_from_bbox(self):
        """Test finding tiles from a bounding box."""
        grid = SentinelTileGrid()
        bbox_geom = box(-119, 34, -118, 35)
        tiles = grid.tiles(bbox_geom)
        
        assert isinstance(tiles, set)
        assert len(tiles) > 0
    
    def test_tiles_from_wkt(self):
        """Test finding tiles from WKT string."""
        grid = SentinelTileGrid()
        wkt = "POLYGON ((-119 34, -118 34, -118 35, -119 35, -119 34))"
        tiles = grid.tiles(wkt)
        
        assert isinstance(tiles, set)
        assert len(tiles) > 0
    
    def test_tile_footprints_basic(self):
        """Test tile footprints retrieval."""
        grid = SentinelTileGrid()
        bbox_geom = box(-119, 34, -118, 35)
        footprints = grid.tile_footprints(bbox_geom)
        
        assert isinstance(footprints, gpd.GeoDataFrame)
        assert len(footprints) > 0
        assert 'tile' in footprints.columns
        assert 'geometry' in footprints.columns
    
    def test_tile_footprints_with_area(self):
        """Test tile footprints with area calculation and redundancy elimination."""
        grid = SentinelTileGrid()
        bbox_geom = box(-119, 34, -118, 35)
        # Note: calculate_area needs eliminate_redundancy or it won't be in final output
        footprints = grid.tile_footprints(
            bbox_geom,
            calculate_area=True,
            eliminate_redundancy=True
        )
        
        assert 'area' in footprints.columns
        assert len(footprints) > 0
    
    def test_tile_footprints_with_distance(self):
        """Test tile footprints with distance calculation."""
        grid = SentinelTileGrid()
        bbox_geom = box(-119, 34, -118, 35)
        footprints = grid.tile_footprints(bbox_geom, calculate_centroid_distance=True)
        
        assert 'distance' in footprints.columns
        assert all(footprints['distance'] >= 0)
    
    def test_tile_footprints_eliminate_redundancy(self):
        """Test tile footprints with redundancy elimination."""
        grid = SentinelTileGrid()
        bbox_geom = box(-119, 34, -118, 35)
        
        footprints_all = grid.tile_footprints(bbox_geom)
        footprints_reduced = grid.tile_footprints(
            bbox_geom,
            eliminate_redundancy=True
        )
        
        # Both should have valid results
        assert len(footprints_all) > 0
        assert len(footprints_reduced) > 0
        # Reduced might have fewer or equal tiles
        assert len(footprints_reduced) <= len(footprints_all)
    
    def test_tile_footprints_geodataframe_input(self):
        """Test tile footprints with GeoDataFrame input."""
        grid = SentinelTileGrid()
        gdf = gpd.GeoDataFrame(
            geometry=[box(-119, 34, -118, 35)],
            crs='EPSG:4326'
        )
        footprints = grid.tile_footprints(gdf)
        
        assert isinstance(footprints, gpd.GeoDataFrame)
        assert len(footprints) > 0
    
    def test_nearest(self):
        """Test nearest tile finding."""
        grid = SentinelTileGrid()
        point = Point(-118.2, 34.5)
        nearest_tile = grid.nearest(point)
        
        assert isinstance(nearest_tile, str)
        assert len(nearest_tile) == 5  # Standard Sentinel-2 tile length
    
    def test_grid_default_resolution(self):
        """Test grid generation with default resolution."""
        grid = SentinelTileGrid(target_resolution=30)
        tile_grid = grid.grid('11SLA')
        
        assert tile_grid is not None
        assert tile_grid.shape[0] > 0
        assert tile_grid.shape[1] > 0
    
    def test_grid_custom_resolution(self):
        """Test grid generation with custom resolution."""
        grid = SentinelTileGrid()
        tile_grid = grid.grid('11SLA', cell_size=10)
        
        assert tile_grid is not None
        # Higher resolution should have more cells
        assert tile_grid.shape[0] > 3000
    
    def test_grid_with_buffer(self):
        """Test grid generation with buffer."""
        grid = SentinelTileGrid()
        grid_no_buffer = grid.grid('11SLA', cell_size=30)
        grid_with_buffer = grid.grid('11SLA', cell_size=30, buffer=1000)
        
        # Buffered grid should be larger
        assert grid_with_buffer.shape[0] > grid_no_buffer.shape[0]
        assert grid_with_buffer.shape[1] > grid_no_buffer.shape[1]
    
    def test_land(self):
        """Test land flag retrieval."""
        grid = SentinelTileGrid()
        # Most tiles should have a land flag
        has_land = grid.land('11SLA')
        
        assert isinstance(has_land, (bool, np.bool_))
    
    def test_centroid(self):
        """Test centroid retrieval."""
        grid = SentinelTileGrid()
        centroid = grid.centroid('11SLA')
        
        # Check it's a Point-like object
        assert hasattr(centroid, 'x')
        assert hasattr(centroid, 'y')
        assert centroid.x != 0
        assert centroid.y != 0
    
    def test_tile_grids(self):
        """Test tile grids generation."""
        grid = SentinelTileGrid()
        bbox_geom = box(-119, 34, -118, 35)
        tile_grids = grid.tile_grids(bbox_geom)
        
        assert isinstance(tile_grids, gpd.GeoDataFrame)
        assert 'tile' in tile_grids.columns
        assert 'area' in tile_grids.columns
        assert 'grid' in tile_grids.columns
        assert 'geometry' in tile_grids.columns
        assert len(tile_grids) > 0


class TestModuleLevelInstance:
    """Test the pre-initialized sentinel_tiles instance."""
    
    def test_sentinel_tiles_instance_exists(self):
        """Test that sentinel_tiles instance exists."""
        assert sentinel_tiles is not None
        assert isinstance(sentinel_tiles, SentinelTileGrid)
    
    def test_sentinel_tiles_instance_usable(self):
        """Test that the instance is immediately usable."""
        bbox = sentinel_tiles.bbox('11SLA')
        assert bbox is not None
    
    def test_sentinel_tiles_default_resolution(self):
        """Test that instance has default resolution."""
        assert sentinel_tiles.target_resolution == 30


class TestIntegration:
    """Integration tests combining multiple features."""
    
    def test_complete_workflow(self):
        """Test a complete workflow from area to grids."""
        # Define area of interest
        study_area = box(-119.5, 34.0, -118.0, 35.0)
        
        # Find tiles
        tiles_df = sentinel_tiles.tile_footprints(
            study_area,
            calculate_area=True,
            eliminate_redundancy=True
        )
        
        assert len(tiles_df) > 0
        
        # Check each tile
        for idx, row in tiles_df.iterrows():
            tile = row['tile']
            
            # Get properties
            has_land = sentinel_tiles.land(tile)
            centroid = sentinel_tiles.centroid(tile)
            footprint = sentinel_tiles.footprint(tile)
            
            assert isinstance(has_land, (bool, np.bool_))
            assert centroid is not None
            assert footprint is not None
            
            # Generate grid
            tile_grid = sentinel_tiles.grid(tile, cell_size=30)
            assert tile_grid.shape[0] > 0
    
    def test_granule_id_to_tile_properties(self):
        """Test extracting and using tile info from granule ID."""
        granule_id = 'S2A_MSIL1C_20170105T013442_N0204_R031_T53NMJ_20170105T013443.SAFE'
        metadata = parse_sentinel_granule_id(granule_id)
        tile = metadata['tile']
        
        # Use tile to get properties
        bbox = sentinel_tiles.bbox(tile)
        footprint = sentinel_tiles.footprint(tile)
        has_land = sentinel_tiles.land(tile)
        
        assert bbox is not None
        assert footprint is not None
        assert isinstance(has_land, (bool, np.bool_))


# Import numpy for boolean type checking
import numpy as np


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
