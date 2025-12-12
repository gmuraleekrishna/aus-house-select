import type { GeoCollection, GeoFeature, SchoolsSummary } from "../types";

function computeStage(lowYear?: string | null, highYear?: string | null) {
  const normalize = (value?: string | null) => (value || "").toUpperCase();
  const low = normalize(lowYear);
  const high = normalize(highYear);

  const toInt = (value: string) => {
    if (value.startsWith("Y") && value.length >= 3) {
      const parsed = parseInt(value.substring(1, 3), 10);
      return Number.isNaN(parsed) ? null : parsed;
    }
    return null;
  };

  const lowNum = toInt(low);
  const highNum = toInt(high);
  let hasPrimary = false;
  let hasSecondary = false;

  if (["KIN", "PP", "P"].includes(low) || ["KIN", "PP", "P"].includes(high)) {
    hasPrimary = true;
  }

  if (lowNum !== null) {
    if (lowNum <= 6) hasPrimary = true;
    if (lowNum >= 7) hasSecondary = true;
  }

  if (highNum !== null) {
    if (highNum <= 6) hasPrimary = true;
    if (highNum >= 7) hasSecondary = true;
  }

  if (hasPrimary && hasSecondary) return "combined";
  if (hasPrimary) return "primary";
  if (hasSecondary) return "secondary";
  return "other";
}

export function ensureSchoolStages(collection: GeoCollection | null) {
  if (!collection) return null;
  const mutated = collection.features?.map((feature) => {
    if (!feature.properties) feature.properties = {};
    if (!feature.properties.stage) {
      feature.properties.stage = computeStage(
        feature.properties?.lowyear,
        feature.properties?.highyear
      );
    }
    return feature;
  });
  return { ...collection, features: mutated || [] };
}

export function summarizeSchools(collection: GeoCollection | null): SchoolsSummary | null {
  if (!collection?.features?.length) return null;
  const sectorCounts: Record<string, number> = {};
  const remoteCounts: Record<string, number> = {};
  const stageCounts: Record<string, number> = {
    primary: 0,
    secondary: 0,
    combined: 0,
    other: 0
  };

  for (const feature of collection.features) {
    const props = feature.properties || {};
    const sector = String(props.sector || "").trim();
    if (sector) {
      sectorCounts[sector] = (sectorCounts[sector] || 0) + 1;
    }
    const remote = String(props.remotearea || "").trim();
    if (remote) {
      remoteCounts[remote] = (remoteCounts[remote] || 0) + 1;
    }
    const stage = (props.stage || "other").toLowerCase();
    if (stageCounts[stage] !== undefined) {
      stageCounts[stage] += 1;
    } else {
      stageCounts.other += 1;
    }
  }

  return {
    count: collection.features.length,
    sectorCounts,
    remoteCounts,
    stageCounts
  };
}

export function parsePercentile(value: unknown): number | null {
  if (value == null) return null;
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const cleaned = value.replace(/%/g, "").trim();
    if (!cleaned) return null;
    const parsed = Number(cleaned);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

export function formatValue(value: unknown): string | null {
  if (value == null) return null;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return null;
    if (Number.isInteger(value)) {
      return value.toString();
    }
    return value.toFixed(2);
  }
  const text = String(value).trim();
  return text || null;
}

export function formatSchoolCode(value: unknown): string | null {
  if (value == null) return null;
  if (typeof value === "number") return Math.trunc(value).toString();
  const numeric = Number(String(value).trim());
  if (!Number.isNaN(numeric)) {
    return Math.trunc(numeric).toString();
  }
  const text = String(value).trim();
  return text || null;
}

export function extractSchoolClick(feature: GeoFeature | null, latLng?: { lat: number; lng: number }) {
  if (!feature && !latLng) return null;
  return feature || null;
}
