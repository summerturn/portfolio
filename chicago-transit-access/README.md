# Chicago: 'L' Station Access by Community Area

How much of each of Chicago's 77 community areas is within a half mile of a CTA 'L' station, and does station access line up with economic hardship? Built in QGIS with City of Chicago open data.

## Maps

| | |
| --- | --- |
| **Station walksheds** ([PDF](maps/map1_station_walksheds.pdf)) | 24.9% of the city's land area is within a half mile of an 'L' station. 23 community areas have no part within a half mile, and 22 are at least half covered. |
| **Hardship and access** ([PDF](maps/map2_hardship_access.pdf)) | Station coverage and the hardship index are not related at the community-area level (r = -0.03, n = 77). |

![Map 1](maps/map1_station_walksheds.png)

![Map 2](maps/map2_hardship_access.png)

## Method

All analysis is in NAD83 / Illinois East (ftUS), EPSG:3435, the State Plane zone the City of Chicago uses, so the half-mile buffer is exactly 2,640 ft.

1. Collapse the CTA stop list (one row per platform direction) to one point per station using `map_id`. This gives 144 stations.
2. Buffer stations by 2,640 ft and dissolve into one walkshed layer (Buffer).
3. Calculate the share of each community area inside the walkshed (Overlap Analysis).
4. Count stations per community area (Count Points in Polygon).
5. Join the ACS 2008-2012 socioeconomic table on community area number (Join Attributes by Field Value). The CSV ships with a `.csvt` so the numeric columns load as numbers.
6. Graduated symbology with manual breaks. 'L' lines use the CTA route colors.
7. Pearson correlation between coverage and hardship index across the 77 areas.

## Limitations

- Walksheds are straight-line buffers. A network buffer along streets would be smaller.
- Coverage is by land area, not population. A population-weighted version using block-level counts would be a better measure of how many people live near a station.
- The hardship index is from ACS 2008-2012, the most recent version the city has published with this index. It does not match the current station list in time.
- Buses are not included. Most of the uncovered areas have frequent bus service.

## Files

| Path | Contents |
| --- | --- |
| `chicago_transit_access.qgz` | QGIS project with styled layers and both print layouts |
| `data/chicago_source.gpkg` | Community areas, 'L' stations, 'L' lines (WGS 84) |
| `data/socioeconomic_2008_2012.csv` | ACS 2008-2012 indicators by community area (+ `.csvt` column types) |
| `data/chicago_analysis.gpkg` | Analysis outputs in EPSG:3435 |
| `data/summary_stats.json` | Numbers quoted on the maps |
| `scripts/01_download_data.py` | Downloads the source data from the City of Chicago Data Portal |
| `scripts/02_qgis_analysis_layouts.py` | PyQGIS script for the Processing steps, styling and layout export |
| `maps/` | Exported layouts (PDF and PNG) |

## Data

- Boundaries - Community Areas (`igwz-8jzy`), City of Chicago Data Portal
- CTA - System Information - List of 'L' Stops (`8pix-ypme`), Chicago Transit Authority
- CTA - 'L' (Rail) Lines (`xbyr-jnvx`), Chicago Transit Authority
- Census Data - Selected socioeconomic indicators in Chicago, 2008-2012 (`kn9c-c2s2`), U.S. Census Bureau ACS via the City of Chicago
