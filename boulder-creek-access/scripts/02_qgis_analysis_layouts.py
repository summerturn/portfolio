# Step 2: run the analysis with QGIS Processing, style the layers, build the print
# layouts and export the maps. Run with the Python that ships with QGIS, e.g.
#   /Applications/QGIS.app/Contents/MacOS/bin/python3 scripts/02_qgis_analysis_layouts.py
# Outputs: data/boulder_analysis.gpkg, boulder_analysis.qgz, maps/*.pdf and maps/*.png

import json
import os
import statistics
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qgis.core import (
    Qgis,
    QgsApplication,
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
    QgsPalLayerSettings,
    QgsPrintLayout,
    QgsProject,
    QgsRectangle,
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
RAW = os.path.join(DATA, "osm_raw.gpkg")
GPKG = os.path.join(DATA, "boulder_analysis.gpkg")
QGZ = os.path.join(PROJECT_DIR, "boulder_analysis.qgz")

CRS = "EPSG:26913"  # NAD83 / UTM zone 13N
BUFFER_M = 100
HEX_M = 250
AUTHOR = "Summerlyn Turner"
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


def raw(name):
    return run("native:reprojectlayer", {"INPUT": f"{RAW}|layername={name}",
                                         "TARGET_CRS": QgsCoordinateReferenceSystem(CRS)})


# ---------------- analysis ----------------
study = raw("study_area")
streams = raw("streams")
parks = raw("parks")
buildings_all = raw("buildings")
study_wkt = next(study.getFeatures()).geometry().asWkt()
streams_full = streams  # keep full lines so the buffer is right at the edges
streams = run("native:clip", {"INPUT": streams_full, "OVERLAY": study})
parks_clip = None  # parks outside the box still count as "nearest", only clip for display

# keep buildings whose centroid falls inside the study area
buildings = run("native:extractbyexpression", {
    "INPUT": buildings_all,
    "EXPRESSION": f"within(centroid(@geometry), geom_from_wkt('{study_wkt}'))"})

# map 1: 100 m stream buffer and the buildings that touch it
buffer = run("native:buffer", {"INPUT": streams_full, "DISTANCE": BUFFER_M, "SEGMENTS": 8,
                               "END_CAP_STYLE": 0, "JOIN_STYLE": 0, "DISSOLVE": True})
buffer = run("native:clip", {"INPUT": buffer, "OVERLAY": study})
near_stream = run("native:extractbylocation", {"INPUT": buildings, "PREDICATE": [0], "INTERSECT": buffer})

# map 2: distance from each building centroid to the nearest park, summarized on a hex grid
centroids = run("native:centroids", {"INPUT": buildings, "ALL_PARTS": False})
nearest = run("native:joinbynearest", {"INPUT": centroids, "INPUT_2": parks, "FIELDS_TO_COPY": ["name"],
                                       "DISCARD_NONMATCHING": False, "PREFIX": "park_", "NEIGHBORS": 1})
# ties (a building equally close to two parks) come back twice, keep one row per building
nearest = run("native:removeduplicatesbyattribute", {"INPUT": nearest, "FIELDS": ["fid"]})
nearest = run("native:deletecolumn", {"INPUT": nearest, "COLUMN": ["fid"]})
grid = run("native:creategrid", {"TYPE": 4, "EXTENT": study.extent(), "HSPACING": HEX_M,
                                 "VSPACING": HEX_M, "HOVERLAY": 0, "VOVERLAY": 0,
                                 "CRS": QgsCoordinateReferenceSystem(CRS)})
hex_summary = run("native:joinbylocationsummary", {"INPUT": grid, "PREDICATE": [1], "JOIN": nearest,
                                                   "JOIN_FIELDS": ["distance"], "SUMMARIES": [0, 6],
                                                   "DISCARD_NONMATCHING": True})
hex_summary = run("native:extractbyexpression", {"INPUT": hex_summary, "EXPRESSION": '"distance_count" >= 3'})
hex_summary = run("native:clip", {"INPUT": hex_summary, "OVERLAY": study})
parks_clip = run("native:clip", {"INPUT": parks, "OVERLAY": study})

dists = [f["distance"] for f in nearest.getFeatures() if f["distance"] is not None]
stats = {
    "buildings": buildings.featureCount(),
    "buildings_within_100m": near_stream.featureCount(),
    "parks": parks.featureCount(),
    "stream_segments": streams.featureCount(),
    "median_distance_to_park_m": round(statistics.median(dists)),
    "pct_within_400m_of_park": round(100 * sum(d <= 400 for d in dists) / len(dists), 1),
}
stats["pct_within_100m"] = round(100 * stats["buildings_within_100m"] / stats["buildings"], 1)
print(json.dumps(stats, indent=2))

# save every analysis layer into one GeoPackage
for lyr, name in [(study, "study_area"), (streams, "streams"), (parks_clip, "parks"), (buildings, "buildings"),
                  (buffer, "stream_buffer_100m"), (near_stream, "buildings_within_100m"),
                  (nearest, "building_nearest_park"), (hex_summary, "park_distance_hex")]:
    lyr.setName(name)
if os.path.exists(GPKG):
    os.remove(GPKG)
processing.run("native:package", {"LAYERS": [study, streams, parks_clip, buildings, buffer, near_stream,
                                             nearest, hex_summary],
                                  "OUTPUT": GPKG, "OVERWRITE": True, "SAVE_STYLES": False})
with open(os.path.join(DATA, "summary_stats.json"), "w") as f:
    json.dump(stats, f, indent=2)

# ---------------- project and styling ----------------
project = QgsProject.instance()
project.setCrs(QgsCoordinateReferenceSystem(CRS))
project.setTitle("Central Boulder stream exposure and park access")


def load(table, title):
    lyr = QgsVectorLayer(f"{GPKG}|layername={table}", title, "ogr")
    if not lyr.isValid():
        raise SystemExit(f"layer failed to load: {table}")
    project.addMapLayer(lyr)
    return lyr


L_study = load("study_area", "Study area")
L_buf = load("stream_buffer_100m", "100 m stream buffer")
L_bldg = load("buildings", "Buildings")
L_near = load("buildings_within_100m", "Buildings within 100 m of a stream")
L_streams = load("streams", "Streams and creeks")
L_parks = load("parks", "Parks")
L_hex = load("park_distance_hex", "Mean distance to nearest park")

L_study.renderer().setSymbol(QgsFillSymbol.createSimple(
    {"style": "no", "outline_color": "0,0,0", "outline_width": "0.5"}))
L_buf.renderer().setSymbol(QgsFillSymbol.createSimple(
    {"color": "166,206,227,140", "outline_color": "31,120,180", "outline_style": "dash", "outline_width": "0.25"}))
L_bldg.renderer().setSymbol(QgsFillSymbol.createSimple({"color": "178,178,178", "outline_style": "no"}))
L_near.renderer().setSymbol(QgsFillSymbol.createSimple({"color": "227,26,28", "outline_style": "no"}))
L_streams.renderer().setSymbol(QgsLineSymbol.createSimple({"line_color": "31,120,180", "line_width": "0.6"}))
L_parks.renderer().setSymbol(QgsFillSymbol.createSimple(
    {"color": "51,160,44,0", "outline_color": "0,100,0", "outline_width": "0.4", "style": "no"}))

# stream labels
fmt = QgsTextFormat()
f = QFont("Arial")
f.setItalic(True)
fmt.setFont(f)
fmt.setSize(7.5)
fmt.setColor(QColor(31, 120, 180))
buf_settings = QgsTextBufferSettings()
buf_settings.setEnabled(True)
buf_settings.setSize(0.8)
buf_settings.setColor(QColor(255, 255, 255))
fmt.setBuffer(buf_settings)
pal = QgsPalLayerSettings()
pal.fieldName = "name"
pal.placement = Qgis.LabelPlacement.Curved
pal.setFormat(fmt)
pal.thinningSettings().setMinimumFeatureSize(15)
pal.lineSettings().setMergeLines(True)
L_streams.setLabeling(QgsVectorLayerSimpleLabeling(pal))
L_streams.setLabelsEnabled(True)

# graduated hexes (manual breaks)
ranges = []
for lo, hi, color, label in [(0, 200, "26,152,80", "0 - 200 m"), (200, 400, "166,217,106", "200 - 400 m"),
                             (400, 800, "253,174,97", "400 - 800 m"), (800, 5000, "215,48,39", "Over 800 m")]:
    sym = QgsFillSymbol.createSimple({"color": color, "outline_color": "255,255,255", "outline_width": "0.2"})
    ranges.append(QgsRendererRange(lo, hi, sym, label))
L_hex.setRenderer(QgsGraduatedSymbolRenderer("distance_mean", ranges))
L_hex.setOpacity(0.85)


# ---------------- layouts ----------------
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


def make_layout(name, title, subtitle, map_layers, legend_layers, results, date):
    layout = QgsPrintLayout(project)
    layout.initializeDefaults()
    layout.setName(name)
    layout.pageCollection().page(0).setPageSize("Letter", QgsLayoutItemPage.Orientation.Landscape)
    project.layoutManager().addLayout(layout)

    border = QgsLayoutItemShape(layout)
    border.setShapeType(QgsLayoutItemShape.Shape.Rectangle)
    border.setSymbol(QgsFillSymbol.createSimple({"style": "no", "outline_color": "0,0,0", "outline_width": "0.6"}))
    layout.addLayoutItem(border)
    border.attemptMove(QgsLayoutPoint(6, 6, MM))
    border.attemptResize(QgsLayoutSize(267.4, 203.9, MM))

    text_item(layout, title, 11, 9, 255, 10, 17, bold=True)
    text_item(layout, subtitle, 11, 19, 255, 7, 10.5)

    m = QgsLayoutItemMap(layout)
    m.setFrameEnabled(True)
    layout.addLayoutItem(m)
    ext = QgsRectangle(L_study.extent())
    ext.grow(25)
    map_w = 190
    map_h = min(174, map_w * ext.height() / ext.width())
    m.attemptMove(QgsLayoutPoint(11, 28 + (174 - map_h) / 2, MM))
    m.attemptResize(QgsLayoutSize(map_w, map_h, MM))
    m.setLayers(map_layers)
    m.setKeepLayerSet(True)
    m.zoomToExtent(ext)

    x0 = 206
    arrow = north_arrow_svg()
    if arrow:
        pic = QgsLayoutItemPicture(layout)
        pic.setPicturePath(arrow)
        layout.addLayoutItem(pic)
        pic.attemptMove(QgsLayoutPoint(x0 + 24, 28, MM))
        pic.attemptResize(QgsLayoutSize(14, 18, MM))

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
    legend.setSymbolWidth(6)
    legend.setSymbolHeight(3.5)
    legend.setWrapString("|")
    legend.setBackgroundEnabled(False)
    for st, size, bold in [(QgsLegendStyle.Style.Title, 11, True), (QgsLegendStyle.Style.Group, 9, False),
                           (QgsLegendStyle.Style.Subgroup, 8.5, False), (QgsLegendStyle.Style.SymbolLabel, 8.5, False)]:
        style = legend.style(st)
        tf = style.textFormat()
        lf = QFont("Arial")
        lf.setBold(bold)
        tf.setFont(lf)
        tf.setSize(size)
        style.setTextFormat(tf)
        legend.setStyle(st, style)
    layout.addLayoutItem(legend)
    legend.attemptMove(QgsLayoutPoint(x0, 50, MM))
    legend.adjustBoxSize()

    text_item(layout, results, x0, 118, 62, 30, 8.5)

    sb = QgsLayoutItemScaleBar(layout)
    sb.setStyle("Single Box")
    sb.setLinkedMap(m)
    sb.setUnits(Qgis.DistanceUnit.Kilometers)
    sb.setUnitLabel("km")
    sb.setUnitsPerSegment(0.5)
    sb.setNumberOfSegments(2)
    sb.setNumberOfSegmentsLeft(0)
    sb.setHeight(2.5)
    sbf = QgsTextFormat()
    sbf.setFont(QFont("Arial"))
    sbf.setSize(8)
    sb.setTextFormat(sbf)
    layout.addLayoutItem(sb)
    sb.attemptMove(QgsLayoutPoint(x0, 152, MM))

    info = (f"Prepared by: {AUTHOR}\nDate: {date}\n"
            "Projection: NAD83 / UTM Zone 13N (EPSG:26913)\n"
            "Data: OpenStreetMap contributors (ODbL), via the Overpass API\n"
            "Software: QGIS")
    text_item(layout, info, x0, 168, 62, 34, 7.5)
    return layout


lay1 = make_layout(
    "Map 1 - Stream exposure",
    "Buildings Within 100 m of Streams, Central Boulder, Colorado",
    "Proximity analysis of OpenStreetMap building footprints and mapped waterways",
    [L_study, L_streams, L_near, L_bldg, L_buf],
    [L_streams, L_buf, L_near, L_bldg, L_study],
    f"Results\n{stats['buildings_within_100m']:,} of {stats['buildings']:,} buildings "
    f"({stats['pct_within_100m']}%) are within 100 m of a mapped stream.\n\n"
    "Screening level only. This is not a FEMA floodplain map.",
    "September 2025",
)

lay2 = make_layout(
    "Map 2 - Park access",
    "Distance to the Nearest Park, Central Boulder, Colorado",
    f"Mean straight-line distance from building centroids to the nearest park, summarized by {HEX_M} m hexagon",
    [L_study, L_parks, L_hex, L_bldg],
    [L_hex, L_parks, L_study],
    f"Results\n{stats['pct_within_400m_of_park']}% of buildings are within 400 m (about a 5 minute walk) "
    f"of a park.\nMedian distance: {stats['median_distance_to_park_m']} m\n\n"
    "Distances are straight-line, not along the street network.",
    "May 2026",
)

os.makedirs(MAPS, exist_ok=True)
for layout, stem in [(lay1, "map1_stream_exposure"), (lay2, "map2_park_access")]:
    exporter = QgsLayoutExporter(layout)
    img = QgsLayoutExporter.ImageExportSettings()
    img.dpi = 150
    r1 = exporter.exportToImage(os.path.join(MAPS, stem + ".png"), img)
    r2 = exporter.exportToPdf(os.path.join(MAPS, stem + ".pdf"), QgsLayoutExporter.PdfExportSettings())
    print(stem, "png:", r1, "pdf:", r2)
    if r1 != QgsLayoutExporter.ExportResult.Success or r2 != QgsLayoutExporter.ExportResult.Success:
        raise SystemExit(f"export failed for {stem}")

project.write(QGZ)

# legend nodes inside the layouts keep absolute paths; make them relative so the
# project opens on any machine
import zipfile  # noqa: E402

with zipfile.ZipFile(QGZ) as z:
    members = {n: z.read(n) for n in z.namelist()}
for n in members:
    if n.endswith(".qgs"):
        txt = members[n].decode("utf-8").replace(GPKG, "./data/boulder_analysis.gpkg")
        arrow = north_arrow_svg()
        if arrow:
            txt = txt.replace(arrow, "arrows/" + os.path.basename(arrow))
        members[n] = txt.encode("utf-8")
with zipfile.ZipFile(QGZ, "w", zipfile.ZIP_DEFLATED) as z:
    for n, data in members.items():
        z.writestr(n, data)
print("saved", QGZ)
qgs.exitQgis()
