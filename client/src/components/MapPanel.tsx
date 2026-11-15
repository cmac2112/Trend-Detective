import { useEffect, useImperativeHandle, useRef, type Ref } from "react";
import L from "leaflet";
import "@geoman-io/leaflet-geoman-free";
import { MapContainer, TileLayer, useMap } from "react-leaflet";
import { MAX_REGIONS, SLOT_COLORS, SLOT_LETTERS, type MapRegion } from "../regions";
import type { TrendMap } from "../api";
import { trendColor } from "../trendColor";

/** Imperative controls the sidebar uses (add an example, remove, rename, clear). */
export interface MapHandle {
  addFeature: (feature: GeoJSON.Feature, name?: string) => void;
  remove: (id: number) => void;
  rename: (id: number, name: string) => void;
  clear: () => void;
}

interface Props {
  /** Called whenever regions are added, edited, renamed or removed (sorted by slot). */
  onChange: (regions: MapRegion[]) => void;
  /** Called when the user tries to add more than MAX_REGIONS. */
  onLimit: () => void;
  /** Per-cell trend maps to draw under the regions (one per analyzed region). */
  trendMaps?: TrendMap[];
  /** Slope where the colour scale saturates (shared by all maps so they compare). */
  trendLimit?: number;
  ref?: Ref<MapHandle>;
}

interface Entry {
  layer: L.Polygon;
  slot: number;
  name: string;
}

const styleFor = (slot: number): L.PathOptions => ({ color: SLOT_COLORS[slot], weight: 2, fillOpacity: 0.15 });

function DrawControl({ onChange, onLimit, ref }: Props) {
  const map = useMap();
  const entries = useRef(new Map<number, Entry>());
  const nextId = useRef(1);
  const cb = useRef({ onChange, onLimit });
  cb.current = { onChange, onLimit };

  const emit = () => {
    const list: MapRegion[] = [...entries.current.entries()]
      .map(([id, e]) => ({ id, slot: e.slot, name: e.name, feature: e.layer.toGeoJSON() as GeoJSON.Feature }))
      .sort((a, b) => a.slot - b.slot);
    cb.current.onChange(list);
  };

  const freeSlot = () => {
    const used = new Set([...entries.current.values()].map((e) => e.slot));
    for (let s = 0; s < MAX_REGIONS; s++) if (!used.has(s)) return s;
    return -1;
  };

  const label = (e: Entry) => `${SLOT_LETTERS[e.slot]} · ${e.name}`;

  /** Register a polygon layer as a region; returns false if all slots are taken. */
  const adopt = (layer: L.Polygon, name?: string) => {
    const slot = freeSlot();
    if (slot < 0) {
      map.removeLayer(layer);
      cb.current.onLimit();
      return false;
    }
    const id = nextId.current++;
    const entry: Entry = { layer, slot, name: name ?? `Region ${SLOT_LETTERS[slot]}` };
    entries.current.set(id, entry);
    layer.setStyle(styleFor(slot));
    layer.bindTooltip(label(entry), { permanent: true, direction: "center", className: "region-label" });
    layer.on("pm:edit pm:dragend", emit);
    (layer as L.Polygon & { _regionId?: number })._regionId = id;
    emit();
    return true;
  };

  useImperativeHandle(ref, () => ({
    addFeature(feature, name) {
      const layer = L.geoJSON(feature).getLayers()[0] as L.Polygon | undefined;
      if (!layer) return;
      layer.addTo(map);
      if (adopt(layer, name)) {
        const all = L.featureGroup([...entries.current.values()].map((e) => e.layer));
        map.fitBounds(all.getBounds(), { padding: [40, 40], maxZoom: 6 });
      }
    },
    remove(id) {
      const e = entries.current.get(id);
      if (!e) return;
      map.removeLayer(e.layer);
      entries.current.delete(id);
      emit();
    },
    rename(id, name) {
      const e = entries.current.get(id);
      if (!e) return;
      e.name = name;
      e.layer.setTooltipContent(label(e));
      emit();
    },
    clear() {
      entries.current.forEach((e) => map.removeLayer(e.layer));
      entries.current.clear();
      emit();
    },
  }));

  useEffect(() => {
    map.pm.addControls({
      position: "topleft",
      drawPolygon: true,
      drawRectangle: true,
      drawMarker: false,
      drawCircleMarker: false,
      drawPolyline: false,
      drawCircle: false,
      drawText: false,
      cutPolygon: false,
      rotateMode: false,
      dragMode: true,
      editMode: true,
      removalMode: true,
    });

    const onCreate = (e: { layer: L.Layer }) => adopt(e.layer as L.Polygon);
    const onRemove = (e: { layer: L.Layer }) => {
      const id = (e.layer as L.Polygon & { _regionId?: number })._regionId;
      if (id !== undefined && entries.current.delete(id)) emit();
    };
    map.on("pm:create", onCreate);
    map.on("pm:remove", onRemove);
    return () => {
      map.off("pm:create", onCreate);
      map.off("pm:remove", onRemove);
      map.pm.removeControls();
    };
    // adopt/emit only use refs, so registering once is correct
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map]);

  return null;
}

const fmt = (v: number) => `${v >= 0 ? "+" : ""}${v.toPrecision(3)}`;

/** Draws each grid cell as a rectangle coloured by its trend; faded when not significant.
 *  Lives in its own pane under the region outlines, ignored by the drawing tools. The
 *  outlines sit on top and take the mouse, so hover is resolved from the map's own
 *  mousemove: the grid is regular, so the cell under the cursor is a direct lookup. */
function TrendLayer({ maps, limit }: { maps: TrendMap[]; limit: number }) {
  const map = useMap();
  useEffect(() => {
    if (!map.getPane("trendmap")) map.createPane("trendmap").style.zIndex = "350";
    const renderer = L.canvas({ pane: "trendmap", padding: 0.5 });
    const group = L.layerGroup([], { pmIgnore: true } as L.LayerOptions);
    for (const m of maps) {
      const [hy, hx] = [m.resolution_deg[0] / 2, m.resolution_deg[1] / 2];
      m.lat.forEach((lat, i) =>
        m.lon.forEach((lon, j) => {
          const slope = m.slope_per_decade[i]?.[j];
          if (slope == null) return;
          group.addLayer(
            L.rectangle([[lat - hy, lon - hx], [lat + hy, lon + hx]], {
              renderer,
              pane: "trendmap",
              stroke: false,
              interactive: false,
              fillColor: trendColor(slope, limit),
              fillOpacity: m.significant[i][j] ? 0.85 : 0.35,
              pmIgnore: true,
            } as L.PolylineOptions),
          );
        }),
      );
    }
    group.addTo(map);

    const nearest = (axis: number[], v: number, half: number) => {
      if (axis.length === 0) return -1;
      const step = axis.length > 1 ? (axis[axis.length - 1] - axis[0]) / (axis.length - 1) : 1;
      const k = Math.round((v - axis[0]) / step);
      return k >= 0 && k < axis.length && Math.abs(axis[k] - v) <= half + 1e-9 ? k : -1;
    };
    const tip = L.tooltip({ sticky: true, className: "trend-tip", direction: "top", offset: [0, -8] });
    const onMove = (e: L.LeafletMouseEvent) => {
      for (const m of maps) {
        const i = nearest(m.lat, e.latlng.lat, m.resolution_deg[0] / 2);
        const j = nearest(m.lon, e.latlng.lng, m.resolution_deg[1] / 2);
        const slope = i >= 0 && j >= 0 ? m.slope_per_decade[i][j] : null;
        if (slope == null) continue;
        const p = m.p_value[i][j];
        const sig = m.significant[i][j];
        tip
          .setLatLng(e.latlng)
          .setContent(
            `<strong>${fmt(slope)} ${m.units} per decade</strong><br>` +
              `${sig ? "Significant" : "Not significant"}${p != null ? ` (p ${p < 0.001 ? "< 0.001" : `= ${p.toFixed(3)}`})` : ""}<br>` +
              `<span class="muted">cell at ${m.lat[i].toFixed(2)}°, ${m.lon[j].toFixed(2)}°</span>`,
          );
        if (!map.hasLayer(tip)) tip.addTo(map);
        return;
      }
      tip.remove();
    };
    const onOut = () => tip.remove();
    map.on("mousemove", onMove);
    map.on("mouseout", onOut);
    return () => {
      map.off("mousemove", onMove);
      map.off("mouseout", onOut);
      tip.remove();
      group.remove();
    };
  }, [map, maps, limit]);
  return null;
}

export default function MapPanel(props: Props) {
  return (
    // One copy of the world only, so drawn longitudes stay within -180..180 like the data.
    <MapContainer
      center={[30, -20]}
      zoom={2}
      minZoom={1}
      maxBounds={[[-90, -180], [90, 180]]}
      maxBoundsViscosity={1}
      className="map"
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        noWrap
      />
      <DrawControl {...props} />
      {props.trendMaps && props.trendMaps.length > 0 && (
        <TrendLayer maps={props.trendMaps} limit={props.trendLimit ?? 1} />
      )}
    </MapContainer>
  );
}
