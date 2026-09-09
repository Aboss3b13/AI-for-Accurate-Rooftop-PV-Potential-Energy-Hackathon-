import AnalysisPanel from "./components/AnalysisPanel";
import SatelliteMap from "./components/SatelliteMap";
import RoofFaces from "./components/RoofFaces";
import MapContext from "./components/MapContext";
import Help from "./components/Help";
import { prepareMapCapture, type MapCapture, type MapPick } from "./mapTypes";
import "./map.css";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Sun,
  Upload,
  ArrowUpRight,
  ScanLine,
  MousePointer2,
  Pentagon,
  Ruler,
  Undo2,
  Check,
  SlidersHorizontal,
  Layers3,
  LoaderCircle,
  Plus,
  Image as ImageIcon,
  Map as MapIcon,
} from "lucide-react";
import RoofCanvas, {
  layerNames,
  type Layers,
  type Tool,
} from "./components/RoofCanvas";
import type { Analysis, Kind, MarkedObject, Mode, Panel, Point } from "./types";
import { registerAnalysisReader } from "./webmcp";

const labels: Record<Tool, string> = {
  view: "Move vertices",
  roof: "Draw roof",
  existing_pv: "Mark existing PV",
  chimney: "Mark chimney",
  skylight: "Mark skylight",
  other_obstacle: "Mark obstacle",
  scale: "Measure distance",
};
type Example = {
  name: string;
  image: string;
  roof: Point[];
  objects: MarkedObject[];
  pixels_per_metre: number;
  note: string;
};

export default function App() {
  const [sourceView, setSourceView] = useState<"map" | "editor">("map");
  const [inspectedFace, setInspectedFace] = useState("");
  const [editedFace, setEditedFace] = useState("");
  const [buildingOverride, setBuildingOverride] = useState<Point[] | null>(null);
  const [faceOverrides, setFaceOverrides] = useState<Record<string, Point[]>>({});
  const [objective, setObjective] = useState<"capacity" | "energy">("capacity");
  const [panelLimit, setPanelLimit] = useState("");
  const [mapCapture, setMapCapture] = useState<MapCapture | null>(null);
  const [mapBusy, setMapBusy] = useState(false),
    [mapError, setMapError] = useState("");
  const [mapEdited, setMapEdited] = useState(false),
    [pendingMapAnalysis, setPendingMapAnalysis] = useState(false);
  const mapRequest = useRef<AbortController | null>(null);
  const loadVersion = useRef(0);
  useEffect(()=>()=>mapRequest.current?.abort(),[]);
  const [file, setFile] = useState<File | null>(null),
    [url, setUrl] = useState(""),
    [size, setSize] = useState<[number, number]>([1000, 700]);
  const [roof, setRoof] = useState<Point[]>([]),
    [objects, setObjects] = useState<MarkedObject[]>([]),
    [draft, setDraft] = useState<Point[]>([]);
  const [tool, setTool] = useState<Tool>("roof"),
    [result, setResult] = useState<Analysis | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [mode, setMode] = useState<Mode>("recommended"),
    [panel, setPanel] = useState<Panel>({
      width: 1.134,
      height: 1.762,
      power: 450,
      gap: 0.02,
    });
  const [ppm, setPpm] = useState(""),
    [roofWidth, setRoofWidth] = useState("12"),
    [measurement, setMeasurement] = useState<Point[]>([]),
    [distance, setDistance] = useState(""),
    [verified, setVerified] = useState(false);
  const [angle, setAngle] = useState(0),
    [yieldValue, setYield] = useState(""),
    [ai, setAi] = useState(true),
    [model, setModel] = useState("Checking model…");
  const [edge, setEdge] = useState(0.3),
    [obstacleMargin, setObstacleMargin] = useState(0.4),
    [pvMargin, setPvMargin] = useState(0.2);
  const [layers, setLayers] = useState<Layers>({
      roof: true,
      existing: true,
      obstacles: true,
      safety: false,
      usable: true,
      panels: true,
    }),
    [original, setOriginal] = useState(false);
  const [examples, setExamples] = useState<Example[]>([]),
    [note, setNote] = useState(""),
    [auto, setAuto] = useState(false),
    [comparisons, setComparisons] = useState<Partial<Record<Mode, number>>>({});
  const upload = useRef<HTMLInputElement>(null),
    request = useRef(0),
    abort = useRef<AbortController | null>(null);
  const completed = useRef<Analysis | null>(null);
  useEffect(() => {
    setComparisons({});
  }, [
    panel,
    ppm,
    roofWidth,
    verified,
    angle,
    yieldValue,
    objective, panelLimit,
    ai,
    edge,
    obstacleMargin,
    pvMargin,
  ]);
  useEffect(() => {
    completed.current = result;
  }, [result]);
  useEffect(() => registerAnalysisReader(() => completed.current), []);
  useEffect(() => {
    fetch("/api/health")
      .then((r) => r.json())
      .then((d) =>
        setModel(
          d.model.available
            ? "YOLO11-seg ready"
            : "Manual mode · model missing",
        ),
      )
      .catch(() => setModel("Backend offline"));
    fetch("/examples/manifest.json")
      .then((r) => r.json())
      .then(setExamples)
      .catch(() => {});
  }, []);
  useEffect(
    () => () => {
      if (url) URL.revokeObjectURL(url);
    },
    [url],
  );
  const invalidate = () => {
    request.current++;
    abort.current?.abort();
    setResult(null);
    setAuto(false);
    setBusy(false);
    setComparisons({});
  };
  async function loadFile(f: File, example?: Example, fromMap=false) {
    if (!["image/png", "image/jpeg", "image/webp"].includes(f.type)) {
      setError("Please upload PNG, JPG or WebP.");
      return false;
    }
    if (f.size > 20 * 1024 * 1024) {
      setError("Please use an image smaller than 20 MB.");
      return false;
    }
    const version=++loadVersion.current;
    if(!fromMap){mapRequest.current?.abort();setMapBusy(false);setMapError('');}
    invalidate();
    setError("");
    const u = URL.createObjectURL(f);
    try {
      const image = new window.Image();
      image.src = u;
      await image.decode();
      if(version!==loadVersion.current){URL.revokeObjectURL(u);return false;}
      if (image.width * image.height > 25_000_000)
        throw Error("Crop the image to less than 25 megapixels.");
      setFile(f);
      setSourceView(fromMap ? "map" : "editor");
      setInspectedFace(""); setEditedFace(""); setFaceOverrides({}); setBuildingOverride(null);
      setObjective("capacity"); setPanelLimit("");
      setMapCapture(null);
      setMapEdited(false);
      setPendingMapAnalysis(false);
      setUrl(u);
      setSize([image.naturalWidth, image.naturalHeight]);
      setRoof(example?.roof || []);
      setObjects(example?.objects || []);
      setDraft([]);
      setTool(example ? "view" : "roof");
      setPpm(example ? String(example.pixels_per_metre) : "");
      setVerified(!!example);
      setMeasurement([]);
      setDistance("");
      setNote(example?.note || "");
      setAi(true);
      return true;
    } catch (e) {
      URL.revokeObjectURL(u);
      setError(String(e));
      return false;
    }
  }
  async function pickMapRoof(pick: MapPick) {
    mapRequest.current?.abort();
    const controller = new AbortController();
    mapRequest.current = controller;
    invalidate();
    setMapBusy(true);
    setMapError("");
    try {
      const capture = await prepareMapCapture(pick, controller.signal);
      if (controller.signal.aborted) return;
      const bytes = Uint8Array.from(atob(capture.image_base64), (c) =>
        c.charCodeAt(0),
      );
      const loaded = await loadFile(
        new File(
          [bytes],
          `Swiss roof ${capture.selected_roof_id || "capture"}.jpg`,
          { type: "image/jpeg" },
        ),
        {
          name: "Swiss map capture",
          image: "",
          roof: capture.roof,
          objects: capture.objects,
          pixels_per_metre: capture.pixels_per_metre,
          note: "Aerial imagery © swisstopo · Roof boundaries: Sonnendach / Swiss Federal Office of Energy.",
        },
        true,
      );
      if (!loaded || controller.signal.aborted) return;
      setMapCapture(capture);
      setMapEdited(false);
      setAngle(capture.angle);
      setYield("");
      setTool(capture.roof.length > 2 ? "view" : "roof");
      if (capture.roof.length < 3) setSourceView("editor");
      setPendingMapAnalysis(capture.roof.length > 2);
    } catch (e) {
      if (!controller.signal.aborted)
        setMapError(e instanceof Error ? e.message : "Map capture failed.");
    } finally {
      if (!controller.signal.aborted) setMapBusy(false);
    }
  }
  async function loadExample(e: Example) {
    try {
      const r = await fetch(e.image);
      if (!r.ok) throw Error("Example unavailable");
      await loadFile(
        new File([await r.blob()], e.name + ".jpg", { type: "image/jpeg" }),
        e,
      );
    } catch (e) {
      setError(String(e));
    }
  }
  function selectTool(t: Tool) {
    setTool(t);
    setDraft([]);
    setOriginal(false);
  }
  function changeRoof(p: Point[]) {
    setRoof(p);
    setMapEdited(true);
    if (editedFace) setFaceOverrides(previous => ({ ...previous, [editedFace]: p }));
    else if (mapCapture) setBuildingOverride(p);
  }
  function editInspectedFace() {
    const face = mapCapture?.roof_faces.find(f => f.id === inspectedFace);
    setEditedFace(face?.id || "");
    setRoof(face ? faceOverrides[face.id] || face.roof : buildingOverride || mapCapture?.roof || roof);
    setSourceView("editor"); setTool("view"); setDraft([]);
  }
  function finish(p: Point[]) {
    if (tool === "scale") {
      setMeasurement(p);
      setDistance("");
      setVerified(false);
      setPpm("");
      invalidate();
    } else if (p.length >= 3) {
      invalidate();
      if (tool === "roof") {
        changeRoof(p);
      } else setObjects([...objects, { polygon: p, kind: tool as Kind }]);
    }
    setDraft([]);
    setTool("view");
  }
  const analyse = useCallback(async () => {
    if (!file || roof.length < 3) {
      setError("Upload an image and draw the roof boundary first.");
      return;
    }
    if (draft.length) {
      setError("Finish or cancel your drawing before analysing.");
      return;
    }
    const id = ++request.current;
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    setBusy(true);
    setError("");
    const form = new FormData();
    form.append("image", file);
    form.append(
      "settings",
      JSON.stringify({
        roof,
        capture_id: mapCapture?.roof_faces.length ? mapCapture.capture_id : null,
        boundary_edited: mapEdited,
        edited_face_id: editedFace || null,
        face_overrides: faceOverrides,
        building_override: buildingOverride,
        objective: mapCapture ? objective : "capacity",
        max_panels: mapCapture && panelLimit ? Number(panelLimit) : null,
        objects,
        mode,
        panel,
        pixels_per_metre: ppm ? Number(ppm) : null,
        approximate_roof_width: Number(roofWidth),
        scale_verified: verified,
        angle,
        annual_specific_yield: yieldValue ? Number(yieldValue) : null,
        use_ai: ai,
        edge_margin: edge,
        obstacle_margin: obstacleMargin,
        pv_margin: pvMargin,
      }),
    );
    try {
      const r = await fetch("/api/analyse", {
        method: "POST",
        body: form,
        signal: controller.signal,
      });
      const data = await r.json();
      if (!r.ok)
        throw Error(
          typeof data.detail === "string"
            ? data.detail
            : "Please check your scale and panel settings.",
        );
      if (id === request.current) {
        setResult(data);
        setAuto(true);
        setComparisons((c) => ({
          ...c,
          [mode]: data.statistics.additional_panel_count,
        }));
        setModel(
          data.model.available
            ? `YOLO11-seg · ${data.model.device === "cpu" ? "CPU" : "CUDA GPU"}`
            : "Manual geometry mode",
        );
      }
    } catch (e) {
      if (
        id === request.current &&
        !(e instanceof DOMException && e.name === "AbortError")
      )
        setError(e instanceof Error ? e.message : "Analysis failed");
    } finally {
      if (id === request.current) setBusy(false);
    }
  }, [
    file,
    roof,
    objects,
    mode,
    panel,
    ppm,
    roofWidth,
    verified,
    angle,
    yieldValue,
    objective, panelLimit,
    ai,
    edge,
    obstacleMargin,
    pvMargin,
    draft.length, buildingOverride, mapCapture, mapEdited, editedFace, faceOverrides, objective, panelLimit,
  ]);
  useEffect(() => {
    if (pendingMapAnalysis && file && roof.length > 2) {
      setPendingMapAnalysis(false);
      void analyse();
    }
  }, [pendingMapAnalysis, file, roof, analyse]);
  useEffect(() => {
    if (!auto) return;
    request.current++;
    abort.current?.abort();
    setBusy(true);
    const timer = setTimeout(() => void analyse(), 450);
    return () => clearTimeout(timer);
  }, [
    mode,
    panel,
    ppm,
    roofWidth,
    verified,
    angle,
    yieldValue,
    objective, panelLimit,
    ai,
    edge,
    obstacleMargin,
    pvMargin,
  ]);
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === "INPUT") return;
      if (e.key === "Escape") {
        setDraft([]);
        setTool("view");
      }
      if (e.key === "Enter" && draft.length >= 3) finish(draft);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [draft, tool, objects]);
  const stats = result?.statistics;
  function exportJson() {
    if (!result) return;
    const blob = new Blob(
      [
        JSON.stringify(
          {
            ...result,
            input: { roof, objects, panel, mode, angle, objective, max_panels: panelLimit || null,
              face_overrides: faceOverrides, building_override: buildingOverride,
              pixels_per_metre: ppm, annual_specific_yield: yieldValue || null,
              edge_margin: edge, obstacle_margin: obstacleMargin, pv_margin: pvMargin },
            map_provenance: mapCapture?.provenance ?? null,
            boundary_adjusted: mapEdited,
          },
          null,
          2,
        ),
      ],
      { type: "application/json" },
    );
    const u = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = u;
    a.download = "solarfit-analysis.json";
    a.click();
    URL.revokeObjectURL(u);
  }
  function configPanel(key: keyof Panel, value: number) {
    setComparisons({});
    setPanel((p) => ({ ...p, [key]: value }));
  }
  return (
    <div className="app">
      <header>
        <a className="brand" href="/">
          <span className="brand-icon">
            <Sun size={24} />
          </span>
          SolarFit<span className="brand-tag">ROOFTOP INTELLIGENCE</span>
        </a>
        <div className="header-right">
          <span className="local-status">
            <i /> Runs on your computer
          </span>
          <button
            className="upload-button"
            onClick={() => upload.current?.click()}
          >
            <Upload size={16} />
            Upload roof
          </button>
        </div>
      </header>
      <input
        ref={upload}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        hidden
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) void loadFile(f);
          e.target.value = "";
        }}
      />
      <main>
        <section className="intro">
          <div>
            <h1>
              Every roof has more potential<span>.</span>
            </h1>
            <p>
              Click a building on the Swiss map. SolarFit measures the roof,
              finds what is in the way, and fits the panels.
            </p>
          </div>
        </section>
        <div className="workspace">
          <section className="left-column">
            <div className="source-switch">
              <button
                className={sourceView === "map" ? "selected" : ""}
                onClick={() => setSourceView("map")}
              >
                <MapIcon size={16} />
                Satellite map
              </button>
              <button
                className={sourceView === "editor" ? "selected" : ""}
                onClick={() => setSourceView("editor")}
              >
                <Pentagon size={16} />
                {file ? "Roof editor" : "Upload & draw"}
              </button>
              <span>
                {sourceView === "map"
                  ? "Find a building. Click its roof."
                  : "Review and adjust your analysis."}
              </span>
            </div>
            <SatelliteMap
              visible={sourceView === "map"}
              onPick={pickMapRoof}
              busy={mapBusy || busy}
              phase={mapBusy ? "Loading official faces, aerial imagery and roof height model" : "Analysing imagery and optimising each roof surface"}
              error={mapError || error}
              capture={mapCapture}
              result={result}
              layers={layers}
              setLayers={setLayers}
              inspectedFace={inspectedFace}
              onInspect={setInspectedFace}
            />
            {result?.faces && <RoofFaces result={result} selected={inspectedFace} onSelect={setInspectedFace}
              onEdit={editInspectedFace} objective={objective} setObjective={setObjective}
              limit={panelLimit} setLimit={setPanelLimit} busy={busy || mapBusy} />}
            {sourceView === "editor" && mapCapture && (
              <MapContext
                capture={mapCapture}
                onPick={pickMapRoof}
                busy={mapBusy}
                edited={mapEdited}
                onReset={() => {
                  invalidate();
                  setRoof(mapCapture.roof);
                  setEditedFace(""); setFaceOverrides({}); setBuildingOverride(null);
                  setAngle(mapCapture.angle);
                  setMapEdited(false);
                  setTool("view");
                  setPendingMapAnalysis(true);
                }}
              />
            )}
            {sourceView === "editor" && mapError && (
              <p className="map-message" role="alert">
                {mapError}
              </p>
            )}
            <div
              className="canvas-card"
              hidden={sourceView === "map"}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                if (e.dataTransfer.files[0])
                  void loadFile(e.dataTransfer.files[0]);
              }}
            >
              <div className="card-toolbar">
                <div>
                  <span className="small-dot" />{" "}
                  {file ? file.name : "Your rooftop workspace"}
                </div>
                <button
                  className={"text-button " + (original ? "selected" : "")}
                  onClick={() => setOriginal(!original)}
                  disabled={!file}
                >
                  <ImageIcon size={15} />
                  {original ? "Show analysis" : "View original"}
                </button>
              </div>
              {file ? (
                <>
                  <div className="image-stage">
                    <RoofCanvas
                      url={url}
                      size={size}
                      roof={roof}
                      objects={objects}
                      draft={draft}
                      setDraft={setDraft}
                      tool={tool}
                      result={result}
                      layers={layers}
                      original={original}
                      onFinish={finish}
                      onRoofChange={(p) => {
                        invalidate();
                        changeRoof(p);
                      }}
                      measurement={measurement}
                    />
                    <div className="image-badge">
                      <span className="small-dot" />
                      {stats
                        ? `${stats.additional_panel_count} additional modules`
                        : labels[tool]}
                    </div>
                    {busy && (
                      <div className="busy-overlay">
                        <LoaderCircle className="spin" />
                        <b>Analysing & fitting panels</b>
                        <span>Segmentation → exclusions → physical layout</span>
                      </div>
                    )}
                  </div>
                  <div className="drawing-tools">
                    {(
                      [
                        ["view", MousePointer2],
                        ["roof", Pentagon],
                        ["scale", Ruler],
                        ["other_obstacle", Plus],
                        ["existing_pv", ScanLine],
                      ] as const
                    ).map(([t, Icon]) => (
                      <button
                        key={t}
                        title={labels[t]}
                        className={tool === t ? "selected" : ""}
                        onClick={() => selectTool(t)}
                      >
                        <Icon size={16} />
                        <span>
                          {t === "view"
                            ? "Edit"
                            : t === "roof"
                              ? "Roof"
                              : t === "scale"
                                ? "Scale"
                                : t === "existing_pv"
                                  ? "Existing PV"
                                  : "Obstacle"}
                        </span>
                      </button>
                    ))}
                    <button
                      disabled={!draft.length}
                      onClick={() => setDraft(draft.slice(0, -1))}
                      title="Undo point"
                    >
                      <Undo2 size={16} />
                    </button>
                    <button
                      disabled={draft.length < 3 || tool === "scale"}
                      onClick={() => finish(draft)}
                    >
                      <Check size={16} />
                      Finish
                    </button>
                  </div>
                  <div className="canvas-hint">
                    {tool === "view"
                      ? "Drag white vertices to adjust the roof. Mark obstacles the model missed."
                      : tool === "scale"
                        ? "Click two endpoints of a known distance, then enter its length below."
                        : "Click around the boundary. Click the first point or Finish to close. Escape cancels."}
                  </div>
                </>
              ) : (
                <div className="empty-stage">
                  <div className="empty-icon">
                    <ScanLine size={42} />
                  </div>
                  <span className="eyebrow">
                    FROM AERIAL IMAGE TO INSTALLABLE CAPACITY
                  </span>
                  <h2>Start with a roof.</h2>
                  <p>
                    Drop your satellite screenshot here
                    <br />
                    or explore a Swiss aerial example below.
                  </p>
                  <button
                    className="primary"
                    onClick={() => upload.current?.click()}
                  >
                    <Upload size={17} />
                    Choose an image <ArrowUpRight size={17} />
                  </button>
                  <small>PNG, JPG or WebP · up to 20 MB</small>
                </div>
              )}
              <div className="layer-bar">
                <Layers3 size={16} />
                {Object.entries(layerNames).map(([key, label]) => (
                  <label key={key} className={"layer " + key}>
                    <input
                      type="checkbox"
                      checked={layers[key as keyof Layers]}
                      onChange={(e) =>
                        setLayers({ ...layers, [key]: e.target.checked })
                      }
                    />
                    <span />
                    {label}
                  </label>
                ))}
              </div>
            </div>
            {note && <p className="example-note">{note}</p>}
            <div className="examples">
              <div className="section-label">
                EXPLORE A ROOF <span>Bundled aerial examples</span>
              </div>
              <div className="example-grid">
                {examples.map((e, i) => (
                  <button
                    key={e.name}
                    className="example"
                    onClick={() => void loadExample(e)}
                  >
                    <img src={e.image} alt={e.name} />
                    <div>
                      <small>CASE 0{i + 1}</small>
                      <strong>{e.name}</strong>
                    </div>
                    <ArrowUpRight size={18} />
                  </button>
                ))}
                {examples.length === 0 && (
                  <p className="muted">Upload your own screenshot to begin.</p>
                )}
              </div>
            </div>
            <section className="settings-card">
              <div className="section-heading">
                <h3>
                  <SlidersHorizontal size={18} /> Installation settings
                </h3>
                <span>Physical constraints, real layouts</span>
              </div>
              <div className="settings-grid">
                <div>
                  <h4>
                    01 / Set the scale
                    <Help title="Scale">
                      SolarFit needs to know how many real metres one pixel of
                      the photo covers, or it cannot size panels. Roofs picked
                      from the satellite map are already calibrated. For your
                      own screenshot, use <b>Scale</b> to click both ends of
                      something you know the length of, and type that length.
                    </Help>
                  </h4>
                  {measurement.length === 2 && (
                    <label>
                      Measured line length (m)
                      <input
                        type="number"
                        min="0.1"
                        step="0.1"
                        value={distance}
                        onChange={(e) => {
                          setDistance(e.target.value);
                          const d = Number(e.target.value);
                          if (d > 0) {
                            setPpm(
                              String(
                                Math.hypot(
                                  measurement[1][0] - measurement[0][0],
                                  measurement[1][1] - measurement[0][1],
                                ) / d,
                              ),
                            );
                            setVerified(true);
                          }
                        }}
                      />
                    </label>
                  )}
                  <label>
                    Pixels per metre
                    <input
                      type="number"
                      min="0.5"
                      max="2000"
                      step="0.1"
                      placeholder="Draw a known distance above"
                      value={ppm}
                      onChange={(e) => {
                        setPpm(e.target.value);
                        setVerified(false);
                      }}
                    />
                  </label>
                  <label className="check-label">
                    <input
                      type="checkbox"
                      checked={verified}
                      disabled={!ppm}
                      onChange={(e) => setVerified(e.target.checked)}
                    />
                    Scale is based on a known measurement
                  </label>
                  {!ppm && (
                    <label>
                      Approximate roof width (m)
                      <input
                        type="number"
                        min="1"
                        max="200"
                        value={roofWidth}
                        onChange={(e) => setRoofWidth(e.target.value)}
                      />
                    </label>
                  )}
                  <p className="field-note">
                    Measure on the roof plane. Uncalibrated screenshots produce
                    approximate results.
                  </p>
                </div>
                <div>
                  <h4>
                    02 / Choose your module
                    <Help title="Your solar module">
                      The physical panel you would install. A common modern
                      module is about 1.76 × 1.13 m and 400–470 watts. If you
                      have a quote from an installer, copy its numbers here;
                      otherwise the defaults are realistic.
                    </Help>
                  </h4>
                  <div className="presets">
                    {[400, 430, 450, 470].map((w) => (
                      <button
                        className={panel.power === w ? "selected" : ""}
                        key={w}
                        onClick={() => configPanel("power", w)}
                      >
                        {w} W
                      </button>
                    ))}
                  </div>
                  <div className="paired">
                    <label>
                      Width (m)
                      <input
                        type="number"
                        min=".5"
                        max="3"
                        step=".001"
                        value={panel.width}
                        onChange={(e) =>
                          configPanel("width", Number(e.target.value))
                        }
                      />
                    </label>
                    <label>
                      Height (m)
                      <input
                        type="number"
                        min=".5"
                        max="4"
                        step=".001"
                        value={panel.height}
                        onChange={(e) =>
                          configPanel("height", Number(e.target.value))
                        }
                      />
                    </label>
                  </div>
                  <div className="paired">
                    <label>
                      Power (W)
                      <input
                        type="number"
                        min="50"
                        max="1000"
                        value={panel.power}
                        onChange={(e) =>
                          configPanel("power", Number(e.target.value))
                        }
                      />
                    </label>
                    <label>
                      Roof alignment (°)
                      <Help title="Roof alignment">
                        The direction the rows of panels run, so they line up
                        with the ridge instead of sitting crooked. Roofs taken
                        from the satellite map set this automatically.
                      </Help>
                      <input
                        type="number"
                        min="-180"
                        max="180"
                        value={angle}
                        onChange={(e) => setAngle(Number(e.target.value))}
                      />
                    </label>
                  </div>
                  <p className="field-note">
                    Wattage presets keep dimensions unchanged. Enter your
                    module’s actual dimensions.
                  </p>
                </div>
              </div>
              <details>
                <summary>Safety margins, energy &amp; detection</summary>
                <div className="advanced-grid">
                  <label>
                    Roof edge (m)
                    <Help title="Roof edge gap">
                      How far panels must stay back from the edge of the roof,
                      for wind loading and safe access. Under half a metre is
                      unusual on a pitched roof.
                    </Help>
                    <input
                      type="number"
                      min="0"
                      max="3"
                      step=".05"
                      value={edge}
                      onChange={(e) => setEdge(Number(e.target.value))}
                    />
                  </label>
                  <label>
                    Obstacle buffer (m)
                    <Help title="Obstacle gap">
                      Clear space left around chimneys, roof windows and vents —
                      both to fit the panel and to avoid their shadow.
                    </Help>
                    <input
                      type="number"
                      min="0"
                      max="3"
                      step=".05"
                      value={obstacleMargin}
                      onChange={(e) =>
                        setObstacleMargin(Number(e.target.value))
                      }
                    />
                  </label>
                  <label>
                    Existing PV buffer (m)
                    <Help title="Gap to existing panels">
                      Space kept between panels already on the roof and any new
                      ones.
                    </Help>
                    <input
                      type="number"
                      min="0"
                      max="3"
                      step=".05"
                      value={pvMargin}
                      onChange={(e) => setPvMargin(Number(e.target.value))}
                    />
                  </label>
                  <label>
                    Module gap (m)
                    <Help title="Gap between panels">
                      The small gap between neighbouring panels in the grid,
                      for mounting rails and heat expansion.
                    </Help>
                    <input
                      type="number"
                      min="0"
                      max=".5"
                      step=".01"
                      value={panel.gap}
                      onChange={(e) =>
                        configPanel("gap", Number(e.target.value))
                      }
                    />
                  </label>
                  <label>
                    Annual yield (kWh/kWp)
                    <Help title="Annual yield">
                      How many kilowatt-hours each kWp produces per year where
                      you live — around 900–1,100 on a good Swiss roof. Leave it
                      empty to use official per-face irradiation in map mode. Uploaded images need a supplied yield for energy estimates.
                    </Help>
                    <input
                      type="number"
                      min="0"
                      max="3000"
                      placeholder="Optional — from a reliable source"
                      value={yieldValue}
                      onChange={(e) => setYield(e.target.value)}
                    />
                  </label>
                  <label className="check-label">
                    <input
                      type="checkbox"
                      checked={ai}
                      onChange={(e) => setAi(e.target.checked)}
                    />
                    Use YOLO segmentation
                  </label>
                </div>
                <p className="field-note">
                  Margins × 1.5 conservative / × 1 recommended / × 0.5 maximum.
                  These are planning assumptions.
                </p>
              </details>
              {objects.length > 0 && (
                <div className="marked-list">
                  <h4>Manual & imported exclusions</h4>
                  {objects.map((o, i) => (
                    <div key={i}>
                      <span>
                        {o.kind.replaceAll("_", " ")} {i + 1}
                      </span>
                      <button
                        className="text-button"
                        onClick={() => {
                          invalidate();
                          setObjects(objects.filter((_, j) => j !== i));
                        }}
                      >
                        Remove
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </section>
          <AnalysisPanel
            result={result}
            busy={busy || mapBusy}
            ready={!!file && roof.length >= 3 && !mapBusy}
            mode={mode}
            setMode={setMode}
            error={error}
            analyse={analyse}
            exportJson={exportJson}
            model={model}
            comparisons={comparisons}
          />
        </div>
        <footer>
          <span className="footer-brand">
            <Sun size={17} />
            SolarFit
          </span>
          <span>Computer vision + roof geometry + physical panel packing</span>
          <span>Built for Energy Data Hackdays · 2026</span>
        </footer>
      </main>
    </div>
  );
}
