#!/usr/bin/env python3
"""Generate assets/arcgis_layers/index.json for the TypeScript client."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAYER_DIR = ROOT / "assets" / "arcgis_layers"
MANIFEST_PATH = LAYER_DIR / "index.json"

def build_manifest() -> None:
    LAYER_DIR.mkdir(parents=True, exist_ok=True)
    layers = []
    for geojson_path in sorted(LAYER_DIR.glob("*.geojson")):
        rel_path = f"arcgis_layers/{geojson_path.name}"
        layers.append({"name": geojson_path.stem, "file": rel_path})
    manifest = {"layers": layers}
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))
    print(f"Wrote {len(layers)} layer entries to {MANIFEST_PATH.relative_to(ROOT)}")

if __name__ == "__main__":
    build_manifest()
