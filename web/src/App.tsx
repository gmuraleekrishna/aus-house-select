import { ChangeEvent, FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  MapContainer,
  TileLayer,
  GeoJSON,
  LayersControl,
  CircleMarker,
  Popup,
  LayerGroup
} from "react-leaflet";
import type { Feature, FeatureCollection } from "geojson";
import L from "leaflet";
import type { GeoCollection, GeoFeature } from "./types";
import { useMapData } from "./hooks/useMapData";
import { buildTooltipFields, getMapCenter, makeSa1Style } from "./utils/geojson";
import { fetchArcgisGeojson } from "./utils/loaders";
import { loadKmzLayer } from "./utils/kmz";
import { ArcgisImageLayer } from "./components/ArcgisImageLayer";
import { formatValue, parsePercentile } from "./utils/schools";
import "leaflet/dist/leaflet.css";

const SCHOOL_DETAIL_FIELDS: Array<[string, string]> = [
  ["sector", "Sector"],
  ["stage", "Stage"],
  ["educationr", "Education region"],
  ["ranking_rank", "Rank"],
  ["ranking_score", "Score"],
  ["ranking_percentile", "Ranking percentile"],
  ["totalschoo", "Enrolments"],
  ["physicalst", "Address"],
  ["physicalto", "Town"],
  ["physicalpo", "Postcode"],
  ["lowyear", "Low year"],
  ["highyear", "High year"],
  ["matched_key", "Matched name"]
];

const SA1_DETAIL_FIELDS: Array<[string, string]> = [
  ["SA1_NAME21", "SA1 name"],
  ["SA2_NAME21", "SA2 name"],
  ["SA3_NAME21", "SA3 name"],
  ["STE_NAME21", "State"],
  ["IRSD_score", "IRSD score"],
  ["IRAD_score", "IRAD score"],
  ["IER_score", "IER score"],
  ["IEO_score", "IEO score"],
  ["URP", "Usual resident population"]
];

const CATCHMENT_COLORS: Record<string, string> = {
  primary: "#2e7d32",
  high: "#1565c0",
  other: "#6d597a"
};

const CATCHMENT_LABELS: Record<string, string> = {
  primary: "Primary school catchment",
  high: "High school catchment",
  other: "Other catchment"
};

const SCHOOL_SECTOR_COLORS: Record<string, string> = {
  government: "#2d9cdb",
  "non-government": "#9b5de5",
  other: "#fb8500"
};

interface AddressPin {
  lat: number;
  lon: number;
  address: string;
}

interface ArcgisLayerState {
  name: string;
  data: GeoCollection;
}

function buildLiaMapUrl(code: string | number | null | undefined) {
  if (!code) return null;
  const clean = String(code).trim();
  if (!clean) return null;
  return `https://www.det.wa.edu.au/schoolsonline/school_file_download?schoolID=${clean}&fileType=INTAKE_MAP01&yearID=_NA`;
}

function buildLiaPageUrl(code: string | number | null | undefined) {
  if (!code) return null;
  const clean = String(code).trim();
  if (!clean) return null;
  return `https://www.det.wa.edu.au/schoolsonline/localintakearea.do?schoolID=${clean}`;
}

function App() {
  const { data, loading, error } = useMapData();
  const [selectedState, setSelectedState] = useState<string | null>(null);
  const [addressQuery, setAddressQuery] = useState("");
  const [addressPin, setAddressPin] = useState<AddressPin | null>(null);
  const [geocodeStatus, setGeocodeStatus] = useState<string | null>(null);
  const [selectedSchool, setSelectedSchool] = useState<GeoFeature | null>(null);
  const [selectedSa1, setSelectedSa1] = useState<GeoFeature | null>(null);
  const [percentileMax, setPercentileMax] = useState<number | null>(null);
  const [temporaryArcgis, setTemporaryArcgis] = useState<ArcgisLayerState[]>([]);
  const [arcgisName, setArcgisName] = useState("");
  const [arcgisUrl, setArcgisUrl] = useState("");
  const [arcgisWhere, setArcgisWhere] = useState("1=1");
  const [arcgisError, setArcgisError] = useState<string | null>(null);
  const [addingArcgis, setAddingArcgis] = useState(false);
  const [selectedProcessedLayers, setSelectedProcessedLayers] = useState<string[]>([]);
  const [processedLayerData, setProcessedLayerData] = useState<Record<string, GeoCollection>>({});
  const [processedLayerError, setProcessedLayerError] = useState<string | null>(null);
  const [kmzLayers, setKmzLayers] = useState<ArcgisLayerState[]>([]);
  const [kmzError, setKmzError] = useState<string | null>(null);
  const [kmzLoading, setKmzLoading] = useState(false);
  const mapRef = useRef<L.Map | null>(null);
  const [imageLayers, setImageLayers] = useState<
    Array<{ name: string; url: string; opacity: number; format: string }>
  >([]);
  const [imageLayerName, setImageLayerName] = useState("");
  const [imageLayerUrl, setImageLayerUrl] = useState("");
  const [imageLayerOpacity, setImageLayerOpacity] = useState(70);
  const [imageLayerFormat, setImageLayerFormat] = useState("png32");
  const [imageLayerError, setImageLayerError] = useState<string | null>(null);

  useEffect(() => {
    if (data && !selectedState && data.metadata.states.length) {
      const defaultState = data.metadata.states.includes("Western Australia")
        ? "Western Australia"
        : data.metadata.states[0];
      setSelectedState(defaultState);
    }
  }, [data, selectedState]);

  const sa1Tooltip = useMemo(() => {
    if (!data) return null;
    return buildTooltipFields(data.metadata.propertyNames, data.metadata.seifaColumns);
  }, [data]);

  const filteredSa1 = useMemo(() => {
    if (!data) return null;
    const filtered = data.sa1.features?.filter((feature) => {
      if (!selectedState) return true;
      return (feature.properties || {}).STE_NAME21 === selectedState;
    });
    return filtered
      ? ({ type: "FeatureCollection", features: filtered } as GeoCollection)
      : data.sa1;
  }, [data, selectedState]);

  useEffect(() => {
    if (!selectedState || !selectedSa1) return;
    const state = selectedSa1.properties?.STE_NAME21;
    if (state && state !== selectedState) {
      setSelectedSa1(null);
    }
  }, [selectedState, selectedSa1]);

  const schoolPercentileDefault = useMemo(() => {
    if (!data?.schools?.features?.length) return null;
    const values: number[] = [];
    for (const feature of data.schools.features) {
      const pct = parsePercentile(feature.properties?.ranking_percentile);
      if (pct != null) {
        values.push(pct);
      }
    }
    if (!values.length) return null;
    return Math.min(100, Math.max(...values));
  }, [data]);

  useEffect(() => {
    if (percentileMax == null && schoolPercentileDefault != null) {
      setPercentileMax(schoolPercentileDefault);
    }
  }, [schoolPercentileDefault, percentileMax]);

  const filteredSchools = useMemo(() => {
    if (!data?.schools?.features) return [];
    if (percentileMax == null) return data.schools.features;
    const defaultMax = schoolPercentileDefault ?? 100;
    const active = percentileMax < defaultMax;
    if (!active) return data.schools.features;
    return data.schools.features.filter((feature) => {
      const pct = parsePercentile(feature.properties?.ranking_percentile);
      if (pct == null) return false;
      return pct <= percentileMax;
    });
  }, [data, percentileMax, schoolPercentileDefault]);

  const mapCenter = useMemo(() => {
    if (!data) return [-25.2744, 133.7751];
    return getMapCenter(data.metadata, selectedState);
  }, [data, selectedState]);

  const selectedSa1Collection = useMemo(() => {
    if (!selectedSa1) return null;
    return { type: "FeatureCollection", features: [selectedSa1] } as GeoCollection;
  }, [selectedSa1]);

  const handleGeocode = async (event?: FormEvent) => {
    event?.preventDefault();
    if (!addressQuery.trim()) {
      setGeocodeStatus("Enter an address to search.");
      return;
    }
    setGeocodeStatus("Searching...");
    try {
      const url = new URL("https://nominatim.openstreetmap.org/search");
      url.searchParams.set("format", "json");
      url.searchParams.set("limit", "1");
      url.searchParams.set("q", addressQuery.trim());
      const response = await fetch(url.toString(), {
        headers: {
          Accept: "application/json"
        }
      });
      if (!response.ok) {
        throw new Error(response.statusText);
      }
      const payload = await response.json();
      if (Array.isArray(payload) && payload.length) {
        const match = payload[0];
        setAddressPin({
          lat: parseFloat(match.lat),
          lon: parseFloat(match.lon),
          address: match.display_name
        });
        const lat = parseFloat(match.lat);
        const lon = parseFloat(match.lon);
        if (!Number.isNaN(lat) && !Number.isNaN(lon)) {
          mapRef.current?.flyTo([lat, lon], 16, { duration: 1.2 });
        }
        setGeocodeStatus("Address located on the map.");
      } else {
        setGeocodeStatus("Address not found.");
      }
    } catch (err) {
      setGeocodeStatus(`Geocoding failed: ${(err as Error).message}`);
    }
  };

  const handleArcgisAdd = async () => {
    if (!arcgisUrl.trim()) {
      setArcgisError("Provide an ArcGIS FeatureServer URL.");
      return;
    }
    setArcgisError(null);
    setAddingArcgis(true);
    try {
      const data = await fetchArcgisGeojson(arcgisUrl, arcgisWhere);
      const name = arcgisName.trim() || "ArcGIS layer";
      setTemporaryArcgis((prev) => [...prev, { name, data }]);
      setArcgisName("");
      setArcgisUrl("");
      setArcgisWhere("1=1");
    } catch (err) {
      setArcgisError((err as Error).message);
    } finally {
      setAddingArcgis(false);
    }
  };

  const handleAddImageLayer = () => {
    if (!imageLayerUrl.trim()) {
      setImageLayerError("Provide an ArcGIS ImageServer URL.");
      return;
    }
    setImageLayerError(null);
    const name = imageLayerName.trim() || "ImageServer layer";
    const opacity = Math.min(1, Math.max(0, imageLayerOpacity / 100));
    const format = imageLayerFormat.trim() || "png32";
    setImageLayers((prev) => [...prev, { name, url: imageLayerUrl.trim(), opacity, format }]);
    setImageLayerName("");
    setImageLayerUrl("");
    setImageLayerOpacity(70);
  };

  const handleKmzUpload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setKmzLoading(true);
    setKmzError(null);
    try {
      const geojson = await loadKmzLayer(file);
      const baseName = file.name.replace(/\\.(kmz|kml)$/i, "");
      setKmzLayers((prev) => [...prev, { name: baseName || file.name, data: geojson }]);
    } catch (err) {
      setKmzError((err as Error).message);
    } finally {
      setKmzLoading(false);
      event.target.value = "";
    }
  };

  const missingProcessed = useMemo(
    () => selectedProcessedLayers.filter((name) => !processedLayerData[name]),
    [selectedProcessedLayers, processedLayerData]
  );

  useEffect(() => {
    if (!missingProcessed.length || !data) return;
    let cancelled = false;
    async function loadSelected() {
      for (const name of missingProcessed) {
        const entry = data.arcgisManifest.layers.find((layer) => layer.name === name);
        if (!entry) continue;
        try {
          const response = await fetch(entry.file.startsWith("/") ? entry.file : `/${entry.file}`);
          if (!response.ok) {
            throw new Error(response.statusText);
          }
          const payload = (await response.json()) as GeoCollection;
          if (!cancelled) {
            setProcessedLayerData((prev) => ({ ...prev, [name]: payload }));
          }
        } catch (err) {
          if (!cancelled) {
            setProcessedLayerError(`Failed to load ${name}: ${(err as Error).message}`);
          }
        }
      }
    }
    loadSelected();
    return () => {
      cancelled = true;
    };
  }, [missingProcessed, data]);

  const sa1FeatureHandler = useCallback(
    (feature: Feature, layer: L.Layer) => {
      if (!sa1Tooltip) return;
      const { fields, aliases } = sa1Tooltip;
      const rows = fields
        .map((field, idx) => {
          const value = feature.properties?.[field];
          if (value == null) return null;
          return `<div><strong>${aliases[idx]}</strong> ${value}</div>`;
        })
        .filter(Boolean)
        .join("");
      if (rows) {
        layer.bindTooltip(rows, { sticky: true });
      }
      layer.on("click", () => {
        setSelectedSa1(feature as GeoFeature);
        setSelectedSchool(null);
      });
    },
    [sa1Tooltip]
  );

  const schoolMarkers = useMemo(() => {
    return filteredSchools.map((feature, index) => {
      const props = feature.properties || {};
      const sector = (props.sector || "other").toLowerCase();
      const color = SCHOOL_SECTOR_COLORS[sector] || SCHOOL_SECTOR_COLORS.other;
      const position = feature.geometry?.coordinates;
      if (!position || !Array.isArray(position) || position.length < 2) return null;
      const [lon, lat] = position;
      return (
        <CircleMarker
          key={`school-${index}`}
          center={[lat, lon]}
          radius={5}
          pathOptions={{ color, fillColor: color, fillOpacity: 0.9 }}
          eventHandlers={{
            click: () => {
              setSelectedSchool(feature as GeoFeature);
              setSelectedSa1(null);
            }
          }}
        >
          <Popup>
            <strong>{props.schoolname || "School"}</strong>
            <br />
            {props.sector && <span>{props.sector}</span>}
          </Popup>
        </CircleMarker>
      );
    });
  }, [filteredSchools]);

  if (loading) {
    return <div className="map-loading">Loading map data…</div>;
  }

  if (error || !data) {
    return <div className="map-loading">{error || "Failed to load map data."}</div>;
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <h1>Suburb Explorer</h1>
        <div className="form-group">
          <label htmlFor="state">State or territory</label>
          <select
            id="state"
            value={selectedState || ""}
            onChange={(event) => setSelectedState(event.target.value || null)}
          >
            {data.metadata.states.map((state) => (
              <option key={state} value={state}>
                {state}
              </option>
            ))}
          </select>
        </div>

        <form className="form-group" onSubmit={handleGeocode}>
          <label htmlFor="address">Search address</label>
          <input
            id="address"
            type="text"
            placeholder="140 William St, Perth"
            value={addressQuery}
            onChange={(event) => setAddressQuery(event.target.value)}
          />
          <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.5rem" }}>
            <button type="submit" className="primary full-width">
              Search
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => {
                setAddressPin(null);
                setGeocodeStatus(null);
              }}
            >
              Clear
            </button>
          </div>
          {geocodeStatus && <div className="alert info">{geocodeStatus}</div>}
        </form>

        {schoolPercentileDefault != null && (
          <div className="form-group">
            <label htmlFor="percentile">Maximum school percentile ({percentileMax ?? schoolPercentileDefault})</label>
            <input
              id="percentile"
              type="range"
              min={0}
              max={100}
              value={percentileMax ?? schoolPercentileDefault}
              onChange={(event) => setPercentileMax(Number(event.target.value))}
              className="slider-input"
            />
          </div>
        )}

        <div className="section-title">Dataset status</div>
        <div className="alert success">Loaded {data.metadata.count} SA1 polygons.</div>
        {data.seifaWarning && <div className="alert warning">{data.seifaWarning}</div>}
        {data.schoolsWarning && <div className="alert warning">{data.schoolsWarning}</div>}
        {data.rankingWarning && <div className="alert warning">{data.rankingWarning}</div>}
        {data.transitWarning && <div className="alert warning">{data.transitWarning}</div>}
        {data.catchmentsWarning && <div className="alert warning">{data.catchmentsWarning}</div>}

        <div className="section-title">ArcGIS layers</div>
        {data.arcgisManifest.layers.length ? (
          <div className="form-group">
            <label htmlFor="processed-arcgis">Processed GeoJSON layers</label>
            <select
              id="processed-arcgis"
              multiple
              value={selectedProcessedLayers}
              onChange={(event) =>
                setSelectedProcessedLayers(
                  Array.from(event.target.selectedOptions, (option) => option.value)
                )
              }
              style={{ minHeight: "6rem" }}
            >
              {data.arcgisManifest.layers.map((layer) => (
                <option key={layer.name} value={layer.name}>
                  {layer.name}
                </option>
              ))}
            </select>
          </div>
        ) : (
          <div className="alert info">No preprocessed ArcGIS layers found.</div>
        )}
        {processedLayerError && <div className="alert warning">{processedLayerError}</div>}

        <div className="form-group">
          <label>Fetch live ArcGIS layer</label>
          <input
            type="text"
            placeholder="Layer display name"
            value={arcgisName}
            onChange={(event) => setArcgisName(event.target.value)}
            style={{ marginBottom: "0.5rem" }}
          />
          <textarea
            value={arcgisUrl}
            onChange={(event) => setArcgisUrl(event.target.value)}
            placeholder="https://services.arcgis.com/.../FeatureServer/0"
            rows={3}
            style={{ marginBottom: "0.5rem" }}
          />
          <input
            type="text"
            value={arcgisWhere}
            onChange={(event) => setArcgisWhere(event.target.value)}
            placeholder="1=1"
            style={{ marginBottom: "0.5rem" }}
          />
          <button type="button" className="primary full-width" onClick={handleArcgisAdd} disabled={addingArcgis}>
            {addingArcgis ? "Loading…" : "Add ArcGIS layer"}
          </button>
          {arcgisError && <div className="alert warning">{arcgisError}</div>}
        </div>

        {temporaryArcgis.length > 0 && (
          <div>
            <div className="section-title">Temporary layers</div>
            {temporaryArcgis.map((layer, index) => (
              <div key={layer.name + index} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "0.25rem" }}>
                <span>{layer.name}</span>
                <button
                  type="button"
                  className="secondary"
                  onClick={() =>
                    setTemporaryArcgis((prev) => prev.filter((_, idx) => idx !== index))
                  }
                >
                  Remove
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="section-title">ImageServer layers</div>
        <div className="form-group">
          <input
            type="text"
            placeholder="Layer display name"
            value={imageLayerName}
            onChange={(event) => setImageLayerName(event.target.value)}
            style={{ marginBottom: "0.5rem" }}
          />
          <textarea
            value={imageLayerUrl}
            onChange={(event) => setImageLayerUrl(event.target.value)}
            placeholder="https://services.arcgis.com/.../ImageServer"
            rows={3}
            style={{ marginBottom: "0.5rem" }}
          />
          <label htmlFor="image-opacity">Opacity ({imageLayerOpacity}%)</label>
          <input
            id="image-opacity"
            type="range"
            min={10}
            max={100}
            value={imageLayerOpacity}
            onChange={(event) => setImageLayerOpacity(Number(event.target.value))}
            className="slider-input"
          />
          <label htmlFor="image-format" style={{ marginTop: "0.5rem" }}>
            Format
          </label>
          <select
            id="image-format"
            value={imageLayerFormat}
            onChange={(event) => setImageLayerFormat(event.target.value)}
            style={{ marginBottom: "0.5rem" }}
          >
            <option value="png32">PNG32 (default)</option>
            <option value="png">PNG</option>
            <option value="jpg">JPG</option>
          </select>
          <button type="button" className="primary full-width" onClick={handleAddImageLayer}>
            Add ImageServer layer
          </button>
          {imageLayerError && <div className="alert warning">{imageLayerError}</div>}
        </div>
        {imageLayers.length > 0 && (
          <div>
            {imageLayers.map((layer, index) => (
              <div key={`image-${index}`} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "0.25rem" }}>
                <span>{layer.name}</span>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => setImageLayers((prev) => prev.filter((_, idx) => idx !== index))}
                >
                  Remove
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="section-title">KMZ / KML layers</div>
        <div className="form-group">
          <input type="file" accept=".kmz,.kml" onChange={handleKmzUpload} />
          {kmzLoading && <div className="alert info">Processing file…</div>}
          {kmzError && <div className="alert warning">{kmzError}</div>}
        </div>
        {kmzLayers.length > 0 && (
          <div>
            {kmzLayers.map((layer, index) => (
              <div key={`kmz-${index}`} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "0.25rem" }}>
                <span>{layer.name}</span>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => setKmzLayers((prev) => prev.filter((_, idx) => idx !== index))}
                >
                  Remove
                </button>
              </div>
            ))}
          </div>
        )}
      </aside>

      <section className="map-panel">
        <div className="map-container">
          <MapContainer
            center={mapCenter as [number, number]}
            zoom={selectedState ? 10 : 4}
            style={{ height: "100%", width: "100%" }}
            scrollWheelZoom
            whenCreated={(mapInstance) => {
              mapRef.current = mapInstance;
            }}
          >
            <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" attribution="&copy; OpenStreetMap contributors" />
            <LayersControl position="topright">
              {filteredSa1 && (
                <LayersControl.Overlay checked name="SA1 areas">
                  <GeoJSON data={filteredSa1 as FeatureCollection} style={makeSa1Style(data.metadata.iradRange)} onEachFeature={sa1FeatureHandler} />
                </LayersControl.Overlay>
              )}
              {selectedSa1Collection && (
                <LayersControl.Overlay checked name="Selected SA1">
                  <GeoJSON
                    data={selectedSa1Collection as FeatureCollection}
                    style={() => ({ color: "#d62828", fillColor: "#ff6b6b", weight: 3, fillOpacity: 0.45 })}
                  />
                </LayersControl.Overlay>
              )}
              {data.transit.train && (
                <LayersControl.Overlay name="PTA metro (train)">
                  <GeoJSON data={data.transit.train as FeatureCollection} style={() => ({ color: "#003f5c", weight: 4, opacity: 0.9 })} />
                </LayersControl.Overlay>
              )}
              {data.transit.bus && (
                <LayersControl.Overlay name="PTA bus network">
                  <GeoJSON data={data.transit.bus as FeatureCollection} style={() => ({ color: "#ffa600", weight: 2, opacity: 0.9 })} />
                </LayersControl.Overlay>
              )}
              {data.transit.other && (
                <LayersControl.Overlay name="PTA services">
                  <GeoJSON data={data.transit.other as FeatureCollection} style={() => ({ color: "#3740ff", weight: 3, opacity: 0.8 })} />
                </LayersControl.Overlay>
              )}
              {Object.entries(data.catchments).map(([level, layer]) => (
                <LayersControl.Overlay key={level} name={CATCHMENT_LABELS[level] || level}>
                  <GeoJSON
                    data={layer as FeatureCollection}
                    style={() => ({
                      color: CATCHMENT_COLORS[level] || "#6d597a",
                      fillColor: CATCHMENT_COLORS[level] || "#6d597a",
                      weight: 2,
                      fillOpacity: 0.15
                    })}
                  />
                </LayersControl.Overlay>
              ))}
              {schoolMarkers.length > 0 && (
                <LayersControl.Overlay checked name="Schools">
                  <LayerGroup>{schoolMarkers}</LayerGroup>
                </LayersControl.Overlay>
              )}
              {temporaryArcgis.map((layer, index) => (
                <LayersControl.Overlay key={`temp-${index}`} name={layer.name}>
                  <GeoJSON data={layer.data as FeatureCollection} style={() => ({ color: "#8f2d56", weight: 2, fillOpacity: 0.2 })} />
                </LayersControl.Overlay>
              ))}
              {selectedProcessedLayers.map((name) => {
                const layer = processedLayerData[name];
                if (!layer) return null;
                return (
                  <LayersControl.Overlay key={`processed-${name}`} name={`ArcGIS (processed) - ${name}`}>
                    <GeoJSON data={layer as FeatureCollection} style={() => ({ color: "#8338ec", weight: 2, fillOpacity: 0.2 })} />
                  </LayersControl.Overlay>
                );
              })}
              {imageLayers.map((layer, index) => (
                <LayersControl.Overlay key={`image-${index}`} name={`ImageServer - ${layer.name}`} checked>
                  <ArcgisImageLayer url={layer.url} opacity={layer.opacity} format={layer.format as any} />
                </LayersControl.Overlay>
              ))}
              {kmzLayers.map((layer, index) => (
                <LayersControl.Overlay key={`kmz-${index}`} name={`KMZ - ${layer.name}`}>
                  <GeoJSON data={layer.data as FeatureCollection} style={() => ({ color: "#0f4c5c", weight: 2, fillOpacity: 0.2 })} />
                </LayersControl.Overlay>
              ))}
            </LayersControl>
            {addressPin && (
              <CircleMarker
                center={[addressPin.lat, addressPin.lon]}
                radius={6}
                pathOptions={{ color: "#d62828", fillColor: "#d62828", fillOpacity: 0.9 }}
              >
                <Popup>{addressPin.address}</Popup>
              </CircleMarker>
            )}
          </MapContainer>
        </div>
        <div className="details-panel">
          {selectedSchool ? (
            <div>
              <h2>{selectedSchool.properties?.schoolname || "School"}</h2>
              <ul className="detail-list">
                {SCHOOL_DETAIL_FIELDS.map(([field, label]) => {
                  const value = formatValue(selectedSchool.properties?.[field]);
                  if (!value) return null;
                  return (
                    <li key={field}>
                      <strong>{label}:</strong> {value}
                    </li>
                  );
                })}
              </ul>
              <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                {buildLiaMapUrl(selectedSchool.properties?.schoolcode) && (
                  <a
                    className="primary"
                    href={buildLiaMapUrl(selectedSchool.properties?.schoolcode) || "#"}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Download intake map
                  </a>
                )}
                {buildLiaPageUrl(selectedSchool.properties?.schoolcode) && (
                  <a
                    className="secondary"
                    href={buildLiaPageUrl(selectedSchool.properties?.schoolcode) || "#"}
                    target="_blank"
                    rel="noreferrer"
                  >
                    View LIA page
                  </a>
                )}
              </div>
            </div>
          ) : selectedSa1 ? (
            <div>
              <h2>{selectedSa1.properties?.SA1_NAME21 || selectedSa1.properties?.SA2_NAME21}</h2>
              <ul className="detail-list">
                {SA1_DETAIL_FIELDS.map(([field, label]) => {
                  const value = formatValue(selectedSa1.properties?.[field]);
                  if (!value) return null;
                  return (
                    <li key={field}>
                      <strong>{label}:</strong> {value}
                    </li>
                  );
                })}
              </ul>
            </div>
          ) : (
            <div className="alert info">Click a school marker or SA1 polygon to see more details.</div>
          )}
        </div>
      </section>
    </div>
  );
}

export default App;
