import logging
from datetime import timedelta
from math import floor
from os.path import abspath, dirname
from os.path import join
from typing import Set, Union

import geopandas as gpd
import mgrs
import numpy as np
import pandas as pd
import shapely
import shapely.geometry
import shapely.wkt
from affine import Affine
from dateutil import parser
from rasters import Polygon, BBox
from rasters import RasterGrid, CRS
from sentinelsat import read_geojson, geojson_to_wkt
from shapely.geometry.base import BaseGeometry

# from transform.UTM import UTM_proj4_from_latlon, UTM_proj4_from_zone

pd.options.mode.chained_assignment = None  # default='warn'

DEFAULT_ALBEDO_RESOLUTION = 10
DEFAULT_SEARCH_DAYS = 10
DEFAULT_CLOUD_MIN = 0
DEFAULT_CLOUD_MAX = 50
DEFAULT_ORDER_BY = "-beginposition"

SENTINEL_POLYGONS_FILENAME = join(abspath(dirname(__file__)), "sentinel2_tiles_world_with_land.geojson")

DEFAULT_WORKING_DIRECTORY = "."
DEFAULT_DOWNLOAD_DIRECTORY = "sentinel_download"
DEFAULT_PRODUCTS_DIRECTORY = "sentinel_products"

logger = logging.getLogger(__name__)

def UTM_proj4_from_latlon(lat: float, lon: float) -> str:
    """
    Generate a Proj4 string for a UTM projection based on latitude and longitude coordinates.
    
    The UTM zone is calculated from the longitude, and the hemisphere is determined
    from the latitude. The resulting Proj4 string can be used for coordinate transformations.
    
    Args:
        lat: Latitude in decimal degrees (-90 to 90)
        lon: Longitude in decimal degrees (-180 to 180)
    
    Returns:
        A Proj4 projection string for the appropriate UTM zone
        
    Example:
        >>> UTM_proj4_from_latlon(34.5, -118.2)
        '+proj=utm +zone=11 +ellps=WGS84 +datum=WGS84 +units=m +no_defs'
    """
    # Calculate UTM zone from longitude (6-degree wide zones, 60 zones total)
    UTM_zone = (floor((lon + 180) / 6) % 60) + 1
    
    # Build Proj4 string with appropriate hemisphere specification
    UTM_proj4 = f"+proj=utm +zone={UTM_zone} {'+south ' if lat < 0 else ''}+ellps=WGS84 +datum=WGS84 +units=m +no_defs"

    return UTM_proj4


def UTM_proj4_from_zone(zone: str) -> str:
    """
    Generate a Proj4 string for a UTM projection based on a UTM zone string.
    
    The zone string should be in the format '##N' or '##S' where ## is the zone
    number (1-60) and N/S indicates the hemisphere (North/South).
    
    Args:
        zone: UTM zone string (e.g., '33N', '15S')
    
    Returns:
        A Proj4 projection string for the specified UTM zone
        
    Raises:
        ValueError: If the hemisphere character is not 'N' or 'S'
        
    Example:
        >>> UTM_proj4_from_zone('33N')
        '+proj=utm +zone=33 +datum=WGS84 +units=m +no_defs'
    """
    # Extract zone number from all characters except the last one
    zone_number = int(zone[:-1])

    # Determine hemisphere from the last character
    if zone[-1].upper() == "N":
        hemisphere = ""  # Northern hemisphere is default in UTM
    elif zone[-1].upper() == "S":
        hemisphere = "+south "  # Southern hemisphere requires explicit flag
    else:
        raise ValueError(f"invalid hemisphere in zone: {zone}")

    # Construct the Proj4 string
    UTM_proj4 = f"+proj=utm +zone={zone_number} {hemisphere}+datum=WGS84 +units=m +no_defs"

    return UTM_proj4


def load_geojson_as_wkt(geojson_filename: str) -> str:
    """
    Load a GeoJSON file and convert it to Well-Known Text (WKT) format.
    
    Args:
        geojson_filename: Path to the GeoJSON file
    
    Returns:
        WKT string representation of the geometry
    """
    return geojson_to_wkt(read_geojson(geojson_filename))


def parse_sentinel_granule_id(granule_id: str) -> dict:
    """
    Parse a Sentinel-2 granule ID into its component parts.
    
    Extracts mission ID, product type, sensing date, processing baseline,
    relative orbit number, and tile number from a Sentinel-2 granule identifier
    following the compact naming convention.
    
    Args:
        granule_id: Sentinel-2 granule ID string (e.g.,
                   'S2A_MSIL1C_20170105T013442_N0204_R031_T53NMJ_20170105T013443.SAFE')
    
    Returns:
        Dictionary containing:
            - mission_id: Mission identifier (S2A or S2B)
            - product: Product level (MSIL1C or MSIL2A)
            - date: Datatake sensing start time as datetime object
            - baseline: PDGS processing baseline number
            - orbit: Relative orbit number
            - tile: Tile number (MGRS tile identifier)
            
    Example:
        >>> parse_sentinel_granule_id('S2A_MSIL1C_20170105T013442_N0204_R031_T53NMJ_20170105T013443.SAFE')
        {'mission_id': 'S2A', 'product': 'MSIL1C', 'date': datetime(...), ...}
    """
    # Compact Naming Convention
    #
    # The compact naming convention is arranged as follows:
    #
    # MMM_MSIXXX_YYYYMMDDHHMMSS_Nxxyy_ROOO_Txxxxx_<Product Discriminator>.SAFE
    #
    # The products contain two dates.
    #
    # The first date (YYYYMMDDHHMMSS) is the datatake sensing time.
    # The second date is the "<Product Discriminator>" field, which is 15 characters in length, and is used to distinguish between different end user products from the same datatake. Depending on the instance, the time in this field can be earlier or slightly later than the datatake sensing time.
    #
    # The other components of the filename are:
    #
    # MMM: is the mission ID(S2A/S2B)
    # MSIXXX: MSIL1C denotes the Level-1C product level/ MSIL2A denotes the Level-2A product level
    # YYYYMMDDHHMMSS: the datatake sensing start time
    # Nxxyy: the PDGS Processing Baseline number (e.g. N0204)
    # ROOO: Relative Orbit number (R001 - R143)
    # Txxxxx: Tile Number field
    # SAFE: Product Format (Standard Archive Format for Europe)
    #
    # Thus, the following filename
    #
    # S2A_MSIL1C_20170105T013442_N0204_R031_T53NMJ_20170105T013443.SAFE
    #
    # Identifies a Level-1C product acquired by Sentinel-2A on the 5th of January, 2017 at 1:34:42 AM. It was acquired over Tile 53NMJ(2) during Relative Orbit 031, and processed with PDGS Processing Baseline 02.04.
    #
    # In addition to the above changes, a a TCI (True Colour Image) in JPEG2000 format is included within the Tile folder of Level-1C products in this format. For more information on the TCI, see the Definitions page here.
    # https://sentinel.esa.int/web/sentinel/user-guides/sentinel-2-msi/naming-convention
    
    # Split the granule ID by underscores to extract components
    parts = granule_id.split("_")

    return {
        "mission_id": parts[0],        # S2A or S2B
        "product": parts[1],            # MSIL1C or MSIL2A
        "date": parser.parse(parts[2]), # Datatake sensing time
        "baseline": parts[3],           # Processing baseline (e.g., N0204)
        "orbit": parts[4],              # Relative orbit (R001-R143)
        "tile": parts[5][1:]            # Tile number without 'T' prefix
    }


def resize_affine(affine: Affine, cell_size: float) -> Affine:
    """
    Resize an affine transformation matrix to a new cell size.
    
    Modifies the scale components of the affine transformation while preserving
    translation and shear components. Used to adjust raster grid resolution.
    
    Args:
        affine: Original affine transformation matrix
        cell_size: New cell size (spatial resolution) in the CRS units
    
    Returns:
        New affine transformation with updated cell size
        
    Raises:
        ValueError: If the affine parameter is not an Affine object
    """
    if not isinstance(affine, Affine):
        raise ValueError("invalid affine transform")

    # Create new affine with updated scale factors (a and e components)
    # a (cell_size): pixel width, e (-cell_size): pixel height (negative for north-up orientation)
    new_affine = Affine(cell_size, affine.b, affine.c, affine.d, -cell_size, affine.f)

    return new_affine


def UTC_to_solar(time_UTC, lon: float):
    """
    Convert UTC time to solar time based on longitude.
    
    Solar time adjusts UTC by the longitude-based time offset, where each 15 degrees
    of longitude represents one hour of time difference.
    
    Args:
        time_UTC: UTC time (datetime or compatible object)
        lon: Longitude in decimal degrees (-180 to 180)
    
    Returns:
        Solar time adjusted for the given longitude
    """
    # Calculate time offset: longitude in radians / π * 12 hours
    # This converts longitude to hours (360° = 24 hours, so 15° = 1 hour)
    return time_UTC + timedelta(hours=(np.radians(lon) / np.pi * 12))

class MGRS(mgrs.MGRS):
    """
    Extended MGRS (Military Grid Reference System) class with bounding box support.
    
    Inherits from mgrs.MGRS and adds functionality to compute bounding boxes
    for MGRS tiles at various precision levels.
    """
    
    def bbox(self, tile: str) -> BBox:
        """
        Compute the bounding box for an MGRS tile.
        
        The precision of the tile is determined by the length of the tile string:
        - 5 characters: 100km precision
        - 7 characters: 10km precision
        - 9 characters: 1km precision
        - 11 characters: 100m precision
        - 13 characters: 10m precision
        - 15 characters: 1m precision
        
        Args:
            tile: MGRS tile identifier string
        
        Returns:
            BBox object with the tile's bounding box in UTM coordinates
            
        Raises:
            ValueError: If the tile string length is not recognized
        """
        # Determine precision based on tile string length
        if len(tile) == 5:
            precision = 100000
        elif len(tile) == 7:
            precision = 10000
        elif len(tile) == 9:
            precision = 1000
        elif len(tile) == 11:
            precision = 100
        elif len(tile) == 13:
            precision = 10
        elif len(tile) == 15:
            precision = 1
        else:
            raise ValueError(f"unrecognized MGRS tile: {tile}")

        # Convert MGRS tile to UTM coordinates (southwest corner)
        zone, hemisphere, xmin, ymin = self.MGRSToUTM(tile)
        
        # Get the appropriate CRS for this UTM zone
        crs = CRS(UTM_proj4_from_zone(f"{int(zone)}{str(hemisphere).upper()}"))
        
        # Calculate the northeast corner by adding precision to southwest corner
        xmax = xmin + precision
        ymax = ymin + precision

        # Create and return the bounding box
        bbox = BBox(
            xmin=xmin,
            ymin=ymin,
            xmax=xmax,
            ymax=ymax,
            crs=crs
        )

        return bbox


class SentinelTileGrid(MGRS):
    """
    Sentinel-2 tile grid management and spatial operations.
    
    This class provides methods for working with Sentinel-2 MGRS tiles, including:
    - Finding tiles that intersect with a target geometry
    - Computing tile footprints and bounding boxes
    - Generating raster grids for tiles
    - Coordinate transformations between geographic and UTM projections
    
    The class uses a GeoJSON file containing all Sentinel-2 tile polygons worldwide
    and supports operations like finding nearest tiles, calculating intersections,
    and eliminating redundant tile coverage.
    
    Attributes:
        target_resolution: Default resolution in meters for generated raster grids
    """
    
    def __init__(self, *args, target_resolution: float = 30, **kwargs):
        """
        Initialize the SentinelTileGrid.
        
        Args:
            target_resolution: Default spatial resolution in meters for raster grids (default: 30)
            *args: Additional positional arguments passed to parent MGRS class
            **kwargs: Additional keyword arguments passed to parent MGRS class
        """
        super(SentinelTileGrid, self).__init__()
        self.target_resolution = target_resolution
        self._sentinel_polygons = None  # Lazy-loaded polygon data

    def __repr__(self) -> str:
        return f"SentinelTileGrid(target_resolution={self.target_resolution})"

    @property
    def sentinel_polygons(self) -> gpd.GeoDataFrame:
        """
        Lazily load and return the Sentinel-2 tile polygons GeoDataFrame.
        
        The polygons are loaded from a GeoJSON file on first access and cached
        for subsequent use.
        
        Returns:
            GeoDataFrame containing all Sentinel-2 tile polygons with their
            attributes (Name, geometry, Land flag, etc.)
        """
        if self._sentinel_polygons is None:
            self._sentinel_polygons = gpd.read_file(SENTINEL_POLYGONS_FILENAME)

        return self._sentinel_polygons

    @property
    def crs(self) -> CRS:
        """
        Get the coordinate reference system of the Sentinel-2 tile polygons.
        
        Returns:
            CRS object representing the coordinate reference system (typically EPSG:4326)
        """
        return CRS(self._sentinel_polygons.crs)

    def UTM_proj4(self, tile: str) -> str:
        """
        Get the UTM Proj4 projection string for a given tile.
        
        Args:
            tile: Sentinel-2 tile identifier (e.g., '53NMJ')
        
        Returns:
            Proj4 string for the tile's UTM zone
        """
        # Extract UTM zone and hemisphere from the tile identifier
        zone, hemisphere, _, _ = self.MGRSToUTM(tile)
        proj4 = UTM_proj4_from_zone(f"{int(zone)}{str(hemisphere).upper()}")

        return proj4

    def footprint(
            self,
            tile: str,
            in_UTM: bool = False,
            round_UTM: bool = True,
            in_2d: bool = True) -> Polygon:
        """
        Get the footprint polygon for a Sentinel-2 tile.
        
        Args:
            tile: Sentinel-2 tile identifier (e.g., '53NMJ')
            in_UTM: If True, transform polygon to UTM coordinates (default: False)
            round_UTM: If True and in_UTM=True, round UTM coordinates to integers (default: True)
            in_2d: If True, return only 2D coordinates (default: True)
        
        Returns:
            Polygon object representing the tile footprint
            
        Raises:
            ValueError: If the tile is not found in the polygon database
        """
        try:
            # Look up the polygon geometry for this tile
            polygon = Polygon(self.sentinel_polygons[self.sentinel_polygons.Name == tile].iloc[0]["geometry"], crs=self.crs)
        except Exception as e:
            raise ValueError(f"polygon for target {tile} not found")

        # Convert to 2D if requested (remove Z coordinate if present)
        if in_2d:
            polygon = Polygon([xy[0:2] for xy in polygon.exterior.coords], crs=self.crs)

        # Transform to UTM if requested
        if in_UTM:
            UTM_proj4 = self.UTM_proj4(tile)
            polygon = polygon.to_crs(UTM_proj4)

            # Round UTM coordinates to integers for cleaner values
            if round_UTM:
                polygon = Polygon([[round(item) for item in xy] for xy in polygon.exterior.coords], crs=polygon.crs)

        return polygon

    def footprint_UTM(self, tile: str) -> Polygon:
        """
        Get the footprint polygon for a tile in UTM coordinates.
        
        Convenience method that returns the tile footprint transformed to UTM
        with rounded coordinates.
        
        Args:
            tile: Sentinel-2 tile identifier (e.g., '53NMJ')
        
        Returns:
            Polygon in UTM coordinates with rounded integer values
        """
        return self.footprint(
            tile=tile,
            in_UTM=True,
            round_UTM=True,
            in_2d=True
        )

    def bbox(self, tile: str, MGRS: bool = False) -> BBox:
        """
        Get the bounding box for a Sentinel-2 tile.
        
        For standard 5-character Sentinel-2 tiles, returns the actual footprint-based
        bounding box. For other MGRS tile formats, delegates to parent MGRS class.
        
        Args:
            tile: Tile identifier
            MGRS: If True, force use of MGRS-based bbox calculation (default: False)
        
        Returns:
            BBox object representing the tile's bounding box in UTM coordinates
        """
        # Use parent MGRS bbox method for non-standard tiles or if explicitly requested
        if len(tile) != 5 or MGRS:
            return super(SentinelTileGrid, self).bbox(tile=tile)

        # For standard Sentinel-2 tiles, use the actual footprint
        polygon = self.footprint(
            tile=tile,
            in_UTM=True,
            round_UTM=True,
            in_2d=True
        )

        bbox = polygon.bbox

        return bbox

    def tiles(self, target_geometry: shapely.geometry.shape) -> Set[str]:
        """
        Find all Sentinel-2 tiles that intersect with a target geometry.
        
        Args:
            target_geometry: Shapely geometry or WKT string representing the area of interest
        
        Returns:
            Set of tile identifiers that intersect the target geometry
        """
        # Convert WKT string to geometry if needed
        if isinstance(target_geometry, str):
            target_geometry = shapely.wkt.loads(target_geometry)

        # Find all tiles that intersect the target geometry
        matches = self.sentinel_polygons[self.sentinel_polygons.intersects(target_geometry)]
        tiles = set(sorted(list(matches.apply(lambda row: row.Name, axis=1))))

        return tiles

    def tile_footprints(
            self,
            target_geometry: Union[shapely.geometry.shape, gpd.GeoDataFrame],
            calculate_area: bool = False,
            calculate_centroid_distance: bool = False,
            eliminate_redundancy: bool = False) -> gpd.GeoDataFrame:
        """
        Get detailed footprint information for tiles intersecting a target geometry.
        
        Args:
            target_geometry: Target area as Shapely geometry, WKT string, or GeoDataFrame
            calculate_area: If True, calculate intersection area for each tile (default: False)
            calculate_centroid_distance: If True, calculate distance from target centroid (default: False)
            eliminate_redundancy: If True, remove redundant tiles that don't add coverage (default: False)
        
        Returns:
            GeoDataFrame with columns:
                - tile: Tile identifier
                - geometry: Tile polygon geometry
                - area: Intersection area (if calculate_area=True)
                - distance: Distance from target centroid (if calculate_centroid_distance=True)
        
        Raises:
            ValueError: If target_geometry is not a valid type
        """
        # Convert WKT string to geometry if needed
        if isinstance(target_geometry, str):
            target_geometry = shapely.wkt.loads(target_geometry)

        if isinstance(target_geometry, BaseGeometry):
            target_geometry = gpd.GeoDataFrame(geometry=[target_geometry], crs="EPSG:4326")

        if not isinstance(target_geometry, gpd.GeoDataFrame):
            raise ValueError("invalid target geometry")

        matches = self.sentinel_polygons[
            self.sentinel_polygons.intersects(target_geometry.to_crs(self.sentinel_polygons.crs).union_all())]
        matches.rename(columns={"Name": "tile"}, inplace=True)
        tiles = matches[["tile", "geometry"]]

        if calculate_area or eliminate_redundancy:
            centroid = target_geometry.to_crs("EPSG:4326").union_all().centroid
            lon = centroid.x
            lat = centroid.y
            projection = UTM_proj4_from_latlon(lat, lon)
            tiles_UTM = tiles.to_crs(projection)
            target_UTM = target_geometry.to_crs(projection)
            tiles_UTM["area"] = gpd.overlay(tiles_UTM, target_UTM).geometry.area
            # overlap = gpd.overlay(tiles_UTM, target_UTM)
            # area = overlap.geometry.area

            # Eliminate redundant tiles that don't add new coverage
            if eliminate_redundancy:
                # Sort by area (largest first) to prioritize tiles with most coverage
                tiles_UTM.sort_values(by="area", ascending=False, inplace=True)
                tiles_UTM.reset_index(inplace=True)
                tiles_UTM = tiles_UTM[["tile", "area", "geometry"]]
                
                # Track remaining uncovered area
                remaining_target = target_UTM.union_all()
                remaining_target_area = remaining_target.area
                indices = []

                # Iteratively subtract tile coverage to find minimal tile set
                for i, (tile, area, geometry) in tiles_UTM.iterrows():
                    remaining_target = remaining_target - geometry
                    previous_area = remaining_target_area
                    remaining_target_area = remaining_target.area
                    change_in_area = remaining_target_area - previous_area

                    # Keep tile only if it reduces uncovered area
                    if change_in_area != 0:
                        indices.append(i)

                    # Stop if target is fully covered
                    if remaining_target_area == 0:
                        break

                tiles_UTM = tiles_UTM.iloc[indices, :]
                tiles = tiles_UTM.to_crs(tiles.crs)
                tiles.sort_values(by="tile", ascending=True, inplace=True)
                tiles = tiles[["tile", "area", "geometry"]]
            else:
                # tiles["area"] = np.array(area)
                tiles = tiles[["tile", "area", "geometry"]]

        # Calculate distance from target centroid if requested
        if calculate_centroid_distance:
            # Get target centroid in lat/lon
            centroid_latlon = target_geometry.to_crs("EPSG:4326").union_all().centroid
            lon = centroid_latlon.x
            lat = centroid_latlon.y
            
            # Use UTM projection centered on target for accurate distance calculation
            projection = UTM_proj4_from_latlon(lat, lon)
            target_centroid = target_geometry.to_crs(projection).union_all().centroid
            
            # Calculate distance from each tile centroid to target centroid
            tiles_UTM = tiles.to_crs(projection)
            tiles_UTM["centroid"] = tiles_UTM.geometry.centroid
            tiles["distance"] = tiles_UTM["centroid"].apply(lambda centroid: target_centroid.distance(centroid))
            
            # Sort by distance (nearest first)
            tiles.sort_values(by="distance", ascending=True, inplace=True)
            
            # Reorder columns to put geometry last
            tiles = tiles[[col for col in tiles.columns if col != 'geometry'] + ['geometry']]

        return tiles
    
    def nearest(self, target_geometry: Union[shapely.geometry.shape, gpd.GeoDataFrame]) -> str:
        """
        Find the nearest Sentinel-2 tile to a target geometry.
        
        Args:
            target_geometry: Target area as Shapely geometry, WKT string, or GeoDataFrame
        
        Returns:
            Tile identifier of the nearest tile to the target geometry centroid
        """
        return self.tile_footprints(target_geometry, calculate_centroid_distance=True).iloc[0].tile

    def grid(self, tile: str, cell_size: float = None, buffer: float = 0) -> RasterGrid:
        """
        Generate a raster grid for a Sentinel-2 tile.
        
        Args:
            tile: Sentinel-2 tile identifier
            cell_size: Spatial resolution in meters (default: uses target_resolution)
            buffer: Buffer distance in meters to expand the grid beyond tile boundary (default: 0)
        
        Returns:
            RasterGrid object configured for the tile's extent and projection
        """
        # Use default resolution if not specified
        if cell_size is None:
            cell_size = self.target_resolution

        # Get tile bounding box and optionally buffer it
        bbox = self.bbox(tile).buffer(buffer)
        projection = self.UTM_proj4(tile)
        
        # Create raster grid from bounding box
        grid = RasterGrid.from_bbox(bbox=bbox, cell_size=cell_size, crs=projection)

        return grid

    def land(self, tile: str) -> bool:
        """
        Check if a Sentinel-2 tile contains land area.
        
        Args:
            tile: Sentinel-2 tile identifier
        
        Returns:
            True if the tile contains land, False if it's ocean-only
        """
        return self.sentinel_polygons[self.sentinel_polygons["Name"].apply(lambda name: name == tile)]["Land"].iloc[0]

    def centroid(self, tile: str) -> shapely.geometry.Point:
        """
        Get the centroid point of a Sentinel-2 tile.
        
        Args:
            tile: Sentinel-2 tile identifier
        
        Returns:
            Shapely Point representing the tile's centroid in EPSG:4326
        """
        return self.footprint(tile).centroid

    def tile_grids(
            self,
            target_geometry: Union[shapely.geometry.shape, gpd.GeoDataFrame],
            eliminate_redundancy: bool = True) -> gpd.GeoDataFrame:
        """
        Get raster grids for all tiles intersecting a target geometry.
        
        Args:
            target_geometry: Target area as Shapely geometry, WKT string, or GeoDataFrame
            eliminate_redundancy: If True, remove redundant tiles (default: True)
        
        Returns:
            GeoDataFrame with columns:
                - tile: Tile identifier
                - area: Intersection area
                - grid: RasterGrid object for the tile
                - geometry: Tile polygon geometry
        """
        # Get tile footprints with area calculation
        tiles = self.tile_footprints(
            target_geometry=target_geometry,
            eliminate_redundancy=eliminate_redundancy,
        )

        # Generate raster grid for each tile
        tiles["grid"] = tiles["tile"].apply(lambda tile: self.grid(tile))
        tiles = tiles[["tile", "area", "grid", "geometry"]]

        return tiles

# Pre-initialized instance for convenient access to Sentinel-2 tile grid functionality
sentinel_tiles = SentinelTileGrid()
