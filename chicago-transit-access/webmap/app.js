// Chicago 'L' station access web map. Data layers are exported from the QGIS
// project by scripts/02_qgis_analysis_webdata.py.

const THEMES = {
  coverage: {
    field: "pct_walkshed",
    title: "Area within 1/2 mile of a station",
    classes: [
      { max: 0, color: "#f7f7f7", label: "None" },
      { max: 10, color: "#c6dbef", label: "Under 10%" },
      { max: 25, color: "#9ecae1", label: "10 - 25%" },
      { max: 50, color: "#6baed6", label: "25 - 50%" },
      { max: 75, color: "#3182bd", label: "50 - 75%" },
      { max: 100.01, color: "#08519c", label: "75 - 100%" },
    ],
  },
  hardship: {
    field: "hardship_index",
    title: "Hardship index (1 = least, 100 = most)",
    classes: [
      { max: 20, color: "#ffffd4", label: "1 - 20" },
      { max: 40, color: "#fed98e", label: "21 - 40" },
      { max: 60, color: "#fe9929", label: "41 - 60" },
      { max: 80, color: "#d95f0e", label: "61 - 80" },
      { max: 101, color: "#993404", label: "81 - 100" },
    ],
  },
};

const LINE_COLORS = {
  RD: "#c60c30", BL: "#00a1de", BR: "#62361b", GR: "#009b3a", OR: "#f9461c",
  PK: "#e27ea6", PR: "#522398", YL: "#f9e300", ML: "#3c3c3c",
};
const STATION_LINES = [
  ["red", "Red", "#c60c30"], ["blue", "Blue", "#00a1de"], ["brn", "Brown", "#62361b"],
  ["g", "Green", "#009b3a"], ["o", "Orange", "#f9461c"], ["pnk", "Pink", "#e27ea6"],
  ["p", "Purple", "#522398"], ["pexp", "Purple Express", "#522398"], ["y", "Yellow", "#f9e300"],
];

let theme = "coverage";
let areaLayer, selected = null;
const byNum = new Map();

const map = L.map("map", { zoomSnap: 0.25, minZoom: 9, maxZoom: 17 }).setView([41.84, -87.68], 10.5);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 18,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
}).addTo(map);
L.control.scale({ imperial: true, metric: false }).addTo(map);

map.createPane("walk").style.zIndex = 420;
map.createPane("lines").style.zIndex = 430;
map.createPane("stations").style.zIndex = 440;

const fmt = {
  pct: (v) => `${(+v).toFixed(1)}%`,
  money: (v) => `$${Math.round(+v).toLocaleString("en-US")}`,
};

function colorFor(value, t = theme) {
  const cls = THEMES[t].classes;
  for (const c of cls) if (+value <= c.max) return c.color;
  return cls[cls.length - 1].color;
}

function areaStyle(f) {
  return {
    fillColor: colorFor(f.properties[THEMES[theme].field]),
    fillOpacity: 0.82,
    color: "#ffffff",
    weight: 1,
  };
}

function renderLegend() {
  const t = THEMES[theme];
  const el = document.getElementById("legend");
  el.innerHTML = `<div class="note">${t.title}</div>` +
    t.classes.map((c) => `<div class="row"><span class="sw" style="background:${c.color}"></span>${c.label}</div>`).join("");
}

function detailHtml(p) {
  return `<h3>${p.community}</h3>
    <table>
      <tr><td>Area within 1/2 mile of a station</td><td>${fmt.pct(p.pct_walkshed)}</td></tr>
      <tr><td>'L' stations inside the area</td><td>${p.stations}</td></tr>
      <tr><td>Hardship index</td><td>${p.hardship_index}</td></tr>
      <tr><td>Per capita income</td><td>${fmt.money(p.per_capita_income_)}</td></tr>
      <tr><td>Households below poverty</td><td>${fmt.pct(p.percent_households_below_poverty)}</td></tr>
    </table>`;
}

function select(num) {
  if (selected) areaLayer.resetStyle(selected);
  document.querySelectorAll(".scatter .dot.on").forEach((d) => d.classList.remove("on"));
  selected = byNum.get(num) || null;
  if (!selected) return;
  selected.setStyle({ color: "#1d2327", weight: 3 });
  selected.bringToFront();
  document.getElementById("detail").innerHTML = detailHtml(selected.feature.properties);
  const dot = document.querySelector(`.scatter .dot[data-num="${num}"]`);
  if (dot) dot.classList.add("on");
}

function renderScatter(features) {
  const W = 320, H = 210, m = { l: 34, r: 18, t: 8, b: 30 };
  const x = (v) => m.l + (v / 100) * (W - m.l - m.r);
  const y = (v) => H - m.b - (v / 100) * (H - m.t - m.b);
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Scatter plot of station coverage against hardship index for 77 community areas">`;
  for (const v of [0, 25, 50, 75, 100]) {
    s += `<line class="grid" x1="${x(v)}" x2="${x(v)}" y1="${m.t}" y2="${H - m.b}"/>`;
    s += `<line class="grid" x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}"/>`;
    s += `<text x="${x(v)}" y="${H - m.b + 13}" text-anchor="middle">${v}%</text>`;
    s += `<text x="${m.l - 5}" y="${y(v) + 3}" text-anchor="end">${v}</text>`;
  }
  s += `<line class="axis" x1="${m.l}" x2="${W - m.r}" y1="${H - m.b}" y2="${H - m.b}"/>`;
  s += `<line class="axis" x1="${m.l}" x2="${m.l}" y1="${m.t}" y2="${H - m.b}"/>`;
  s += `<text x="${(W + m.l) / 2}" y="${H - 3}" text-anchor="middle">Area within 1/2 mile of a station</text>`;
  s += `<text transform="translate(10 ${(H - m.b) / 2}) rotate(-90)" text-anchor="middle">Hardship index</text>`;
  for (const f of features) {
    const p = f.properties;
    s += `<circle class="dot" data-num="${p.area_num}" cx="${x(+p.pct_walkshed).toFixed(1)}" cy="${y(+p.hardship_index).toFixed(1)}" r="4.2" fill="${colorFor(p.hardship_index, "hardship")}"><title>${p.community}: ${fmt.pct(p.pct_walkshed)}, hardship ${p.hardship_index}</title></circle>`;
  }
  s += "</svg>";
  const el = document.getElementById("scatter");
  el.innerHTML = s;
  el.addEventListener("click", (e) => {
    const d = e.target.closest(".dot");
    if (!d) return;
    const layer = byNum.get(+d.dataset.num);
    select(+d.dataset.num);
    if (layer) map.fitBounds(layer.getBounds(), { maxZoom: 13, padding: [40, 40] });
  });
  el.addEventListener("mouseover", (e) => {
    const d = e.target.closest(".dot");
    if (!d) return;
    const layer = byNum.get(+d.dataset.num);
    if (layer && layer !== selected) layer.setStyle({ color: "#1d2327", weight: 2 });
  });
  el.addEventListener("mouseout", (e) => {
    const d = e.target.closest(".dot");
    if (!d) return;
    const layer = byNum.get(+d.dataset.num);
    if (layer && layer !== selected) areaLayer.resetStyle(layer);
  });
}

function stationPopup(p) {
  const chips = STATION_LINES.filter(([k]) => p[k]).map(([, name, c]) =>
    `<span class="chip" style="background:${c};${name === "Yellow" ? "color:#222" : ""}">${name}</span>`).join("");
  return `<strong>${p.station_name}</strong><br>${chips}<br>${p.ada ? "Accessible (ADA)" : "Not ADA accessible"}`;
}

async function getJSON(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

async function init() {
  const [areas, walk, lines, stations, summary] = await Promise.all([
    getJSON("data/community_areas.geojson"),
    getJSON("data/walkshed.geojson"),
    getJSON("data/l_lines.geojson"),
    getJSON("data/l_stations.geojson"),
    getJSON("data/summary.json"),
  ]);

  document.getElementById("stat-cover").textContent = `${summary.pct_city_area_in_walkshed}%`;
  document.getElementById("stat-none").textContent = `${summary.areas_with_no_station_within_half_mile} / 77`;
  document.getElementById("stat-r").textContent = `r = ${summary.pearson_r_pct_vs_hardship.toFixed(2)}`;

  areaLayer = L.geoJSON(areas, {
    style: areaStyle,
    onEachFeature: (f, layer) => {
      byNum.set(+f.properties.area_num, layer);
      layer.bindTooltip(f.properties.community, { sticky: true, className: "area-tip" });
      layer.on("click", () => select(+f.properties.area_num));
      layer.on("mouseover", () => { if (layer !== selected) layer.setStyle({ color: "#1d2327", weight: 2 }); });
      layer.on("mouseout", () => { if (layer !== selected) areaLayer.resetStyle(layer); });
    },
  }).addTo(map);

  const walkLayer = L.geoJSON(walk, {
    pane: "walk", interactive: false,
    style: { fill: false, color: "#1d2327", weight: 1.1, dashArray: "4 3", opacity: 0.8 },
  }).addTo(map);

  const lineLayer = L.geoJSON(lines, {
    pane: "lines", interactive: false,
    style: (f) => ({ color: LINE_COLORS[f.properties.legend] || "#444", weight: 3, opacity: 0.95 }),
  }).addTo(map);

  const stationLayer = L.geoJSON(stations, {
    pane: "stations",
    pointToLayer: (f, ll) => L.circleMarker(ll, {
      pane: "stations", radius: 3.6, color: "#1d2327", weight: 1.2, fillColor: "#ffffff", fillOpacity: 1,
    }),
    onEachFeature: (f, layer) => layer.bindPopup(stationPopup(f.properties)),
  }).addTo(map);

  const fitCity = () => {
    map.invalidateSize();
    map.fitBounds(areaLayer.getBounds(), { padding: [12, 12] });
  };
  // Leaflet caches the container size from before the stylesheet applied, so
  // refresh it and fit now, and once more after the page has fully loaded.
  fitCity();
  if (document.readyState === "complete") setTimeout(fitCity, 50);
  else window.addEventListener("load", () => setTimeout(fitCity, 50), { once: true });
  new ResizeObserver(() => map.invalidateSize()).observe(document.getElementById("map"));

  const toggle = (id, layer) => document.getElementById(id).addEventListener("change", (e) => {
    if (e.target.checked) layer.addTo(map); else map.removeLayer(layer);
  });
  toggle("lyr-walk", walkLayer);
  toggle("lyr-lines", lineLayer);
  toggle("lyr-stations", stationLayer);

  document.querySelectorAll('input[name="theme"]').forEach((r) => r.addEventListener("change", (e) => {
    theme = e.target.value;
    areaLayer.setStyle(areaStyle);
    if (selected) selected.setStyle({ color: "#1d2327", weight: 3 });
    renderLegend();
  }));

  renderLegend();
  renderScatter(areas.features);
}

init().catch((err) => {
  document.getElementById("detail").innerHTML =
    `<p class="note">The map data did not load (${err.message}). If you opened this file directly, serve the folder over HTTP instead.</p>`;
});
