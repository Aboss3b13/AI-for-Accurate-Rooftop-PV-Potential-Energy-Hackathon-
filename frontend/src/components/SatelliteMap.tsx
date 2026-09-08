import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import {
  Search,
  MapPin,
  LoaderCircle,
  Crosshair,
  ArrowUpRight,
  PenLine,
  Trash2,
  Check,
  Undo2,
} from "lucide-react";
import Help from "./Help";
import type { MapCapture, MapPick } from "../mapTypes";

type Location = {
  label: string;
  latitude: number;
  longitude: number;
  is_address: boolean;
};
type Props = {
  onPick: (pick: MapPick) => Promise<void>;
  busy: boolean;
  error: string;
  capture: MapCapture | null;
  visible: boolean;
};
const INITIAL: L.LatLngTuple = [47.473, 8.307];
export default function SatelliteMap({
  onPick,
  busy,
  error,
  capture,
  visible,
}: Props) {
  const container = useRef<HTMLDivElement>(null),
    map = useRef<L.Map | null>(null),
    selection = useRef<L.GeoJSON | null>(null);
  const callback = useRef(onPick),
    isBusy = useRef(busy);
  callback.current = onPick;
  isBusy.current = busy;
  const [query, setQuery] = useState(""),
    [results, setResults] = useState<Location[]>([]),
    [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState(""),
    [mapError, setMapError] = useState(""),
    [zoom, setZoom] = useState(18);
  const [drawing, setDrawing] = useState(false);
  const [outline, setOutline] = useState<L.LatLng[]>([]);
  const searchRequest = useRef<AbortController | null>(null);
  const drawLayer = useRef<L.LayerGroup | null>(null);
  const isDrawing = useRef(drawing);
  isDrawing.current = drawing;
  useEffect(() => {
    if (!container.current) return;
    const m = L.map(container.current, {
      center: INITIAL,
      zoom: 18,
      minZoom: 8,
      maxZoom: 21,
      maxBounds: [
        [45.7, 5.85],
        [47.95, 10.65],
      ],
      maxBoundsViscosity: 0.8,
      scrollWheelZoom: true,
    });
    map.current = m;
    const tiles = L.tileLayer(
      "https://wmts.geo.admin.ch/1.0.0/ch.swisstopo.swissimage/default/current/3857/{z}/{x}/{y}.jpeg",
      {
        maxNativeZoom: 20,
        maxZoom: 21,
        attribution:
          'Aerial imagery © <a href="https://www.swisstopo.admin.ch/" target="_blank" rel="noopener">swisstopo</a>',
        bounds: [
          [45.7, 5.85],
          [47.95, 10.65],
        ],
        keepBuffer: 2,
      },
    ).addTo(m);
    tiles.on("tileerror", () =>
      setMapError(
        "Some aerial tiles could not load. Check your connection or try a different zoom.",
      ),
    );
    tiles.on("load", () => {
      if (container.current?.querySelector(".leaflet-tile-loaded"))
        setMapError("");
    });
    L.control.scale({ imperial: false, position: "bottomleft" }).addTo(m);
    m.on("zoomend", () => setZoom(m.getZoom()));
    m.on("click", (e: L.LeafletMouseEvent) => {
      if (isBusy.current) return;
      if (isDrawing.current) {
        setOutline((points) => [...points, e.latlng]);
        return;
      }
      if (m.getZoom() < 18) {
        m.setView(e.latlng, 19);
        return;
      }
      void callback.current({
        latitude: e.latlng.lat,
        longitude: e.latlng.lng,
      });
    });
    const observer = new ResizeObserver(() => m.invalidateSize());
    observer.observe(container.current);
    return () => {
      observer.disconnect();
      m.remove();
      map.current = null;
      searchRequest.current?.abort();
    };
  }, []);
  useEffect(() => {
    if (visible) map.current?.invalidateSize();
  }, [visible]);
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    drawLayer.current?.remove();
    if (!outline.length) return;
    const group = L.layerGroup();
    const closed = outline.length > 2;
    (closed ? L.polygon(outline) : L.polyline(outline)).setStyle({
      color: "#d5ff8f",
      weight: 3,
      fillOpacity: closed ? 0.22 : 0,
      dashArray: closed ? undefined : "6 5",
    }).addTo(group);
    outline.forEach((point, i) =>
      L.circleMarker(point, {
        radius: 5,
        color: "#0f2417",
        weight: 2,
        fillColor: i === 0 ? "#d5ff8f" : "#ffffff",
        fillOpacity: 1,
      }).addTo(group),
    );
    drawLayer.current = group.addTo(m);
  }, [outline]);
  useEffect(() => {
    const container = map.current?.getContainer();
    if (container) container.style.cursor = drawing ? "crosshair" : "";
  }, [drawing]);
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    selection.current?.remove();
    if (drawing) return;
    if (!capture?.candidates.length && !capture?.building_outline) return;
    const outline = capture.building_outline;
    // The merged building sits underneath; facets stay clickable on top of it.
    const features = [
      ...(outline ? [{ plane: outline, whole: true }] : []),
      ...capture.candidates.map((p) => ({ plane: p, whole: false })),
    ].map(({ plane, whole }) => ({
      type: "Feature",
      properties: { id: plane.id, whole },
      geometry: plane.geometry,
    }));
    const wholeSelected = outline?.id === capture.selected_roof_id;
    selection.current = L.geoJSON(features as any, {
      style: (feature) => {
        const isWhole = feature?.properties.whole;
        const isSelected = feature?.properties.id === capture.selected_roof_id;
        if (isWhole)
          return {
            color: isSelected ? "#d5ff8f" : "#9fe870",
            weight: isSelected ? 3 : 2,
            fillOpacity: isSelected ? 0.2 : 0.05,
          };
        return {
          color: isSelected ? "#d5ff8f" : "#75cfff",
          weight: isSelected ? 3 : 1,
          fillOpacity: isSelected ? 0.24 : wholeSelected ? 0 : 0.16,
          dashArray: wholeSelected && !isSelected ? "3 4" : undefined,
        };
      },
      onEachFeature: (feature, layer) =>
        layer.on("click", (event: L.LeafletMouseEvent) => {
          L.DomEvent.stopPropagation(event);
          if (isBusy.current) return;
          // Clicking the active facet again widens back out to the whole roof.
          const back =
            feature.properties.id === capture.selected_roof_id && outline;
          void callback.current({
            latitude: capture.provenance.latitude,
            longitude: capture.provenance.longitude,
            roof_id: back ? outline.id : feature.properties.id,
          });
        }),
    }).addTo(m);
  }, [capture, drawing]);
  async function search(event: React.FormEvent) {
    event.preventDefault();
    if (query.trim().length < 2) return;
    searchRequest.current?.abort();
    const controller = new AbortController();
    searchRequest.current = controller;
    setSearching(true);
    setSearchError("");
    try {
      const response = await fetch(
        "/api/map/search?q=" + encodeURIComponent(query.trim()),
        { signal: controller.signal },
      );
      const data = await response.json();
      if (!response.ok)
        throw Error(data.detail || "Address search unavailable.");
      setResults(data.results);
      if (!data.results.length)
        setSearchError("No matching Swiss address or place found.");
    } catch (e) {
      if (!controller.signal.aborted)
        setSearchError(e instanceof Error ? e.message : "Search failed.");
    } finally {
      if (!controller.signal.aborted) setSearching(false);
    }
  }
  function goTo(location: Location) {
    map.current?.setView(
      [location.latitude, location.longitude],
      location.is_address ? 20 : 17,
    );
    setQuery(location.label);
    setResults([]);
    setSearchError("");
  }
  function useOutline() {
    if (outline.length < 3) return;
    const centre = L.polygon(outline).getBounds().getCenter();
    void onPick({
      latitude: centre.lat,
      longitude: centre.lng,
      polygon: outline.map((p) => ({ latitude: p.lat, longitude: p.lng })),
    });
    setDrawing(false);
  }
  function clearOutline() {
    setOutline([]);
  }
  function pickCentre() {
    const m = map.current;
    if (!m) return;
    const point = m.getCenter();
    void onPick({ latitude: point.lat, longitude: point.lng });
  }
  return (
    <section className="satellite-card" hidden={!visible}>
      <div className="map-heading">
        <div>
          <MapPin size={18} />
          <strong>Find your roof</strong>
          <span>Switzerland · live aerial map</span>
          <Help title="Finding your roof">
            Search an address or drag the map to your building, zoom in, then
            click the roof. SolarFit downloads that patch of aerial photo at a
            known scale, so every measurement is in real metres.
          </Help>
        </div>
        <span className="map-auto-pill">
          {drawing ? "Drawing your own outline" : "Automatic scale + roof outline"}
        </span>
      </div>
      <form className="map-search" onSubmit={search}>
        <Search size={17} />
        <input
          aria-label="Swiss address or place"
          placeholder="Search a Swiss address or place…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button disabled={searching || query.trim().length < 2}>
          {searching ? <LoaderCircle className="spin" size={17} /> : "Search"}
        </button>
      </form>
      {!!results.length && (
        <div className="map-search-results">
          {results.map((r, i) => (
            <button key={i} onClick={() => goTo(r)}>
              <MapPin size={15} />
              {r.label}
              <ArrowUpRight size={15} />
            </button>
          ))}
        </div>
      )}
      {searchError && (
        <p className="map-message" role="alert">
          {searchError}
        </p>
      )}
      <div className="map-stage">
        <div
          ref={container}
          className="satellite-map"
          aria-label="Satellite map of Switzerland. Zoom to a building and click its roof."
        />
        <div className="map-crosshair" aria-hidden="true">
          +
        </div>
        <div className="map-instruction">
          {drawing
            ? outline.length < 3
              ? `Click each corner of the roof (${outline.length}/3 minimum)`
              : `${outline.length} corners. Click more, or press “Use this outline”.`
            : zoom < 18
            ? "Zoom in to see individual roofs"
            : capture?.provenance.merged_planes && capture.provenance.merged_planes > 1
              ? `Whole roof: ${capture.provenance.merged_planes} planes, ${capture.provenance.roof_area_m2} m². Click a facet to narrow.`
              : "Click a roof. SolarFit handles the rest."}
        </div>
        {busy && (
          <div className="map-working" role="status">
            <LoaderCircle className="spin" />
            <strong>Finding your roof & calibrating imagery</strong>
            <span>
              Official roof outline → metric aerial capture → PV analysis
            </span>
          </div>
        )}
      </div>
      {(error || mapError) && (
        <p className="map-message" role="alert">
          {error || mapError}
        </p>
      )}
      <div className="map-mode-switch" role="group" aria-label="How to select the roof">
        <button
          className={drawing ? "" : "selected"}
          onClick={() => setDrawing(false)}
          disabled={busy}
        >
          <Crosshair size={15} />
          Click a roof
        </button>
        <button
          className={drawing ? "selected" : ""}
          onClick={() => setDrawing(true)}
          disabled={busy}
        >
          <PenLine size={15} />
          Draw it myself
        </button>
        <Help title="The two ways to pick a roof">
          <b>Click a roof</b> uses Switzerland’s official roof map: one click
          takes the whole building, and its outline and size are filled in for
          you. <b>Draw it myself</b> lets you click the corners yourself — use
          it for a building the official map does not cover, or when you only
          want part of a roof.
        </Help>
      </div>
      {drawing ? (
        <div className="map-actions">
          <button
            className="primary"
            onClick={useOutline}
            disabled={busy || outline.length < 3}
          >
            <Check size={16} />
            Use this outline
          </button>
          <button
            className="text-button"
            onClick={() => setOutline((p) => p.slice(0, -1))}
            disabled={busy || !outline.length}
          >
            <Undo2 size={15} />
            Undo point
          </button>
          <button
            className="text-button"
            onClick={clearOutline}
            disabled={busy || !outline.length}
          >
            <Trash2 size={15} />
            Clear drawing
          </button>
          <span>Click each corner of the roof on the photo</span>
        </div>
      ) : (
        <div className="map-actions">
          <button
            className="primary"
            onClick={pickCentre}
            disabled={busy || zoom < 18}
          >
            <Crosshair size={16} />
            Analyse roof at centre
          </button>
          <span>Or press “Draw it myself” to trace the roof by hand</span>
        </div>
      )}
      <p className="map-disclosure">
        Roof planes: Sonnendach / Swiss Federal Office of Energy. Imagery:
        swisstopo. Map browsing needs internet; AI runs on your computer.
      </p>
    </section>
  );
}
