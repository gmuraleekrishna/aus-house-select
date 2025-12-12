import type {
  ArcgisManifest,
  CatchmentsSummary,
  GeoCollection,
  MapData,
  MapMetadata,
  SchoolsSummary,
  TransitLayers
} from "../types";
import type { Feature } from "geojson";
import { buildMetadata } from "./geojson";
import { ensureSchoolStages, summarizeSchools } from "./schools";

const SA1_FILE = "/sa1_2021.geojson";
const SCHOOLS_FILE = "/schools_2019.geojson";
const CATCHMENTS_FILE = "/school_catchments.geojson";
const TRANSIT_FILE = "/transit_services.geojson";
const ARCGIS_MANIFEST = "/arcgis_layers/index.json";

async function fetchJson<T>(path: string): Promise<T | null> {
  try {
    const response = await fetch(path);
    if (!response.ok) {
      console.warn(`Failed to fetch ${path}:`, response.statusText);
      return null;
    }
    return (await response.json()) as T;
  } catch (error) {
    console.error(`Fetch error for ${path}`, error);
    return null;
  }
}

function groupTransitLayers(data: GeoCollection | null): TransitLayers {
  if (!data?.features?.length) return {};
  const routeType = (feature: Feature) => {
    const props = feature.properties || {};
    for (const key of ["ROUTETYPE", "RouteType", "route_type"]) {
      if (props[key] != null) {
        return String(props[key]).trim().toLowerCase();
      }
    }
    return "";
  };

  const makeCollection = (predicate: (feature: Feature) => boolean): GeoCollection => ({
    type: "FeatureCollection",
    features: data.features.filter(predicate)
  });

  const train = makeCollection((feature) => routeType(feature) === "train");
  const bus = makeCollection((feature) =>
    ["standard", "cat", "school"].includes(routeType(feature))
  );
  const other = makeCollection((feature) => !["train", "standard", "cat", "school"].includes(routeType(feature)));

  const layers: TransitLayers = {};
  if (train.features.length) layers.train = train;
  if (bus.features.length) layers.bus = bus;
  if (other.features.length) layers.other = other;
  if (!layers.train && !layers.bus && !layers.other) {
    layers.all = data;
  }
  return layers;
}

function summarizeCatchments(data: GeoCollection | null): {
  layers: Record<string, GeoCollection>;
  summary: CatchmentsSummary | null;
  warning?: string;
} {
  if (!data?.features?.length) {
    return { layers: {}, summary: null, warning: "Catchment GeoJSON not found or empty." };
  }

  const layers: Record<string, GeoCollection> = {};
  const collect = (level: string) => {
    const features = data.features.filter(
      (feature) => (feature.properties || {}).catchment_level === level
    );
    if (features.length) {
      layers[level] = { type: "FeatureCollection", features };
    }
  };
  collect("primary");
  collect("high");
  collect("other");

  const summary: CatchmentsSummary = {
    count: data.features.length,
    levels: Object.fromEntries(Object.entries(layers).map(([level, layer]) => [level, layer.features.length]))
  };

  return { layers, summary };
}

async function loadArcgisManifest(): Promise<ArcgisManifest> {
  const manifest = await fetchJson<ArcgisManifest>(ARCGIS_MANIFEST);
  if (!manifest) {
    return { layers: [] };
  }
  return manifest;
}

export async function fetchArcgisGeojson(url: string, where = "1=1", outFields = "*") {
  const target = url.trim().endsWith("/query") ? url.trim() : `${url.trim().replace(/\/?$/, "")}/query`;
  const params = new URLSearchParams({ where, outFields, f: "geojson" }).toString();
  const fullUrl = `${target}?${params}`;
  const response = await fetch(fullUrl);
  if (!response.ok) {
    throw new Error(`ArcGIS request failed: ${response.statusText}`);
  }
  const data = await response.json();
  if (data.error) {
    throw new Error(data.error.message || "ArcGIS error");
  }
  return data as GeoCollection;
}

export async function loadMapData(): Promise<MapData> {
  const [sa1, transitSource, schools, catchmentsSource, arcgisManifest] = await Promise.all([
    fetchJson<GeoCollection>(SA1_FILE),
    fetchJson<GeoCollection>(TRANSIT_FILE),
    fetchJson<GeoCollection>(SCHOOLS_FILE),
    fetchJson<GeoCollection>(CATCHMENTS_FILE),
    loadArcgisManifest()
  ]);

  if (!sa1) {
    throw new Error("SA1 dataset is required. Ensure assets are generated under /assets.");
  }

  const metadata: MapMetadata = buildMetadata(sa1);
  const transit = groupTransitLayers(transitSource);
  const stagedSchools = ensureSchoolStages(schools);
  const schoolsSummary: SchoolsSummary | null = summarizeSchools(stagedSchools);
  const { layers: catchments, summary: catchmentsSummary, warning: catchmentsWarning } = summarizeCatchments(
    catchmentsSource
  );
  let rankingWarning: string | undefined;
  if (stagedSchools?.features?.length) {
    const hasRanking = stagedSchools.features.some(
      (feature) => feature.properties && feature.properties.ranking_rank != null
    );
    if (!hasRanking) {
      rankingWarning =
        "Ranking attributes missing from processed schools GeoJSON. Re-run scripts/prep_geojson.py --schools with the ranking XML.";
    }
  }

  return {
    sa1,
    metadata,
    transit,
    schools: stagedSchools,
    schoolsSummary,
    catchments,
    catchmentsSummary,
    catchmentsWarning,
    transitWarning: transitSource ? undefined : "Transit GeoJSON missing from assets.",
    schoolsWarning: stagedSchools ? undefined : "Schools GeoJSON missing from assets.",
    rankingWarning,
    seifaWarning: metadata.seifaColumns.length ? undefined : "SEIFA fields missing from SA1 GeoJSON.",
    arcgisManifest
  };
}
