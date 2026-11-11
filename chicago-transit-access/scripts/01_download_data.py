# Step 1: pull the source layers from the City of Chicago Data Portal.
# Needs: geopandas, pandas, requests
# Output: data/chicago_source.gpkg (EPSG:4326) and data/socioeconomic_2008_2012.csv

import io
import os

import geopandas as gpd
import pandas as pd
import requests

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(PROJECT, "data")
OUT = os.path.join(DATA, "chicago_source.gpkg")
PORTAL = "https://data.cityofchicago.org/resource"
HEADERS = {"User-Agent": "gis-portfolio/1.0"}


def get(url):
    r = requests.get(url, headers=HEADERS, timeout=120)
    r.raise_for_status()
    return r


def main():
    # community area boundaries (77 areas)
    ca = gpd.read_file(io.BytesIO(get(f"{PORTAL}/igwz-8jzy.geojson?$limit=200").content))
    ca = ca.rename(columns={"area_numbe": "area_num", "community": "community"})
    ca["area_num"] = ca["area_num"].astype(int)
    ca["community"] = ca["community"].str.title().replace({"Ohare": "O'Hare", "Mckinley Park": "McKinley Park"})
    ca = ca[["area_num", "community", "geometry"]].set_crs("EPSG:4326", allow_override=True)
    print("community areas:", len(ca))

    # CTA 'L' stops -> one point per station (map_id)
    stops = pd.DataFrame(get(f"{PORTAL}/8pix-ypme.json?$limit=1000").json())
    stops["lat"] = stops["location"].apply(lambda d: float(d["latitude"]))
    stops["lon"] = stops["location"].apply(lambda d: float(d["longitude"]))
    lines = ["red", "blue", "g", "brn", "p", "pexp", "y", "pnk", "o"]
    for c in lines:
        if c not in stops:
            stops[c] = False
    agg = {"station_name": "first", "station_descriptive_name": "first", "ada": "max",
           "lat": "mean", "lon": "mean", **{c: "max" for c in lines}}
    st = stops.groupby("map_id").agg(agg).reset_index()
    stations = gpd.GeoDataFrame(st.drop(columns=["lat", "lon"]),
                                geometry=gpd.points_from_xy(st["lon"], st["lat"]), crs="EPSG:4326")
    print("stations:", len(stations))

    # CTA 'L' line geometry
    rail = gpd.read_file(io.BytesIO(get(f"{PORTAL}/xbyr-jnvx.geojson?$limit=2000").content))
    print("rail line columns:", list(rail.columns))
    print("rail segments:", len(rail))

    # socioeconomic indicators by community area (ACS 2008-2012)
    se = pd.DataFrame(get(f"{PORTAL}/kn9c-c2s2.json?$limit=200").json())
    se = se[pd.to_numeric(se["ca"], errors="coerce").notna()].copy()  # drop the city-wide row
    se["ca"] = se["ca"].astype(float).astype(int)
    csv_path = os.path.join(DATA, "socioeconomic_2008_2012.csv")
    se.to_csv(csv_path, index=False)
    # .csvt tells GDAL/QGIS the column types (otherwise everything loads as text)
    types = ['"Integer"' if c == "ca" else '"String"' if c == "community_area_name" else '"Real"'
             for c in se.columns]
    with open(csv_path + "t", "w") as f:
        f.write(",".join(types))
    print("socioeconomic rows:", len(se))

    if os.path.exists(OUT):
        os.remove(OUT)
    ca.to_file(OUT, layer="community_areas", driver="GPKG")
    stations.to_file(OUT, layer="l_stations", driver="GPKG")
    rail.to_file(OUT, layer="l_lines", driver="GPKG")


if __name__ == "__main__":
    main()
