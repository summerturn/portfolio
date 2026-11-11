# Step 1: download OSM features for the study area and save them to a GeoPackage.
# Needs: geopandas, shapely, requests
# Output: data/osm_raw.gpkg (EPSG:4326) with layers study_area, streams, parks, buildings

import json
import os
import time

import geopandas as gpd
import requests
from shapely.geometry import LineString, Polygon, box
from shapely.ops import polygonize, unary_union

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(PROJECT, "data")
CACHE = os.path.join(DATA, "osm_boulder.json")
OUT = os.path.join(DATA, "osm_raw.gpkg")

# central Boulder, CO (south, west, north, east)
S, W, N, E = 39.995, -105.295, 40.035, -105.235

QUERY = f"""
[out:json][timeout:120];
(
  way["waterway"~"^(river|stream|creek)$"]({S},{W},{N},{E});
  way["leisure"="park"]({S},{W},{N},{E});
  relation["leisure"="park"]({S},{W},{N},{E});
  way["building"]({S},{W},{N},{E});
);
out geom;
"""


# reference layers for the basemap: main roads and the CU campus
BASEMAP_QUERY = f"""
[out:json][timeout:120];
(
  way["highway"~"^(motorway|trunk|primary|secondary|tertiary)$"]({S},{W},{N},{E});
  way["amenity"="university"]({S},{W},{N},{E});
  relation["amenity"="university"]({S},{W},{N},{E});
);
out geom;
"""
BASEMAP_CACHE = os.path.join(DATA, "osm_basemap.json")


def download(query=QUERY, cache=CACHE):
    if os.path.exists(cache):
        print("using cached", cache)
        with open(cache) as f:
            return json.load(f)
    for url in ["https://overpass-api.de/api/interpreter",
                "https://overpass.kumi.systems/api/interpreter",
                "https://overpass-api.de/api/interpreter"]:
        try:
            r = requests.post(url, data={"data": query}, timeout=180,
                              headers={"User-Agent": "gis-portfolio/1.0"})
            r.raise_for_status()
            data = r.json()
            with open(cache, "w") as f:
                json.dump(data, f)
            return data
        except Exception as e:
            print("overpass failed:", url, e)
            time.sleep(15)
    raise SystemExit("could not download OSM data")


def polygon_from_relation(el):
    outer = [LineString([(p["lon"], p["lat"]) for p in m["geometry"]])
             for m in el.get("members", []) if m.get("role") == "outer" and m.get("geometry")]
    polys = list(polygonize(unary_union(outer))) if outer else []
    return unary_union(polys) if polys else None


def main():
    data = download()
    streams, parks, buildings = [], [], []
    for el in data["elements"]:
        tags = el.get("tags", {})
        if el["type"] == "relation" and tags.get("leisure") == "park":
            geom = polygon_from_relation(el)
            if geom is not None:
                parks.append({"osm_id": el["id"], "name": tags.get("name", ""), "geometry": geom})
            continue
        if el["type"] != "way" or "geometry" not in el:
            continue
        pts = [(p["lon"], p["lat"]) for p in el["geometry"]]
        if "waterway" in tags:
            streams.append({"osm_id": el["id"], "name": tags.get("name", ""),
                            "waterway": tags["waterway"], "geometry": LineString(pts)})
        elif len(pts) >= 4 and pts[0] == pts[-1]:
            poly = Polygon(pts)
            if not poly.is_valid:
                poly = poly.buffer(0)
            if poly.is_empty:
                continue
            if tags.get("leisure") == "park":
                parks.append({"osm_id": el["id"], "name": tags.get("name", ""), "geometry": poly})
            elif "building" in tags:
                buildings.append({"osm_id": el["id"], "building": tags["building"], "geometry": poly})

    if os.path.exists(OUT):
        os.remove(OUT)
    gpd.GeoDataFrame([{"name": "Central Boulder study area", "geometry": box(W, S, E, N)}],
                     crs="EPSG:4326").to_file(OUT, layer="study_area", driver="GPKG")
    for name, rows in [("streams", streams), ("parks", parks), ("buildings", buildings)]:
        gpd.GeoDataFrame(rows, crs="EPSG:4326").to_file(OUT, layer=name, driver="GPKG")
        print(f"{name}: {len(rows)}")

    roads, campus = [], []
    for el in download(BASEMAP_QUERY, BASEMAP_CACHE)["elements"]:
        tags = el.get("tags", {})
        if tags.get("amenity") == "university":
            if el["type"] == "relation":
                geom = polygon_from_relation(el)
            elif "geometry" in el and len(el["geometry"]) >= 4:
                pts = [(p["lon"], p["lat"]) for p in el["geometry"]]
                geom = Polygon(pts) if pts[0] == pts[-1] else None
            else:
                geom = None
            if geom is not None and not geom.is_empty:
                campus.append({"osm_id": el["id"], "name": tags.get("name", ""), "geometry": geom})
        elif el["type"] == "way" and "highway" in tags and "geometry" in el:
            roads.append({"osm_id": el["id"], "name": tags.get("name", ""), "highway": tags["highway"],
                          "geometry": LineString([(p["lon"], p["lat"]) for p in el["geometry"]])})
    gpd.GeoDataFrame(roads, crs="EPSG:4326").to_file(OUT, layer="roads", driver="GPKG")
    gpd.GeoDataFrame(campus, crs="EPSG:4326").to_file(OUT, layer="campus", driver="GPKG")
    print(f"roads: {len(roads)}")
    print(f"campus: {len(campus)} {[c['name'] for c in campus]}")


if __name__ == "__main__":
    main()
