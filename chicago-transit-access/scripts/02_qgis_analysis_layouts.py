# Step 2: walkshed analysis in QGIS Processing, styling, print layouts and export.
# Run with the Python bundled with QGIS. Outputs: data/chicago_analysis.gpkg,
# chicago_transit_access.qgz, maps/*.pdf, maps/*.png, data/summary_stats.json

import json
import os
import statistics
import sys
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCategorizedSymbolRenderer,
    QgsCoordinateReferenceSystem,
    QgsFillSymbol,
    QgsGraduatedSymbolRenderer,
    QgsLayoutExporter,
    QgsLayoutItemLabel,
    QgsLayoutItemLegend,
    QgsLayoutItemMap,
    QgsLayoutItemPage,
    QgsLayoutItemPicture,
    QgsLayoutItemScaleBar,
    QgsLayoutItemShape,
    QgsLayoutPoint,
    QgsLayoutSize,
    QgsLegendStyle,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsPalLayerSettings,
    QgsPrintLayout,
    QgsProject,
    QgsRectangle,
    QgsRendererCategory,
    QgsRendererRange,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)
from qgis.PyQt.QtGui import QColor, QFont

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(PROJECT_DIR, "data")
MAPS = os.path.join(PROJECT_DIR, "maps")
SRC = os.path.join(DATA, "chicago_source.gpkg")
CSV = os.path.join(DATA, "socioeconomic_2008_2012.csv")
GPKG = os.path.join(DATA, "chicago_analysis.gpkg")
QGZ = os.path.join(PROJECT_DIR, "chicago_transit_access.qgz")

CRS = "EPSG:3435"  # NAD83 / Illinois East (ftUS)
HALF_MILE_FT = 2640
AUTHOR = "Summerlyn Turner"
DATE = "October 2025"
MM = Qgis.LayoutUnit.Millimeters

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

# share of each community area inside the walkshed
overlap = run("native:calculatevectoroverlaps", {"INPUT": areas, "LAYERS": [walkshed]})
pc_field = next(f.name() for f in overlap.fields() if f.name().endswith("_pc"))
area_field = next(f.name() for f in overlap.fields() if f.name().endswith("_area"))
overlap = run("native:renametablefield", {"INPUT": overlap, "FIELD": pc_field, "NEW_NAME": "pct_walkshed"})
overlap = run("native:renametablefield", {"INPUT": overlap, "FIELD": area_field, "NEW_NAME": "walkshed_sqft"})

# stations per community area
counted = run("native:countpointsinpolygon", {"POLYGONS": overlap, "POINTS": stations, "FIELD": "stations"})

# join the ACS 2008-2012 socioeconomic table on community area number
csv = QgsVectorLayer(CSV, "socioeconomic", "ogr")  # column types come from the .csvt next to it
if not csv.isValid():
    raise SystemExit("could not read socioeconomic csv")
joined = run("native:joinattributestable", {
    "INPUT": counted, "FIELD": "area_num", "INPUT_2": csv, "FIELD_2": "ca",
    "FIELDS_TO_COPY": ["hardship_index", "per_capita_income_", "percent_households_below_poverty"],
    "METHOD": 1, "DISCARD_NONMATCHING": False, "PREFIX": ""})

walkshed_city = run("native:clip", {"INPUT": walkshed, "OVERLAY": areas})

rows = [(f["community"], float(f["pct_walkshed"] or 0), float(f["hardship_index"]), int(f["stations"]))
        for f in joined.getFeatures()]
pct = [r[1] for r in rows]
hard = [r[2] for r in rows]
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
    "mean_hardship_under_10pct": round(statistics.mean(low), 1) if low else None,
    "mean_hardship_50pct_or_more": round(statistics.mean(high), 1) if high else None,
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

# ---------------- project and styling ----------------
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
L_hard = load("community_area_access", "Hardship index (ACS 2008-2012)")
L_walk = load("walkshed_half_mile", "1/2 mile station walkshed")
L_rail = load("l_lines", "CTA 'L' lines")
L_sta = load("l_stations", "'L' stations")


def graduated(layer, field, classes):
    ranges = []
    for lo, hi, color, label in classes:
        sym = QgsFillSymbol.createSimple({"color": color, "outline_color": "255,255,255", "outline_width": "0.25"})
        ranges.append(QgsRendererRange(lo, hi, sym, label))
    layer.setRenderer(QgsGraduatedSymbolRenderer(field, ranges))


graduated(L_access, "pct_walkshed", [
    (-0.001, 0.001, "247,247,247", "None"),
    (0.001, 10, "198,219,239", "Under 10%"),
    (10, 25, "158,202,225", "10 - 25%"),
    (25, 50, "107,174,214", "25 - 50%"),
    (50, 75, "49,130,189", "50 - 75%"),
    (75, 100.001, "8,81,156", "75 - 100%"),
])
graduated(L_hard, "hardship_index", [
    (0, 20, "255,255,212", "1 - 20 (lowest hardship)"),
    (20, 40, "254,217,142", "21 - 40"),
    (40, 60, "254,153,41", "41 - 60"),
    (60, 80, "217,95,14", "61 - 80"),
    (80, 101, "153,52,4", "81 - 100 (highest hardship)"),
])

L_walk.renderer().setSymbol(QgsFillSymbol.createSimple(
    {"style": "no", "outline_color": "20,20,20", "outline_style": "dash", "outline_width": "0.3"}))

line_colors = [("RD", "198,12,48", "Red"), ("BL", "0,161,222", "Blue"), ("BR", "98,54,27", "Brown"),
               ("GR", "0,155,58", "Green"), ("OR", "249,70,28", "Orange"), ("PK", "226,126,166", "Pink"),
               ("PR", "82,35,152", "Purple"), ("YL", "249,227,0", "Yellow"),
               ("ML", "60,60,60", "Shared track (Loop)")]
cats = [QgsRendererCategory(code, QgsLineSymbol.createSimple({"line_color": c, "line_width": "0.7"}), label)
        for code, c, label in line_colors]
L_rail.setRenderer(QgsCategorizedSymbolRenderer("legend", cats))

L_sta.renderer().setSymbol(QgsMarkerSymbol.createSimple(
    {"name": "circle", "color": "255,255,255", "outline_color": "0,0,0", "outline_width": "0.25", "size": "1.3"}))

# community area name labels
lab_fmt = QgsTextFormat()
lab_fmt.setFont(QFont("Arial"))
lab_fmt.setSize(4.6)
lab_fmt.setColor(QColor(30, 30, 30))
lab_buf = QgsTextBufferSettings()
lab_buf.setEnabled(True)
lab_buf.setSize(0.5)
lab_buf.setColor(QColor(255, 255, 255))
lab_fmt.setBuffer(lab_buf)
for lyr in (L_access, L_hard):
    pal = QgsPalLayerSettings()
    pal.fieldName = "community"
    pal.placement = Qgis.LabelPlacement.OverPoint
    pal.setFormat(lab_fmt)
    lyr.setLabeling(QgsVectorLayerSimpleLabeling(pal))
    lyr.setLabelsEnabled(True)


# ---------------- layouts (Letter portrait) ----------------
def text_item(layout, text, x, y, w, h, size, bold=False):
    item = QgsLayoutItemLabel(layout)
    tf = QgsTextFormat()
    font = QFont("Arial")
    font.setBold(bold)
    tf.setFont(font)
    tf.setSize(size)
    tf.setColor(QColor(0, 0, 0))
    item.setTextFormat(tf)
    item.setText(text)
    layout.addLayoutItem(item)
    item.attemptMove(QgsLayoutPoint(x, y, MM))
    item.attemptResize(QgsLayoutSize(w, h, MM))
    return item


def north_arrow_svg():
    for base in QgsApplication.svgPaths():
        for name in ("NorthArrow_02.svg", "NorthArrow_01.svg"):
            p = os.path.join(base, "arrows", name)
            if os.path.exists(p):
                return p
    return None


def make_layout(name, title, subtitle, map_layers, legend_layers, results):
    layout = QgsPrintLayout(project)
    layout.initializeDefaults()
    layout.setName(name)
    layout.pageCollection().page(0).setPageSize("Letter", QgsLayoutItemPage.Orientation.Portrait)
    project.layoutManager().addLayout(layout)

    border = QgsLayoutItemShape(layout)
    border.setShapeType(QgsLayoutItemShape.Shape.Rectangle)
    border.setSymbol(QgsFillSymbol.createSimple({"style": "no", "outline_color": "0,0,0", "outline_width": "0.6"}))
    layout.addLayoutItem(border)
    border.attemptMove(QgsLayoutPoint(6, 6, MM))
    border.attemptResize(QgsLayoutSize(203.9, 267.4, MM))

    text_item(layout, title, 11, 9, 194, 8, 15, bold=True)
    text_item(layout, subtitle, 11, 18, 194, 6, 9.5)

    ext = QgsRectangle(L_access.extent())
    ext.combineExtentWith(L_rail.extent())
    ext.grow(1500)
    map_w = 134
    map_h = min(186, map_w * ext.height() / ext.width())
    m = QgsLayoutItemMap(layout)
    m.setFrameEnabled(True)
    layout.addLayoutItem(m)
    m.attemptMove(QgsLayoutPoint(11, 27, MM))
    m.attemptResize(QgsLayoutSize(map_w, map_h, MM))
    m.setLayers(map_layers)
    m.setKeepLayerSet(True)
    m.zoomToExtent(ext)

    x0 = 11 + map_w + 6
    pw = 205 - x0
    arrow = north_arrow_svg()
    if arrow:
        pic = QgsLayoutItemPicture(layout)
        pic.setPicturePath(arrow)
        layout.addLayoutItem(pic)
        pic.attemptMove(QgsLayoutPoint(x0 + pw / 2 - 6, 30, MM))
        pic.attemptResize(QgsLayoutSize(12, 16, MM))

    legend = QgsLayoutItemLegend(layout)
    legend.setTitle("Legend")
    legend.setLinkedMap(m)
    if hasattr(legend, "setSyncMode") and hasattr(Qgis, "LegendSyncMode"):
        legend.setSyncMode(Qgis.LegendSyncMode.Manual)
    else:
        legend.setAutoUpdateModel(False)
    root = legend.model().rootGroup()
    root.clear()
    for lyr in legend_layers:
        root.addLayer(lyr)
    legend.setSymbolWidth(5.5)
    legend.setSymbolHeight(3.2)
    legend.setWrapString("|")
    legend.setBackgroundEnabled(False)
    for st, size, bold in [(QgsLegendStyle.Style.Title, 10.5, True), (QgsLegendStyle.Style.Group, 8.5, False),
                           (QgsLegendStyle.Style.Subgroup, 8, False), (QgsLegendStyle.Style.SymbolLabel, 7.5, False)]:
        style = legend.style(st)
        tf = style.textFormat()
        lf = QFont("Arial")
        lf.setBold(bold)
        tf.setFont(lf)
        tf.setSize(size)
        style.setTextFormat(tf)
        legend.setStyle(st, style)
    layout.addLayoutItem(legend)
    legend.attemptMove(QgsLayoutPoint(x0, 49, MM))
    legend.adjustBoxSize()

    text_item(layout, results, 11, 27 + map_h + 6, map_w, 266 - (27 + map_h + 6), 8.5)

    sb = QgsLayoutItemScaleBar(layout)
    sb.setStyle("Single Box")
    sb.setLinkedMap(m)
    sb.setUnits(Qgis.DistanceUnit.Miles)
    sb.setUnitLabel("mi")
    sb.setUnitsPerSegment(1)
    sb.setNumberOfSegments(2)
    sb.setNumberOfSegmentsLeft(0)
    sb.setHeight(2.2)
    sbf = QgsTextFormat()
    sbf.setFont(QFont("Arial"))
    sbf.setSize(7.5)
    sb.setTextFormat(sbf)
    layout.addLayoutItem(sb)
    sb.attemptMove(QgsLayoutPoint(x0, 205, MM))

    info = (f"Prepared by: {AUTHOR}\nDate: {DATE}\n"
            "Projection: NAD83 / Illinois East (ftUS), EPSG:3435\n"
            "Data: City of Chicago Data Portal (community areas, CTA 'L' stops and lines); "
            "U.S. Census Bureau ACS 2008-2012 via the City of Chicago\n"
            "Software: QGIS")
    text_item(layout, info, x0, 222, pw, 42, 6.8)
    return layout


lay1 = make_layout(
    "Map 1 - Station walksheds",
    "Share of Each Community Area Within a Half Mile of a CTA 'L' Station",
    "Chicago, Illinois. Half-mile (2,640 ft) straight-line buffers around all 'L' stations.",
    [L_sta, L_rail, L_walk, L_access],
    [L_access, L_walk, L_rail, L_sta],
    f"Results\n{stats['pct_city_area_in_walkshed']}% of the city's land area is within a half mile of "
    f"an 'L' station. {stats['areas_with_no_station_within_half_mile']} of 77 community areas have no "
    f"part within a half mile of a station, and {stats['areas_50pct_or_more']} are at least half covered.\n\n"
    "Coverage follows the radial lines out of the Loop. The largest gaps are the Far Southwest Side "
    "(Ashburn, Beverly, Mount Greenwood), the Far Southeast Side (South Deering, Hegewisch) and the "
    "Northwest Side (Dunning, Montclare, Belmont Cragin).",
)

lay2 = make_layout(
    "Map 2 - Hardship and access",
    "Economic Hardship and 'L' Station Access, Chicago Community Areas",
    "Hardship index (ACS 2008-2012) with half-mile station walksheds outlined.",
    [L_sta, L_rail, L_walk, L_hard],
    [L_hard, L_walk, L_rail, L_sta],
    f"Results\nAt the community-area level, 'L' access and hardship are not related "
    f"(r = {stats['pearson_r_pct_vs_hardship']}, n = 77). Areas under 10% covered average a hardship "
    f"index of {stats['mean_hardship_under_10pct']}; areas at least half covered average "
    f"{stats['mean_hardship_50pct_or_more']}. Several high-hardship areas on the West and South Sides "
    "are well served by the Green, Pink and Red lines, while the Far Southeast Side has no 'L' service.\n\n"
    "Hardship index combines crowding, poverty, unemployment, education, dependency and income "
    "(1 = least, 100 = most).",
)

os.makedirs(MAPS, exist_ok=True)
for layout, stem in [(lay1, "map1_station_walksheds"), (lay2, "map2_hardship_access")]:
    exporter = QgsLayoutExporter(layout)
    img = QgsLayoutExporter.ImageExportSettings()
    img.dpi = 150
    r1 = exporter.exportToImage(os.path.join(MAPS, stem + ".png"), img)
    r2 = exporter.exportToPdf(os.path.join(MAPS, stem + ".pdf"), QgsLayoutExporter.PdfExportSettings())
    print(stem, "png:", r1, "pdf:", r2)
    if r1 != QgsLayoutExporter.ExportResult.Success or r2 != QgsLayoutExporter.ExportResult.Success:
        raise SystemExit(f"export failed for {stem}")

project.write(QGZ)
# legend nodes in layouts keep absolute paths; store them relative to the project
with zipfile.ZipFile(QGZ) as z:
    members = {n: z.read(n) for n in z.namelist()}
for n in members:
    if n.endswith(".qgs"):
        txt = members[n].decode("utf-8").replace(GPKG, "./data/chicago_analysis.gpkg")
        arrow = north_arrow_svg()
        if arrow:
            txt = txt.replace(arrow, "arrows/" + os.path.basename(arrow))
        members[n] = txt.encode("utf-8")
with zipfile.ZipFile(QGZ, "w", zipfile.ZIP_DEFLATED) as z:
    for n, data in members.items():
        z.writestr(n, data)
print("saved", QGZ)
qgs.exitQgis()
