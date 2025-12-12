from pathlib import Path
import logging
import math
from string import Template
import sys

import folium
import streamlit as st
from streamlit_folium import st_folium
from shapely.geometry import Point, shape


from data_utils import (
    build_tooltip_fields,
    list_arcgis_layers,
    filter_geojson,
    get_map_center,
    geocode_address,
    load_catchment_data,
    load_geojson_path,
    load_sa1_dataset,
    load_school_data,
    load_transit_data,
    make_sa1_style,
    fetch_arcgis_geojson,
)

# Configure logging to output to standard output
logging.basicConfig(
    stream=sys.stdout,  # Sends log output to the terminal/Docker stdout
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

SA1_FILE = Path("assets/sa1_2021.geojson")
SEIFA_FILE = Path(
    "assets/statistical_area_level_1_indexes_seifa_2021_table_1.csv"
)
PTA_LINES_FILE = Path("assets/transit_services.geojson")
SCHOOLS_FILE = Path("assets/schools_2019.geojson")
CATCHMENTS_FILE = Path("assets/school_catchments.geojson")
ARCGIS_LAYERS_DIR = Path("assets/arcgis_layers")

LIA_MAP_URL = Template(
    "https://www.det.wa.edu.au/schoolsonline/school_file_download?schoolID=${SCHOOL_CODE}&fileType=INTAKE_MAP01&yearID=_NA"
)


@st.cache_resource(show_spinner="Bootstrapping datasets...")
def load_map_data(
    path: Path,
    seifa_path: Path | None,
    transit_path: Path | None,
    schools_path: Path | None,
    catchments_path: Path | None,
):
    geojson_data, metadata = load_sa1_dataset(path, seifa_path)
    transit_layers, transit_warning = load_transit_data(transit_path)
    schools_geojson, schools_warning, schools_summary, ranking_warning = (
        load_school_data(schools_path)
    )
    catchment_layers, catchment_summary, catchment_warning = load_catchment_data(
        catchments_path
    )

    metadata["transit_warning"] = transit_warning
    metadata["schools_warning"] = schools_warning
    metadata["ranking_warning"] = ranking_warning
    metadata["catchments_warning"] = catchment_warning
    metadata["schools_summary"] = schools_summary
    metadata["catchments_summary"] = catchment_summary
    return geojson_data, transit_layers, schools_geojson, catchment_layers, metadata


# ---------------------------------------------------------
# Config
# ---------------------------------------------------------
st.set_page_config(
    page_title="Suburb Explorer",
    layout="wide",
)


SCHOOL_DETAIL_FIELDS = [
    ("Sector", "sector"),
    ("Stage", "stage"),
    ("Education region", "educationr"),
    ("Rank", "ranking_rank"),
    ("Score", "ranking_score"),
    ("Ranking percentile", "ranking_percentile"),
    ("Enrolments", "totalschoo"),
    ("Address", "physicalst"),
    ("Town", "physicalto"),
    ("Postcode", "physicalpo"),
    ("Low year", "lowyear"),
    ("High year", "highyear"),
    ("Matched Name", "matched_key")
]

SA1_DETAIL_FIELDS = [
    ("SA1 name", "SA1_NAME21"),
    ("SA2 name", "SA2_NAME21"),
    ("SA3 name", "SA3_NAME21"),
    ("State", "STE_NAME21"),
    ("IRSD score", "IRSD_score"),
    ("IRAD score", "IRAD_score"),
    ("IER score", "IER_score"),
    ("IEO score", "IEO_score"),
    ("Usual resident population", "URP"),
]


def _parse_percentile_value(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        cleaned = str(value).replace("%", "").strip()
    except Exception:
        return None
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _format_detail_value(value):
    if value is None:
        return None
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if value.is_integer():
            return str(int(value))
    return str(value)


def _format_school_code(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return str(int(value))
    try:
        numeric = float(str(value).strip())
    except (TypeError, ValueError):
        cleaned = str(value).strip()
        return cleaned or None
    return str(int(numeric))


def _extract_school_from_click(click_info, school_features):
    if not click_info or not school_features:
        return None
    props = (click_info.get("properties") or {}).copy()
    if props.get("schoolname"):
        return props

    lat = click_info.get("lat")
    lon = click_info.get("lng") or click_info.get("lon")
    if (lat is None or lon is None) and isinstance(click_info.get("latlng"), dict):
        lat = lat or click_info["latlng"].get("lat")
        lon = lon or click_info["latlng"].get("lng") or click_info["latlng"].get("lon")
    if lat is None or lon is None:
        return None

    lat = float(lat)
    lon = float(lon)
    tolerance = 1e-5

    for feature in school_features:
        geometry = feature.get("geometry") or {}
        coords = geometry.get("coordinates")
        if not coords or len(coords) < 2:
            continue
        feat_lon, feat_lat = coords[0], coords[1]
        if abs(feat_lat - lat) <= tolerance and abs(feat_lon - lon) <= tolerance:
            return dict(feature.get("properties") or {})
    return None


def _find_sa1_feature_by_code(code, sa1_features):
    if not code:
        return None
    for feature in sa1_features:
        props = feature.get("properties") or {}
        if str(props.get("SA1_CODE21") or "") == str(code):
            return feature
    return None


def _extract_sa1_from_click(click_info, sa1_features):
    if not click_info or not sa1_features:
        return None

    props = (click_info.get("properties") or {}).copy()
    code = props.get("SA1_CODE21")
    if code:
        feature = _find_sa1_feature_by_code(code, sa1_features)
        return feature

    lat = click_info.get("lat")
    lon = click_info.get("lng") or click_info.get("lon")
    if (lat is None or lon is None) and isinstance(click_info.get("latlng"), dict):
        lat = lat or click_info["latlng"].get("lat")
        lon = lon or click_info["latlng"].get("lng") or click_info["latlng"].get("lon")
    if lat is None or lon is None:
        return None

    try:
        point = Point(float(lon), float(lat))
    except Exception:
        return None

    for feature in sa1_features:
        geom = feature.get("geometry")
        if not geom:
            continue
        try:
            geom_shape = shape(geom)
        except Exception:
            continue
        if geom_shape.contains(point):
            return feature
    return None


if "address_pin" not in st.session_state:
    st.session_state["address_pin"] = None
if "selected_school" not in st.session_state:
    st.session_state["selected_school"] = None
if "selected_sa1" not in st.session_state:
    st.session_state["selected_sa1"] = None
if "selected_sa1_code" not in st.session_state:
    st.session_state["selected_sa1_code"] = None
if "arcgis_layers" not in st.session_state:
    st.session_state["arcgis_layers"] = []


@st.cache_data(show_spinner="Geocoding address...")
def cached_geocode(query: str):
    return geocode_address(query)


@st.cache_data(show_spinner="Loading ArcGIS layer...")
def load_arcgis_file(path_str: str):
    return load_geojson_path(Path(path_str))


# ---------------------------------------------------------
# Load data
# ---------------------------------------------------------
try:
    (
        geojson_data,
        transit_layers,
        schools_geojson,
        catchment_layers,
        metadata,
    ) = load_map_data(
        SA1_FILE,
        SEIFA_FILE,
        PTA_LINES_FILE,
        SCHOOLS_FILE,
        CATCHMENTS_FILE,
    )
except FileNotFoundError as exc:
    st.error(str(exc))
    st.stop()
except Exception as exc:  # pragma: no cover - runtime guard
    st.error(f"Failed to load SA1 dataset: {exc}")
    st.stop()

available_arcgis_layers = list_arcgis_layers(ARCGIS_LAYERS_DIR)


# ---------------------------------------------------------
# UI Controls
# ---------------------------------------------------------

states = metadata.get("states", [])
if not states:
    st.warning("No SA1 features were loaded from the shapefile.")
    st.stop()

default_state_index = 0
if "Western Australia" in states:
    default_state_index = states.index("Western Australia")

selected_state = st.sidebar.selectbox(
    "State / Territory",
    options=states,
    index=default_state_index,
)

address_query = st.sidebar.text_input(
    "Enter address",
    placeholder="e.g. 140 William St, Perth",
)


col_search, col_clear = st.sidebar.columns([2, 1])
if col_search.button("Search", use_container_width=True):
    if not address_query:
        st.sidebar.warning("Enter an address to search.")
    else:
        try:
            result = geocode_address(address_query)
        except Exception as exc:
            st.sidebar.error(f"Geocoding failed: {exc}")
        else:
            if result:
                st.session_state["address_pin"] = result
                st.sidebar.success("Address located on the map.")
            else:
                st.sidebar.warning("Address not found.")
school_features = (schools_geojson.get("features") or []) if schools_geojson else []
percentile_slider_default = None
percentile_filter_active = False
selected_percentile_max = None
filtered_school_features = school_features

if school_features:
    percentile_values = []
    for feature in school_features:
        props = feature.get("properties") or {}
        val = _parse_percentile_value(props.get("ranking_percentile"))
        if val is not None:
            percentile_values.append(val)
    if percentile_values:
        percentile_slider_default = min(100, int(max(percentile_values)))
        selected_percentile_max = st.sidebar.slider(
            "Maximum school percentile",
            min_value=0,
            max_value=100,
            value=percentile_slider_default,
            step=1,
        )
        percentile_filter_active = selected_percentile_max < percentile_slider_default
        filtered_school_features = []
        for feature in school_features:
            props = feature.get("properties") or {}
            pct_value = _parse_percentile_value(props.get("ranking_percentile"))
            if pct_value is None and percentile_filter_active:
                continue
            if pct_value is not None and pct_value > selected_percentile_max:
                continue
            filtered_school_features.append(feature)
        if percentile_filter_active and not filtered_school_features:
            st.sidebar.info("No schools fall within the selected percentile range.")
    else:
        st.sidebar.info("Schools are missing percentile rankings; slider disabled.")

st.sidebar.markdown("---")
sa2_options = metadata.get("sa2_by_state", {}).get(selected_state, [])
st.sidebar.success(f"Loaded {metadata.get('count', 0)} SA1 polygons")

seifa_warning = metadata.get("seifa_warning")
seifa_columns = metadata.get("seifa_columns") or []
if seifa_warning:
    st.sidebar.warning(seifa_warning)
elif seifa_columns:
    st.sidebar.success("SEIFA metrics loaded")

if metadata.get("transit_warning"):
    st.sidebar.warning(metadata["transit_warning"])
if metadata.get("schools_warning"):
    st.sidebar.warning(metadata["schools_warning"])
if metadata.get("ranking_warning"):
    st.sidebar.warning(metadata["ranking_warning"])
if metadata.get("catchments_warning"):
    st.sidebar.warning(metadata["catchments_warning"])

st.sidebar.markdown("---")
st.sidebar.subheader("ArcGIS layers")

available_arcgis_options = [layer["name"] for layer in available_arcgis_layers]
initial_arcgis_selected = st.session_state.get("arcgis_selected_files") or []
if available_arcgis_options:
    selected_arcgis_files = st.sidebar.multiselect(
        "Include processed layers",
        options=available_arcgis_options,
        default=[name for name in initial_arcgis_selected if name in available_arcgis_options],
    )
    st.session_state["arcgis_selected_files"] = selected_arcgis_files
else:
    st.sidebar.caption("No preprocessed ArcGIS layers found.")

arcgis_name = st.sidebar.text_input(
    "Layer display name",
    key="arcgis_layer_name",
    placeholder="e.g. City bike paths",
)
arcgis_url = st.sidebar.text_input(
    "ArcGIS FeatureServer URL",
    key="arcgis_layer_url",
    placeholder="https://services.arcgis.com/.../FeatureServer/0",
)
arcgis_where = st.sidebar.text_input(
    "Filter (where clause)",
    value="1=1",
    key="arcgis_layer_where",
)
arcgis_add = st.sidebar.button("Add ArcGIS layer", use_container_width=True)
if arcgis_add:
    if not arcgis_url:
        st.sidebar.error("Provide an ArcGIS FeatureServer URL.")
    else:
        try:
            layer_data = fetch_arcgis_geojson(arcgis_url, where=arcgis_where)
        except Exception as exc:
            st.sidebar.error(f"Failed to load ArcGIS layer: {exc}")
        else:
            name = arcgis_name.strip() if arcgis_name else "ArcGIS layer"
            st.session_state["arcgis_layers"].append(
                {"name": name, "data": layer_data}
            )
            st.sidebar.success(f"Added ArcGIS layer '{name}'.")

if st.session_state["arcgis_layers"]:
    st.sidebar.caption("Temporary ArcGIS layers")
    remove_indices = []
    for idx, layer in enumerate(st.session_state["arcgis_layers"]):
        col_label, col_remove = st.sidebar.columns([4, 1])
        col_label.write(f"{idx + 1}. {layer['name']}")
        if col_remove.button("✕", key=f"remove_arcgis_{idx}"):
            remove_indices.append(idx)
    if remove_indices:
        for idx in sorted(remove_indices, reverse=True):
            st.session_state["arcgis_layers"].pop(idx)
        st.experimental_rerun()

selected_arcgis_file_layers = []
selected_arcgis_names = st.session_state.get("arcgis_selected_files") or []
if selected_arcgis_names:
    name_to_layer = {layer["name"]: layer for layer in available_arcgis_layers}
    for name in selected_arcgis_names:
        layer = name_to_layer.get(name)
        if not layer:
            continue
        try:
            data = load_arcgis_file(str(layer["path"]))
        except Exception as exc:
            st.sidebar.error(f"Failed to load ArcGIS layer '{name}': {exc}")
        else:
            selected_arcgis_file_layers.append({"name": name, "data": data})


def sa1_filter(feature):
    props = feature.get("properties", {})
    state_name = props.get("STE_NAME21", "Unknown")

    if selected_state and state_name != selected_state:
        return False

    return True


# ---------------------------------------------------------
# Main layout
# ---------------------------------------------------------
st.title("Suburb Explorer")

col_map, col_info = st.columns([0.9, 0.1])

with col_map:
    map_center = get_map_center(metadata, selected_state)
    zoom_level = 10 if selected_state else 4

    filtered_geojson = filter_geojson(geojson_data, sa1_filter)
    tooltip_fields, tooltip_aliases = build_tooltip_fields(
        metadata.get("property_names", []),
        metadata.get("seifa_columns"),
    )
    base_style = make_sa1_style(metadata.get("irad_range"))

    selected_feature = st.session_state.get("selected_sa1")
    selected_region_props = selected_feature
    selected_code = st.session_state.get("selected_sa1_code")
    selected_geojson = None
    if selected_code:
        selected_geojson = filter_geojson(
            filtered_geojson,
            lambda feat: str((feat.get("properties") or {}).get("SA1_CODE21") or "")
            == str(selected_code),
        )
        if not selected_geojson.get("features"):
            selected_region_props = None
            selected_geojson = None
            st.session_state["selected_sa1"] = None
            st.session_state["selected_sa1_code"] = None

    m = folium.Map(
        location=map_center,
        zoom_start=zoom_level,
        tiles="CartoDB positron",
        control_scale=True,
    )

    folium.GeoJson(
        filtered_geojson,
        name="SA1 areas",
        style_function=base_style,
        tooltip=folium.GeoJsonTooltip(
            fields=tooltip_fields,
            aliases=tooltip_aliases,
            sticky=True,
        ),
    ).add_to(m)

    if selected_geojson and selected_geojson.get("features"):
        folium.GeoJson(
            selected_geojson,
            name="Selected SA1",
            style_function=lambda _feat: {
                "fillColor": "#ff6b6b",
                "color": "#d62828",
                "weight": 3,
                "fillOpacity": 0.45,
            },
            tooltip=folium.GeoJsonTooltip(
                fields=tooltip_fields,
                aliases=tooltip_aliases,
                sticky=True,
            ),
        ).add_to(m)

    train_lines = transit_layers.get("train")
    bus_lines = transit_layers.get("bus")
    other_lines = transit_layers.get("other") or transit_layers.get("all")

    if train_lines:
        folium.GeoJson(
            train_lines,
            name="PTA metro (train)",
            style_function=lambda _feat: {
                "color": "#003f5c",
                "weight": 4,
                "opacity": 0.9,
            },
        ).add_to(m)

    if bus_lines:
        folium.GeoJson(
            bus_lines,
            name="PTA bus network",
            style_function=lambda _feat: {
                "color": "#ffa600",
                "weight": 2,
                "opacity": 0.8,
            },
        ).add_to(m)

    if other_lines and not (train_lines or bus_lines):
        folium.GeoJson(
            other_lines,
            name="PTA services",
            style_function=lambda _feat: {
                "color": "#3740ff",
                "weight": 3,
                "opacity": 0.8,
            },
        ).add_to(m)

    for idx, custom in enumerate(st.session_state.get("arcgis_layers", [])):
        data = custom.get("data") or {}
        if not data.get("features"):
            continue
        layer_name = custom.get("name") or f"ArcGIS layer {idx + 1}"
        folium.GeoJson(
            data,
            name=layer_name,
            style_function=lambda _feat, idx=idx: {
                "color": "#8f2d56",
                "weight": 2,
                "fillOpacity": 0.2,
            },
        ).add_to(m)

    for layer in selected_arcgis_file_layers:
        data = layer.get("data") or {}
        if not data.get("features"):
            continue
        layer_name = f"ArcGIS (processed) - {layer.get('name')}"
        folium.GeoJson(
            data,
            name=layer_name,
            style_function=lambda _feat: {
                "color": "#8338ec",
                "weight": 2,
                "fillOpacity": 0.2,
            },
        ).add_to(m)

    catchment_color_map = {
        "primary": "#2e7d32",
        "high": "#1565c0",
        "other": "#6d597a",
    }
    catchment_labels = {
        "primary": "Primary school catchment",
        "high": "High school catchment",
        "other": "Other catchment",
    }
    catchment_tooltip_fields = [
        ("schoolname", "School:"),
        ("catchment_level", "Level:"),
        ("catchment_type", "Type:"),
        ("catchment_notes", "Notes:"),
        ("catchment_score", "Score:"),
        ("catchment_score_strat", "Score stratification:"),
    ]

    for level in ("primary", "high", "other"):
        layer_data = catchment_layers.get(level)
        if not layer_data or not layer_data.get("features"):
            continue

        prop_keys = set()
        for feature in layer_data.get("features", []):
            prop_keys.update((feature.get("properties") or {}).keys())

        tooltip_pairs = [
            (field, alias)
            for field, alias in catchment_tooltip_fields
            if field in prop_keys
        ]
        if not tooltip_pairs:
            tooltip_pairs = [("schoolname", "School:")]

        layer_color = catchment_color_map.get(level, "#6d597a")
        layer_name = catchment_labels.get(level, level.title())

        folium.GeoJson(
            layer_data,
            name=layer_name,
            style_function=lambda _feat, color=layer_color: {
                "color": color,
                "weight": 2,
                "fillColor": color,
                "fillOpacity": 0.15,
            },
            tooltip=folium.GeoJsonTooltip(
                fields=[field for field, _ in tooltip_pairs],
                aliases=[alias for _, alias in tooltip_pairs],
                sticky=True,
            ),
        ).add_to(m)

    school_layer_control = folium.FeatureGroup(name="Schools (2019)")
    school_sector_map = {
        "government": "Government",
        "non-government": "Non-Government",
        "community kinder": "Community Kinder",
        "independent pre": "Independent Pre-school",
    }

    if schools_geojson:
        property_keys = set()
        for feature in school_features:
            property_keys.update((feature.get("properties") or {}).keys())

        tooltip_pairs = []

        def add_tooltip_field(field, alias):
            if field in property_keys:
                tooltip_pairs.append((field, alias))

        add_tooltip_field("schoolname", "School:")
        add_tooltip_field("sector", "Sector:")
        add_tooltip_field("ranking_rank", "Rank:")
        add_tooltip_field("ranking_score", "Score:")
        add_tooltip_field("ranking_percentile", "Percentile:")

        def school_style(feature):
            props = feature.get("properties") or {}
            sector = (props.get("sector") or "").lower()
            color = "#2d9cdb"
            if "non" in sector:
                color = "#9b5de5"
            elif "gov" in sector or "government" in sector.lower():
                color = "#2d9cdb"
            return {
                "color": color,
                "weight": 2,
                "fillColor": color,
                "fillOpacity": 0.8,
            }

        if not tooltip_pairs:
            tooltip_pairs = [("schoolname", "School:")]
        school_fields = [field for field, _ in tooltip_pairs]
        school_aliases = [alias for _, alias in tooltip_pairs]

        # Create LayerGroups by sector/stage combination
        sector_stage_groups = {}
        for feature in filtered_school_features:
            props = feature.get("properties") or {}
            sector = (props.get("sector") or "").strip().lower() or "other"
            stage = (props.get("stage") or "other").lower()
            key = (sector, stage)
            sector_stage_groups.setdefault(key, []).append(feature)

        for (sector, stage), features in sector_stage_groups.items():
            human_sector = school_sector_map.get(sector, sector.title())
            human_stage = stage.title()
            layer_name = f"{human_sector} - {human_stage}"
            collection = {"type": "FeatureCollection", "features": features}

            folium.GeoJson(
                collection,
                name=layer_name,
                marker=folium.CircleMarker(radius=4, fill=True),
                style_function=school_style,
                tooltip=folium.GeoJsonTooltip(
                    fields=school_fields,
                    aliases=school_aliases,
                    sticky=True,
                ),
            ).add_to(m)

    address_pin = st.session_state.get("address_pin")
    if address_pin:
        folium.Marker(
            location=[address_pin["lat"], address_pin["lon"]],
            tooltip=address_pin.get("address", "Search location"),
            icon=folium.Icon(color="red", icon="map-marker"),
        ).add_to(m)

    folium.LayerControl().add_to(m)

    map_state = st_folium(
        m,
        width=1000,
        height=750,
        returned_objects=["last_object_clicked"],
    )

    if map_state and map_state.get("last_object_clicked"):
        clicked = map_state["last_object_clicked"]
        props = clicked.get("properties") or clicked
        props = dict(props)
        new_code = str(props.get("SA1_CODE21") or "")
        prev_code = (
            str((selected_feature or {}).get("SA1_CODE21") or "")
            if selected_feature
            else ""
        )

        matched_school = _extract_school_from_click(clicked, filtered_school_features)
        matched_region_feature = None
        if matched_school:
            st.session_state["selected_school"] = matched_school
        else:
            st.session_state["selected_school"] = None

        matched_region_feature = _extract_sa1_from_click(
            clicked, filtered_geojson.get("features", [])
        )
        if matched_region_feature:
            props = dict((matched_region_feature.get("properties") or {}))
            st.session_state["selected_sa1"] = props
            st.session_state["selected_sa1_code"] = str(props.get("SA1_CODE21") or "")
        elif not matched_school:
            st.session_state["selected_sa1"] = None
            st.session_state["selected_sa1_code"] = None


with col_info:
    selected_school = st.session_state.get("selected_school")
    selected_region = st.session_state.get("selected_sa1")
    if selected_school:
        st.markdown(f"**{selected_school.get('schoolname', 'School')}**")
        detail_lines = []
        for label, key in SCHOOL_DETAIL_FIELDS:
            value = _format_detail_value(selected_school.get(key))
            if value:
                detail_lines.append(f"- **{label}:** {value}")
        if detail_lines:
            st.markdown("\n".join(detail_lines))
        lia_url = selected_school.get("lia_map_url")
        if lia_url:
            st.link_button("Download intake map", lia_url, type="primary")
    elif selected_region:
        detail_lines = []
        label = selected_region.get("SA1_NAME21") or selected_region.get("SA2_NAME21")
        if label:
            st.markdown(f"**{label}**")
        for label, key in SA1_DETAIL_FIELDS:
            value = _format_detail_value(selected_region.get(key))
            if value:
                detail_lines.append(f"- **{label}:** {value}")
        if detail_lines:
            st.markdown("\n".join(detail_lines))
    else:
        st.caption("Click a school marker or SA1 polygon to see its details here.")
