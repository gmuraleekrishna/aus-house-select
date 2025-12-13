import type { FeatureCollection, Feature } from "geojson";

export type Properties = Record<string, any>;

export type GeoFeature = Feature<GeoJSON.Geometry, Properties>;
export type GeoCollection = FeatureCollection<GeoJSON.Geometry, Properties>;

export interface MapMetadata {
  states: string[];
  sa2ByState: Record<string, string[]>;
  totalBounds: [number, number, number, number] | null;
  stateCenters: Record<string, [number, number]>;
  propertyNames: string[];
  count: number;
  iradRange: [number, number] | null;
  seifaColumns: string[];
}

export interface TransitLayers {
  train?: GeoCollection;
  bus?: GeoCollection;
  other?: GeoCollection;
  all?: GeoCollection;
}

export interface SchoolsSummary {
  count: number;
  sectorCounts: Record<string, number>;
  remoteCounts: Record<string, number>;
  stageCounts: Record<string, number>;
}

export interface CatchmentsSummary {
  count: number;
  levels: Record<string, number>;
}

export interface MapData {
  sa1: GeoCollection;
  metadata: MapMetadata;
  transit: TransitLayers;
  schools: GeoCollection | null;
  schoolsSummary: SchoolsSummary | null;
  schoolsWarning?: string;
  rankingWarning?: string;
  catchments: Record<string, GeoCollection>;
  catchmentsSummary: CatchmentsSummary | null;
  catchmentsWarning?: string;
  transitWarning?: string;
  seifaWarning?: string;
  arcgisManifest: ArcgisManifest;
  stops: GeoCollection | null;
}

export interface ArcgisManifestEntry {
  name: string;
  file: string;
}

export interface ArcgisManifest {
  layers: ArcgisManifestEntry[];
}

export interface SchoolSelection {
  feature: GeoFeature;
}

export interface Sa1Selection {
  feature: GeoFeature;
}
