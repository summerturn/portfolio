# Step 2: walkshed analysis in QGIS Processing, a styled QGIS project for desktop
# review, and GeoJSON exports for the Leaflet web map.
# Run with the Python bundled with QGIS. Outputs: data/chicago_analysis.gpkg,
# chicago_transit_access.qgz, data/summary_stats.json, webmap/data/*.geojson

import json
import os
import statistics
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qgis.core import (
    QgsApplication,
    QgsCategorizedSymbolRenderer,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransformContext,
    QgsFillSymbol,
    QgsGraduatedSymbolRenderer,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsProject,
    QgsRendererCategory,
    QgsRendererRange,
    QgsVectorFileWriter,
    QgsVectorLayer,
)

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(PROJECT_DIR, "data")
WEB = os.path.join(PROJECT_DIR, "webmap", "data")
SRC = os.path.join(DATA, "chicago_source.gpkg")
CSV = os.path.join(DATA, "socioeconomic_2008_2012.csv")
GPKG = os.path.join(DATA, "chicago_analysis.gpkg")
QGZ = os.path.join(PROJECT_DIR, "chicago_transit_access.qgz")

CRS = "EPSG:3435"  # NAD83 / Illinois East (ftUS)
HALF_MILE_FT = 2640

QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX", "/Applications/QGIS.app/Contents/MacOS"), True)
qgs = QgsApplication([], False)
qgs.initQgis()
sys.path.append(os.path.join(QgsApplication.pkgDataPath(), "python", "plugins"))
import processing  # noqa: E402
from processing.core.Processing import Processing  # noqa: E402

Processing.initialize()


def run(alg, params):
    params.setdefault("OUTPUT", "TEMPORARY_OUTPUT")
    out = processing.run(alg, params)["OUTPUT"]
    return out if isinstance(out, QgsVectorLayer) else QgsVectorLayer(out, alg, "ogr")


def src(name):
    return run("native:reprojectlayer", {"INPUT": f"{SRC}|layername={name}",
                                         "TARGET_CRS": QgsCoordinateReferenceSystem(CRS)})


# ---------------- analysis ----------------
areas = src("community_areas")
stations = src("l_stations")
rail = src("l_lines")

walkshed = run("native:buffer", {"INPUT": stations, "DISTANCE": HALF_MILE_FT, "SEGMENTS": 16,
                                 "END_CAP_STYLE": 0, "JOIN_STYLE": 0, "DISSOLVE": True})
walkshed.setName("walkshed")

overlap = run("native:calculatevectoroverlaps", {"INPUT": areas, "LAYERS": [walkshed]})
pc_field = next(f.name() for f in overlap.fields() if f.name().endswith("_pc"))
area_field = next(f.name() for f in overlap.fields() if f.name().endswith("_area"))
overlap = run("native:renametablefield", {"INPUT": overlap, "FIELD": pc_field, "NEW_NAME": "pct_walkshed"})
overlap = run("native:renametablefield", {"INPUT": overlap, "FIELD": area_field, "NEW_NAME": "walkshed_sqft"})
counted = run("native:countpointsinpolygon", {"POLYGONS": overlap, "POINTS": stations, "FIELD": "stations"})

csv = QgsVectorLayer(CSV, "socioeconomic", "ogr")  # column types come from the .csvt next to it
if not csv.isValid():
    raise SystemExit("could not read socioeconomic csv")
joined = run("native:joinattributestable", {
    "INPUT": counted, "FIELD": "area_num", "INPUT_2": csv, "FIELD_2": "ca",
    "FIELDS_TO_COPY": ["hardship_index", "per_capita_income_", "percent_households_below_poverty"],
    "METHOD": 1, "DISCARD_NONMATCHING": False, "PREFIX": ""})

walkshed_city = run("native:clip", {"INPUT": walkshed, "OVERLAY": areas})

rows = [(float(f["pct_walkshed"] or 0), float(f["hardship_index"])) for f in joined.getFeatures()]
pct = [r[0] for r in rows]
hard = [r[1] for r in rows]
city_area = sum(f.geometry().area() for f in areas.getFeatures())
covered_area = sum(f.geometry().area() for f in walkshed_city.getFeatures())
low = [h for p, h in zip(pct, hard) if p < 10]
high = [h for p, h in zip(pct, hard) if p >= 50]
stats = {
    "community_areas": len(rows),
    "stations": stations.featureCount(),
    "pct_city_area_in_walkshed": round(100 * covered_area / city_area, 1),
    "areas_with_no_station_within_half_mile": sum(1 for p in pct if p == 0),
    "areas_under_10pct": len(low),
    "areas_50pct_or_more": len(high),
    "mean_hardship_under_10pct": round(statistics.mean(low), 1),
    "mean_hardship_50pct_or_more": round(statistics.mean(high), 1),
    "pearson_r_pct_vs_hardship": round(statistics.correlation(pct, hard), 2),
}
print(json.dumps(stats, indent=2))

for lyr, name in [(areas, "community_areas"), (stations, "l_stations"), (rail, "l_lines"),
                  (walkshed_city, "walkshed_half_mile"), (joined, "community_area_access")]:
    lyr.setName(name)
if os.path.exists(GPKG):
    os.remove(GPKG)
processing.run("native:package", {"LAYERS": [areas, stations, rail, walkshed_city, joined],
                                  "OUTPUT": GPKG, "OVERWRITE": True, "SAVE_STYLES": False})
with open(os.path.join(DATA, "summary_stats.json"), "w") as f:
    json.dump(stats, f, indent=2)

# ---------------- GeoJSON for the web map ----------------
os.makedirs(WEB, exist_ok=True)


def to_geojson(layer, name, fields, simplify_ft=0):
    lyr = run("native:retainfields", {"INPUT": layer, "FIELDS": fields}) if fields else layer
    if simplify_ft:
        lyr = run("native:simplifygeometries", {"INPUT": lyr, "METHOD": 0, "TOLERANCE": simplify_ft})
    lyr = run("native:reprojectlayer", {"INPUT": lyr, "TARGET_CRS": QgsCoordinateReferenceSystem("EPSG:4326")})
    path = os.path.join(WEB, name + ".geojson")
    if os.path.exists(path):
        os.remove(path)
    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = "GeoJSON"
    opts.layerOptions = ["COORDINATE_PRECISION=5", "RFC7946=YES"]
    err = QgsVectorFileWriter.writeAsVectorFormatV3(lyr, path, QgsCoordinateTransformContext(), opts)
    if err[0] != QgsVectorFileWriter.WriterError.NoError:
        raise SystemExit(f"geojson export failed for {name}: {err}")
    print(f"{name}.geojson {os.path.getsize(path) // 1024} KB")


to_geojson(joined, "community_areas",
           ["area_num", "community", "pct_walkshed", "stations", "hardship_index",
            "per_capita_income_", "percent_households_below_poverty"], simplify_ft=40)
to_geojson(walkshed_city, "walkshed", [], simplify_ft=20)
to_geojson(rail, "l_lines", ["legend", "lines"], simplify_ft=20)
to_geojson(stations, "l_stations",
           ["station_name", "ada", "red", "blue", "g", "brn", "p", "pexp", "y", "pnk", "o"])
with open(os.path.join(WEB, "summary.json"), "w") as f:
    json.dump(stats, f, indent=2)

# ---------------- QGIS project (styled, for desktop review) ----------------
project = QgsProject.instance()
project.setCrs(QgsCoordinateReferenceSystem(CRS))
project.setTitle("Chicago 'L' station access by community area")


def load(table, title):
    lyr = QgsVectorLayer(f"{GPKG}|layername={table}", title, "ogr")
    if not lyr.isValid():
        raise SystemExit(f"layer failed to load: {table}")
    project.addMapLayer(lyr)
    return lyr


L_access = load("community_area_access", "Area within 1/2 mile of a station")
L_walk = load("walkshed_half_mile", "1/2 mile station walkshed")
L_rail = load("l_lines", "CTA 'L' lines")
L_sta = load("l_stations", "'L' stations")

ranges = []
for lo, hi, color, label in [(-0.001, 0.001, "247,247,247", "None"), (0.001, 10, "198,219,239", "Under 10%"),
                             (10, 25, "158,202,225", "10 - 25%"), (25, 50, "107,174,214", "25 - 50%"),
                             (50, 75, "49,130,189", "50 - 75%"), (75, 100.001, "8,81,156", "75 - 100%")]:
    sym = QgsFillSymbol.createSimple({"color": color, "outline_color": "255,255,255", "outline_width": "0.25"})
    ranges.append(QgsRendererRange(lo, hi, sym, label))
L_access.setRenderer(QgsGraduatedSymbolRenderer("pct_walkshed", ranges))
L_walk.renderer().setSymbol(QgsFillSymbol.createSimple(
    {"style": "no", "outline_color": "20,20,20", "outline_style": "dash", "outline_width": "0.3"}))
cats = [QgsRendererCategory(code, QgsLineSymbol.createSimple({"line_color": c, "line_width": "0.7"}), label)
        for code, c, label in [("RD", "198,12,48", "Red"), ("BL", "0,161,222", "Blue"),
                               ("BR", "98,54,27", "Brown"), ("GR", "0,155,58", "Green"),
                               ("OR", "249,70,28", "Orange"), ("PK", "226,126,166", "Pink"),
                               ("PR", "82,35,152", "Purple"), ("YL", "249,227,0", "Yellow"),
                               ("ML", "60,60,60", "Shared track (Loop)")]]
L_rail.setRenderer(QgsCategorizedSymbolRenderer("legend", cats))
L_sta.renderer().setSymbol(QgsMarkerSymbol.createSimple(
    {"name": "circle", "color": "255,255,255", "outline_color": "0,0,0", "outline_width": "0.25", "size": "1.3"}))

project.write(QGZ)
print("saved", QGZ)
qgs.exitQgis()
