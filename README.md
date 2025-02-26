# `sentinel-tiles` Python Package

![CI](https://github.com/JPL-Evapotranspiration-Algorithms/sentinel_tiles/actions/workflows/ci.yml/badge.svg)

The `sentinel-tiles` Python package generates raster geometries for the Sentinel version of 100km Military Grid Reference System (MGRS) tiles.

The Julia equivalent of this package is [SentinelTiles.jl](https://github.com/STARS-Data-Fusion/SentinelTiles.jl).

[Gregory H. Halverson](https://github.com/gregory-halverson-jpl) (they/them)<br>
[gregory.h.halverson@jpl.nasa.gov](mailto:gregory.h.halverson@jpl.nasa.gov)<br>
NASA Jet Propulsion Laboratory 329G

![MGRS grid](MGRS_GZD.png)

## Installation

This package is available on PyPi as a [pip package](https://pypi.org/project/sentinel-tiles/) called `sentinel-tiles` with a dash.

```bash
pip install sentinel-tiles
```

## Usage

Import this package as `sentinel_tiles` with an under-score.

```python
import sentinel_tiles
```
