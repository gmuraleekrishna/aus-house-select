import type { GeoCollection } from "../types";
import JSZip from "jszip";
import { kml as kmlToGeojson } from "@tmcw/togeojson";

function parseKmlText(text: string): GeoCollection {
  const parser = new DOMParser();
  const dom = parser.parseFromString(text, "text/xml");
  const geojson = kmlToGeojson(dom) as GeoCollection;
  if (!geojson || !geojson.features) {
    throw new Error("KML document did not contain features.");
  }
  return geojson;
}

async function extractKmlFromKmz(file: File): Promise<string> {
  const buffer = await file.arrayBuffer();
  const zip = await JSZip.loadAsync(buffer);
  const kmlEntry = zip.file(/\.kml$/i)?.[0];
  if (!kmlEntry) {
    throw new Error("KMZ archive does not contain a KML file.");
  }
  return kmlEntry.async("text");
}

export async function loadKmzLayer(file: File): Promise<GeoCollection> {
  const name = file.name.toLowerCase();
  if (name.endsWith(".kmz")) {
    const kmlText = await extractKmlFromKmz(file);
    return parseKmlText(kmlText);
  }
  if (name.endsWith(".kml")) {
    const text = await file.text();
    return parseKmlText(text);
  }
  throw new Error("Only KMZ or KML files are supported.");
}
