# House Selector

React + TypeScript explorer for Australian ABS SA1 polygons, socio-economic metrics, school locations/rankings, catchments, and transit services. The web UI loads the processed GeoJSON files from `assets/` and renders interactive overlays via Leaflet.

## Stack overview
- Frontend: [Vite](https://vitejs.dev/) + React + TypeScript (`web/`).
- Mapping: Leaflet + GeoJSON overlays (SA1, schools, transit, catchments, ArcGIS downloads).
- Data prep: existing Python scripts under `scripts/` still generate GeoJSON files from shapefiles / Excel workbooks.

## Prerequisites
- Node.js 18+ (for the frontend build/dev server).
- Python 3.11+ (for the optional preprocessing helpers).
- [uv](https://github.com/astral-sh/uv) or pip if you need to install the Python tooling.

## Running the TypeScript app
```bash
cd web
npm install
npm run dev         # start Vite dev server on http://localhost:5173
npm run build       # optional: generate production build
```
The Vite config exposes everything inside `assets/` as static files, so keep your processed GeoJSONs there (`sa1_2021.geojson`, `schools_2019.geojson`, `school_catchments.geojson`, `transit_services.geojson`, etc.).

### ArcGIS layers
Place any preprocessed `.geojson` exports under `assets/arcgis_layers/` and regenerate the manifest so the UI can list them:
```bash
python scripts/build_arcgis_manifest.py
```
This writes/updates `assets/arcgis_layers/index.json` that the frontend consumes. You can also fetch ad-hoc ArcGIS FeatureServer layers directly from the sidebar in the running app.

### KMZ / KML overlays
Use the “KMZ / KML layers” uploader in the sidebar to add ad-hoc geospatial overlays. The browser unzips KMZ files on the fly and converts them to GeoJSON so they appear as toggleable Leaflet layers without needing any preprocessing.
If you prefer offline conversion (e.g., to ship the processed files with the app), use the prep script:
```bash
python scripts/prep_geojson.py --kmz-file data/custom_layer.kmz
```
Converted files are written to `data/processed/arcgis_layers/`; copy them into `assets/arcgis_layers/` and rebuild the manifest.

### ArcGIS ImageServer overlays
Paste any ImageServer endpoint into the “ImageServer layers” form in the sidebar to render it as a dynamic raster overlay. You can control the label and opacity (PNG/JPG formats supported) and toggle the resulting layers inside the Leaflet control like the other data sources.

## Preparing datasets (Python helpers)
The original preprocessing scripts are unchanged and still live under `scripts/`. Run them from the repo root to populate `assets/`:
```bash
uv sync                     # install Python deps once
uv run python scripts/prep_geojson.py            # builds all datasets
uv run python scripts/prep_geojson.py --sa1      # only SA1 + SEIFA merge
uv run python scripts/prep_geojson.py --catchments --schools
uv run python scripts/prep_geojson.py --arcgis-url "https://services.arcgis.com/.../FeatureServer/0"
```
Outputs land in `data/processed/`; copy or symlink the GeoJSON files into `assets/` (or point the scripts there directly) so the React app can fetch them.

## Development notes
- Local dev/build: `npm run dev`, `npm run build`, `npm run preview`.
- Tests/linters are not yet wired up; add Vitest/ESLint if you need automation.
- The legacy Streamlit code is no longer used for the UI but remains in `src/` for reference until the data prep scripts are ported.
