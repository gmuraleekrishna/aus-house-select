import type { GeoCollection, GeoFeature, MapMetadata } from "../types";

const STATE_CAPITALS: Record<string, [number, number]> = {
  "Australian Capital Territory": [-35.2931, 149.1269],
  "New South Wales": [-33.8678, 151.21],
  "Northern Territory": [-12.4381, 130.8411],
  Queensland: [-27.4678, 153.0281],
  "South Australia": [-34.9275, 138.6],
  Tasmania: [-42.8806, 147.325],
  Victoria: [-37.8142, 144.9631],
  "Western Australia": [-31.9559, 115.8606]
};

function flattenCoords(geometry: GeoJSON.Geometry | null | undefined, points: number[][]): void {
  if (!geometry) return;
  switch (geometry.type) {
    case "Point": {
      const [lon, lat] = geometry.coordinates as number[];
      points.push([lon, lat]);
      break;
    }
    case "MultiPoint":
    case "LineString": {
      for (const coord of geometry.coordinates as number[][]) {
        points.push(coord as number[]);
      }
      break;
    }
    case "MultiLineString":
    case "Polygon": {
      for (const ring of geometry.coordinates as number[][][]) {
        for (const coord of ring) {
          points.push(coord as number[]);
        }
      }
      break;
    }
    case "MultiPolygon": {
      for (const polygon of geometry.coordinates as number[][][][]) {
        for (const ring of polygon) {
          for (const coord of ring) {
            points.push(coord as number[]);
          }
        }
      }
      break;
    }
    case "GeometryCollection": {
      for (const geom of geometry.geometries) {
        flattenCoords(geom, points);
      }
      break;
    }
    default:
      break;
  }
}

function computeBounds(collection: GeoCollection | GeoFeature[]): [number, number, number, number] | null {
  const points: number[][] = [];
  const features = Array.isArray(collection) ? collection : collection.features || [];
  for (const feature of features) {
    flattenCoords(feature.geometry, points);
  }
  if (!points.length) return null;
  let minLon = Infinity;
  let minLat = Infinity;
  let maxLon = -Infinity;
  let maxLat = -Infinity;
  for (const [lon, lat] of points) {
    if (Number.isFinite(lon) && Number.isFinite(lat)) {
      minLon = Math.min(minLon, lon);
      minLat = Math.min(minLat, lat);
      maxLon = Math.max(maxLon, lon);
      maxLat = Math.max(maxLat, lat);
    }
  }
  if (!Number.isFinite(minLon) || !Number.isFinite(minLat) || !Number.isFinite(maxLon) || !Number.isFinite(maxLat)) {
    return null;
  }
  return [minLon, minLat, maxLon, maxLat];
}

export function buildMetadata(data: GeoCollection): MapMetadata {
  const propertyNames = new Set<string>();
  const sa2ByState: Record<string, Set<string>> = {};
  const stateCenters: Record<string, [number, number]> = {};
  const iradValues: number[] = [];

  for (const feature of data.features || []) {
    const props = feature.properties || {};
    Object.keys(props).forEach((name) => propertyNames.add(name));
    const state = props["STE_NAME21"] as string | undefined;
    const sa2 = props["SA2_NAME21"] as string | undefined;
    if (state) {
      if (!sa2ByState[state]) sa2ByState[state] = new Set();
      if (sa2) sa2ByState[state].add(sa2);
    }
    const decile = Number(props["IRAD_decile"]);
    if (!Number.isNaN(decile)) {
      iradValues.push(decile);
    }
  }

  for (const [state, sa2] of Object.entries(sa2ByState)) {
    const subset = (data.features || []).filter(
      (feature) => (feature.properties || {})["STE_NAME21"] === state
    );
    const bounds = computeBounds(subset);
    if (bounds) {
      const [minLon, minLat, maxLon, maxLat] = bounds;
      stateCenters[state] = [
        Number(((minLat + maxLat) / 2).toFixed(6)),
        Number(((minLon + maxLon) / 2).toFixed(6))
      ];
    }
  }

  const seifaColumns = Array.from(propertyNames).filter((name) =>
    ["IRSD_", "IRAD_", "IER_", "IEO_"].some((prefix) => name.startsWith(prefix)) || name === "URP"
  );

  const metadata: MapMetadata = {
    states: Object.keys(sa2ByState).sort(),
    sa2ByState: Object.fromEntries(
      Object.entries(sa2ByState).map(([state, values]) => [state, Array.from(values).sort()])
    ),
    totalBounds: computeBounds(data),
    stateCenters,
    propertyNames: Array.from(propertyNames),
    count: data.features?.length || 0,
    iradRange: iradValues.length ? [Math.min(...iradValues), Math.max(...iradValues)] : null,
    seifaColumns
  };

  return metadata;
}

export function getMapCenter(meta: MapMetadata, state: string | null): [number, number] {
  if (state) {
    if (STATE_CAPITALS[state]) {
      return STATE_CAPITALS[state];
    }
    const computed = meta.stateCenters[state];
    if (computed) {
      return computed;
    }
  }
  if (meta.totalBounds) {
    const [minLon, minLat, maxLon, maxLat] = meta.totalBounds;
    return [(minLat + maxLat) / 2, (minLon + maxLon) / 2];
  }
  return [-25.2744, 133.7751];
}

const SCORE_SUFFIXES = ["_score", "_Score"];
const SEIFA_DISPLAY: Record<string, string> = {
  IRSD_score: "IRSD score",
  IRSD_decile: "IRSD decile",
  IRAD_score: "IRAD score",
  IRAD_decile: "IRAD decile",
  IER_score: "IER score",
  IER_decile: "IER decile",
  IEO_score: "IEO score",
  IEO_decile: "IEO decile",
  URP: "URP"
};

export function buildTooltipFields(propertyNames: string[], extra?: string[]) {
  const picks: Array<[string, string]> = [];
  const add = (field: string, label: string) => {
    if (propertyNames.includes(field)) {
      picks.push([field, label]);
    }
  };
  add("SA1_NAME21", "SA1:");
  add("SA2_NAME21", "SA2:");
  add("SA3_NAME21", "SA3:");
  add("STE_NAME21", "State:");
  if (extra) {
    for (const field of extra) {
      if (SCORE_SUFFIXES.some((suffix) => field.endsWith(suffix))) continue;
      const alias = SEIFA_DISPLAY[field] || `${field}:`;
      add(field, alias);
    }
  }
  if (!picks.length && propertyNames.length) {
    const fallback = propertyNames[0];
    picks.push([fallback, `${fallback}:`]);
  }
  if (!picks.length) {
    picks.push(["SA1_CODE21", "SA1 code:"]);
  }
  return {
    fields: picks.map(([field]) => field),
    aliases: picks.map(([, alias]) => alias)
  };
}

function interpolateColor(a: [number, number, number], b: [number, number, number], t: number) {
  return a.map((value, idx) => Math.round(value + (b[idx] - value) * t)) as [number, number, number];
}

const GRADIENT = {
  red: [215, 48, 39] as [number, number, number],
  yellow: [254, 224, 139] as [number, number, number],
  green: [26, 152, 80] as [number, number, number]
};

export function colorForIradDecile(decile: number | string | null | undefined, range: [number, number] | null) {
  if (decile == null || !range) return "#b0bec5";
  const value = Number(decile);
  if (Number.isNaN(value)) return "#b0bec5";
  const [min, max] = range;
  const ratio = min === max ? 0.5 : Math.min(1, Math.max(0, (value - min) / (max - min)));
  let rgb: [number, number, number];
  if (ratio <= 0.5) {
    const local = ratio / 0.5;
    rgb = interpolateColor(GRADIENT.red, GRADIENT.yellow, local);
  } else {
    const local = (ratio - 0.5) / 0.5;
    rgb = interpolateColor(GRADIENT.yellow, GRADIENT.green, local);
  }
  return `#${rgb.map((channel) => channel.toString(16).padStart(2, "0")).join("")}`;
}

export function makeSa1Style(range: [number, number] | null) {
  return (feature: GeoFeature) => {
    const color = colorForIradDecile(feature.properties?.["IRAD_decile"], range);
    return {
      color,
      fillColor: color,
      weight: 1,
      fillOpacity: 0.45
    };
  };
}
