# ---------------------------------------------------------
# Data helpers
# ---------------------------------------------------------
from pathlib import Path
import json
from collections import defaultdict
from urllib.parse import urlencode
from urllib.request import urlopen
import geopandas as gpd
import pandas as pd
from geopy.geocoders import Nominatim
import logging
import sys

# Configure logging to output to standard output
logging.basicConfig(
    stream=sys.stdout,  # Sends log output to the terminal/Docker stdout
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

STATES_CAPITALS = {
    "Australian Capital Territory": (-35.2931, 149.1269),
    "New South Wales": (-33.8678, 151.2100),
    "Northern Territory": (-12.4381, 130.8411),
    "Queensland": (-27.4678, 153.0281),
    "South Australia": (-34.9275, 138.6000),
    "Tasmania": (-42.8806, 147.3250),
    "Victoria": (-37.8142, 144.9631),
    "Western Australia": (-31.9559, 115.8606),
}


SEIFA_COLUMN_RENAMES = {
    "2021 Statistical Area Level 1 (SA1)": "SA1_CODE21",
    "Index of Relative Socio-economic Disadvantage Score": "IRSD_score",
    "Index of Relative Socio-economic Disadvantage Decile": "IRSD_decile",
    "Index of Relative Socio-economic Advantage and Disadvantage Score": "IRAD_score",
    "Index of Relative Socio-economic Advantage and Disadvantage Decile": "IRAD_decile",
    "Index of Economic Resources Score": "IER_score",
    "Index of Economic Resources Decile": "IER_decile",
    "Index of Education and Occupation Score": "IEO_score",
    "Index of Education and Occupation Decile": "IEO_decile",
    "Usual Resident Population": "URP",
}


def _build_sa1_metadata(gdf):
    sa2_by_state = defaultdict(set)
    for state, sa2 in zip(gdf["STE_NAME21"], gdf["SA2_NAME21"]):
        sa2_by_state[state].add(sa2)

    sa2_by_state = {state: sorted(values) for state, values in sa2_by_state.items()}

    state_centers = {}
    for state, subset in gdf.groupby("STE_NAME21"):
        minx, miny, maxx, maxy = subset.total_bounds
        state_centers[state] = [(miny + maxy) / 2, (minx + maxx) / 2]

    geometry_col = gdf.geometry.name
    property_names = [col for col in gdf.columns if col != geometry_col]

    return {
        "states": sorted(sa2_by_state),
        "sa2_by_state": sa2_by_state,
        "state_centers": state_centers,
        "total_bounds": gdf.total_bounds.tolist(),
        "count": int(len(gdf)),
        "property_names": property_names,
    }


def _compute_school_stage(low_year: str, high_year: str):
    low = (low_year or "").upper()
    high = (high_year or "").upper()

    def year_to_int(val):
        if val.startswith("Y") and len(val) >= 3:
            try:
                return int(val[1:3])
            except ValueError:
                return None
        return None

    low_num = year_to_int(low)
    high_num = year_to_int(high)
    has_primary = False
    has_secondary = False

    if low in {"KIN", "PP", "P"} or high in {"KIN", "PP", "P"}:
        has_primary = True

    if low_num is not None:
        if low_num <= 6:
            has_primary = True
        if low_num >= 7:
            has_secondary = True

    if high_num is not None:
        if high_num <= 6:
            has_primary = True
        if high_num >= 7:
            has_secondary = True

    if has_primary and has_secondary:
        return "combined"
    if has_primary:
        return "primary"
    if has_secondary:
        return "secondary"
    return "other"


def _load_geojson_file(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_geojson_path(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"GeoJSON file not found: {path}")
    return _load_geojson_file(path)


def _ensure_stage(features):
    updated = False
    for feature in features:
        props = feature.setdefault("properties", {})
        if "stage" not in props:
            props["stage"] = _compute_school_stage(
                props.get("lowyear"), props.get("highyear")
            )
            updated = True
    return updated


def geocode_address(query: str):
    geolocator = Nominatim(user_agent="house_selector_app")
    location = geolocator.geocode(query, timeout=10)
    if not location:
        return None
    return {
        "lat": location.latitude,
        "lon": location.longitude,
        "address": location.address,
    }


def load_sa1_dataset(
    path: Path,
    seifa_path: Path | None,
):
    if not path.exists():
        raise FileNotFoundError(
            f"SA1 data not found: {path}. Run `python scripts/prep_geojson.py --sa1`."
        )

    seifa_columns = []
    seifa_warning = None
    irad_range = None

    gdf = gpd.read_file(path)
    gdf = gdf.to_crs(epsg=4326)

    needs_seifa_merge = seifa_path and (
        "IRAD_decile" not in gdf.columns or "IRSD_score" not in gdf.columns
    )
    if needs_seifa_merge:
        if not seifa_path.exists():
            seifa_warning = (
                f"SEIFA data not found: {seifa_path}. "
                "Run `python scripts/prep_excel.py` to generate it."
            )
        else:
            try:
                seifa_df = _load_seifa_table(seifa_path)
            except Exception as exc:  # pragma: no cover - runtime file parsing
                seifa_warning = f"Failed to load SEIFA data: {exc}"
            else:
                gdf = gdf.merge(seifa_df, on="SA1_CODE21", how="left")
                seifa_columns = [col for col in seifa_df.columns if col != "SA1_CODE21"]
                if not irad_range and "IRAD_decile" in seifa_df.columns:
                    series = seifa_df["IRAD_decile"].dropna()
                    if not series.empty:
                        irad_range = (float(series.min()), float(series.max()))

    if not seifa_columns:
        seifa_columns = [
            col
            for col in gdf.columns
            if col.startswith(("IRSD_", "IRAD_", "IER_", "IEO_")) or col == "URP"
        ]

    if "IRAD_decile" in gdf.columns:
        series = gdf["IRAD_decile"].dropna()
        if not series.empty:
            irad_range = (float(series.min()), float(series.max()))

    metadata = _build_sa1_metadata(gdf)
    metadata["seifa_columns"] = seifa_columns
    metadata["seifa_warning"] = seifa_warning
    metadata["irad_range"] = irad_range
    return json.loads(gdf.to_json()), metadata


def load_transit_data(transit_path):
    transit_layers = {}
    transit_warning = None
    if transit_path:
        if not transit_path.exists():
            transit_warning = (
                f"Transit data not found: {transit_path}. "
                "Run `python scripts/prep_geojson.py --transit`."
            )
        else:
            try:
                if transit_path.suffix.lower() == ".shp":
                    transit_gdf = gpd.read_file(transit_path).to_crs(epsg=4326)
                    transit_geojson = json.loads(transit_gdf.to_json())
                else:
                    transit_geojson = _load_geojson_file(transit_path)
                features = transit_geojson.get("features", [])
            except Exception as exc:  # pragma: no cover - runtime guard
                transit_warning = f"Failed to load transit data: {exc}"
            else:

                def route_type(feature):
                    props = feature.get("properties") or {}
                    for key in ("ROUTETYPE", "RouteType", "route_type"):
                        if key in props:
                            return str(props[key]).strip().lower()
                    return ""

                def make_collection(predicate):
                    feats = [feat for feat in features if predicate(feat)]
                    return {"type": "FeatureCollection", "features": feats}

                if features:
                    train_feats = make_collection(lambda f: route_type(f) == "train")
                    bus_feats = make_collection(
                        lambda f: route_type(f) in {"standard", "cat", "school"}
                    )
                    other_feats = make_collection(
                        lambda f: route_type(f)
                        not in {"train", "standard", "cat", "school"}
                    )
                    if train_feats["features"]:
                        transit_layers["train"] = train_feats
                    if bus_feats["features"]:
                        transit_layers["bus"] = bus_feats
                    if other_feats["features"]:
                        transit_layers["other"] = other_feats
                    if not transit_layers:
                        transit_layers["all"] = transit_geojson
    return transit_layers, transit_warning


def load_catchment_data(path: Path | None):
    catchment_layers = {}
    catchments_warning = None
    catchment_summary = None

    if not path:
        catchments_warning = "Catchment file path not provided."
        return catchment_layers, catchment_summary, catchments_warning

    if not path.exists():
        catchments_warning = (
            f"Catchment GeoJSON not found: {path}. "
            "Run `python scripts/prep_geojson.py --catchments`."
        )
        return catchment_layers, catchment_summary, catchments_warning

    try:
        data = _load_geojson_file(path)
        features = data.get("features", [])
    except Exception as exc:  # pragma: no cover - runtime guard
        catchments_warning = f"Failed to load catchments GeoJSON: {exc}"
        return catchment_layers, catchment_summary, catchments_warning

    if not features:
        catchments_warning = "Catchment GeoJSON contains no features."
        return catchment_layers, catchment_summary, catchments_warning

    def collect(level: str):
        subset = [
            feat
            for feat in features
            if (feat.get("properties") or {}).get("catchment_level") == level
        ]
        if subset:
            catchment_layers[level] = {
                "type": "FeatureCollection",
                "features": subset,
            }

    collect("primary")
    collect("high")
    collect("other")

    if not catchment_layers:
        catchments_warning = "Catchment features missing `catchment_level` attributes."

    catchment_summary = {
        "count": len(features),
        "levels": {level: len(layer["features"]) for level, layer in catchment_layers.items()},
    }
    return catchment_layers, catchment_summary, catchments_warning


def fetch_arcgis_geojson(base_url: str, where: str = "1=1", out_fields: str = "*"):
    if not base_url:
        raise ValueError("ArcGIS URL is required.")

    url = base_url.strip()
    if not url.lower().endswith("/query"):
        url = url.rstrip("/") + "/query"

    params = {
        "where": where or "1=1",
        "outFields": out_fields or "*",
        "f": "geojson",
    }
    separator = "&" if "?" in url else "?"
    request_url = f"{url}{separator}{urlencode(params)}"

    with urlopen(request_url) as response:
        data = json.load(response)

    if "error" in data:
        message = data["error"].get("message") or "Unknown ArcGIS error"
        raise ValueError(f"ArcGIS query failed: {message}")
    return data


def list_arcgis_layers(directory: Path | None):
    if not directory or not directory.exists():
        return []
    layers = []
    for path in sorted(directory.glob("*.geojson")):
        layers.append(
            {
                "name": path.stem,
                "path": path,
            }
        )
    return layers


def load_school_data(schools_path: Path):
    schools_geojson = None
    schools_warning = None
    schools_summary = None
    ranking_warning = None

    if not schools_path:
        schools_warning = (
            f"Schools data not found: {schools_path}. "
            "Run `python scripts/prep_geojson.py --schools`."
        )
    if schools_path.exists():
        try:
            schools_geojson = _load_geojson_file(schools_path)
            features = schools_geojson.get("features", [])
            _ensure_stage(features)

            sectors = {}
            remote_counts = {}
            stage_counts = {"primary": 0, "secondary": 0, "combined": 0, "other": 0}
            ranking_values_present = False

            for feature in features:
                props = feature.get("properties") or {}
                sector = str(props.get("sector", "")).strip()
                if sector:
                    sectors[sector] = sectors.get(sector, 0) + 1
                remote = str(props.get("remotearea", "")).strip()
                if remote:
                    remote_counts[remote] = remote_counts.get(remote, 0) + 1
                stage = (props.get("stage") or "other").lower()
                if stage in stage_counts:
                    stage_counts[stage] += 1
                if props.get("ranking_rank") is not None:
                    ranking_values_present = True

            schools_summary = {
                "count": int(len(features)),
                "sector_counts": sectors,
                "remote_counts": remote_counts,
                "stage_counts": stage_counts,
            }

            if not ranking_values_present:
                ranking_warning = (
                    "Ranking attributes missing from processed schools GeoJSON. "
                    "Re-run `python scripts/prep_geojson.py --schools` after "
                    "including the ranking XML."
                )
        except Exception as exc:  # pragma: no cover
            schools_warning = f"Failed to load schools data: {exc}"
    return schools_geojson, schools_warning, schools_summary, ranking_warning


def get_map_center(meta, state):
    if state:
        if center := STATES_CAPITALS.get(state):
            return center
        elif center := meta.get("state_centers", {}).get(state):
            return center
    bounds = meta.get("total_bounds")
    if bounds:
        minx, miny, maxx, maxy = bounds
        return [(miny + maxy) / 2, (minx + maxx) / 2]
    return [-25.2744, 133.7751]  # fallback to center of Australia


def _interpolate_color(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def _rgb_to_hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _color_for_irad_decile(decile, irad_range):
    if decile is None or irad_range is None:
        return "#b0bec5"  # muted grey for missing values

    try:
        decile = int(decile)
    except (TypeError, ValueError):
        return "#b0bec5"

    min_decile, max_decile = irad_range
    if min_decile == max_decile:
        position = 0.5
    else:
        position = (decile - min_decile) / (max_decile - min_decile)
        position = max(0.0, min(1.0, position))

    red = (215, 48, 39)
    yellow = (254, 224, 139)
    green = (26, 152, 80)

    if position <= 0.5:
        local_t = position / 0.5 if position else 0.0
        rgb = _interpolate_color(red, yellow, local_t)
    else:
        local_t = (position - 0.5) / 0.5
        rgb = _interpolate_color(yellow, green, local_t)
    return _rgb_to_hex(rgb)


def make_sa1_style(irad_range):
    def style(feature):
        props = feature.get("properties") or {}
        irad_decile = props.get("IRAD_decile")
        color = _color_for_irad_decile(irad_decile, irad_range)
        return {
            "fillColor": color,
            "color": color,
            "weight": 1,
            "fillOpacity": 0.45,
        }

    return style


def _load_seifa_table(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"SEIFA data not found: {path}")
    df = pd.read_csv(path)
    df = df.rename(columns=SEIFA_COLUMN_RENAMES)
    needed_cols = ["SA1_CODE21"] + [
        col for col in SEIFA_COLUMN_RENAMES.values() if col != "SA1_CODE21"
    ]
    available_cols = [col for col in needed_cols if col in df.columns]
    missing = sorted(set(needed_cols) - set(available_cols))
    if missing:
        print("Warning: missing SEIFA columns in " f"{path.name}: {', '.join(missing)}")
    df = df[available_cols]
    df = df.dropna(subset=["SA1_CODE21"])
    df["SA1_CODE21"] = df["SA1_CODE21"].astype(str).str.strip()

    numeric_cols = [col for col in df.columns if col != "SA1_CODE21"]
    df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors="coerce")

    df = df[~df["SA1_CODE21"].str.contains("Table", na=False)]
    df = df[df["SA1_CODE21"].str.len() >= 5]
    return df


def filter_geojson(data, predicate):
    if predicate is None or not data:
        return data

    features = data.get("features", [])
    filtered = [feat for feat in features if predicate(feat)]

    # Copy top-level dict without mutating cache.
    filtered_data = {**data, "features": filtered}
    return filtered_data


def build_tooltip_fields(property_names, extra_fields=None):
    def add_field(field, alias, results):
        if field in property_names:
            results.append((field, alias))

    picks = []
    add_field("SA1_NAME21", "SA1:", picks)
    add_field("SA2_NAME21", "SA2:", picks)
    add_field("SA3_NAME21", "SA3:", picks)
    add_field("STE_NAME21", "State:", picks)

    if extra_fields:
        for field in extra_fields:
            if any(field.endswith(suffix) for suffix in SCORE_SUFFIXES):
                continue
            alias = SEIFA_DISPLAY_NAMES.get(field, field + ":")
            add_field(field, f"{alias}:", picks)

    if not picks:
        # Fall back to whatever attributes exist, or an empty placeholder.
        if property_names:
            fallback_field = property_names[0]
            picks.append((fallback_field, fallback_field + ":"))
        else:
            picks.append(("SA1_CODE21", "SA1 code:"))

    fields = [field for field, _ in picks]
    aliases = [alias for _, alias in picks]
    return fields, aliases


SEIFA_DISPLAY_NAMES = {
    "IRSD_score": "IRSD score",
    "IRSD_decile": "IRSD decile",
    "IRAD_score": "IRAD score",
    "IRAD_decile": "IRAD decile",
    "IER_score": "IER score",
    "IER_decile": "IER decile",
    "IEO_score": "IEO score",
    "IEO_decile": "IEO decile",
    "URP": "URP",
}


SCORE_SUFFIXES = ("_score", "_Score")
