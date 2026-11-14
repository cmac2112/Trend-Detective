import { useEffect, useRef } from "react";
import L from "leaflet";
import "@geoman-io/leaflet-geoman-free";
import { MapContainer, TileLayer, useMap } from "react-leaflet";

interface Props {
  /** Called with the drawn polygon (GeoJSON Feature) or null when it's removed. */
  onChange: (region: GeoJSON.Feature | null) => void;
  /** Set to load a region onto the map (e.g. a demo region). Change `id` to reload. */
  loadRegion: { id: number; feature: GeoJSON.Feature } | null;
}

const SHAPE_STYLE: L.PathOptions = { color: "#2a78d6", weight: 2, fillOpacity: 0.15 };

/** Adds the Geoman drawing toolbar and keeps exactly one region on the map. */
function DrawControl({ onChange, loadRegion }: Props) {
  const map = useMap();
  const current = useRef<L.Layer | null>(null);
  const adoptRef = useRef<(layer: L.Layer) => void>(() => {});
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

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
    map.pm.setPathOptions(SHAPE_STYLE);

    const emit = (layer: L.Layer) => {
      const gj = (layer as L.Polygon).toGeoJSON() as GeoJSON.Feature;
      onChangeRef.current(gj);
    };

    const adopt = (layer: L.Layer) => {
      // Only one region at a time: drawing a new one replaces the old one.
      if (current.current && current.current !== layer) map.removeLayer(current.current);
      current.current = layer;
      layer.on("pm:edit pm:dragend", () => emit(layer));
      emit(layer);
    };

    const onCreate = (e: { layer: L.Layer }) => adopt(e.layer);
    const onRemove = (e: { layer: L.Layer }) => {
      if (e.layer === current.current) {
        current.current = null;
        onChangeRef.current(null);
      }
    };
    map.on("pm:create", onCreate);
    map.on("pm:remove", onRemove);
    adoptRef.current = adopt;

    return () => {
      map.off("pm:create", onCreate);
      map.off("pm:remove", onRemove);
      map.pm.removeControls();
    };
  }, [map]);

  // Load an external region (demo examples) as an editable polygon.
  useEffect(() => {
    if (!loadRegion) return;
    const group = L.geoJSON(loadRegion.feature, { style: () => SHAPE_STYLE });
    const layer = group.getLayers()[0];
    if (!layer) return;
    layer.addTo(map);
    adoptRef.current(layer);
    map.fitBounds((layer as L.Polygon).getBounds(), { padding: [40, 40] });
  }, [loadRegion, map]);

  return null;
}

export default function MapPanel(props: Props) {
  return (
    // One copy of the world only, so drawn longitudes stay within -180..180 like the data.
    <MapContainer
      center={[30, -20]}
      zoom={2}
      minZoom={2}
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
