import { useEffect, useImperativeHandle, useRef, type Ref } from "react";
import L from "leaflet";
import "@geoman-io/leaflet-geoman-free";
import { MapContainer, TileLayer, useMap } from "react-leaflet";
import { MAX_REGIONS, SLOT_COLORS, SLOT_LETTERS, type MapRegion } from "../regions";

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
    </MapContainer>
  );
}
