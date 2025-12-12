#!/usr/bin/env python3
"""
Preprocess spatial datasets into GeoJSON files for faster runtime loading.

Usage:
    python scripts/prep_geojson.py            # converts all datasets
    python scripts/prep_geojson.py --sa1      # just SA1 + SEIFA merge
    python scripts/prep_geojson.py --sa1 --state "Western Australia"
                                          # SA1 filtered by STE_NAME21
    python scripts/prep_geojson.py --transit  # just transit services
    python scripts/prep_geojson.py --schools  # just school locations
"""

from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

import geopandas as gpd
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]

SA1_SHP = (
    REPO_ROOT / "data/SocioEconomic/SA1_2021_AUST_SHP_GDA2020/SA1_2021_AUST_GDA2020.shp"
)
SEIFA_XLS = (
    REPO_ROOT / "data/SocioEconomic/Statistical Area Level 1, Indexes, SEIFA 2021.xlsx"
)
TRANSIT_SHP = REPO_ROOT / "data/Transit/Spatial_Data/Services/Services.shp"
SCHOOLS_SHP = (
    REPO_ROOT
    / "data/School/Current_Active_Schools_Sem_1_2019_Public_DET_017_WA_GDA2020_Public_Shapefile/School/Current_Active_Schools_Sem_1_2019_Public_DET_017.shp"
)
SCHOOL_RANKING_XML = REPO_ROOT / "data/School/school_ranking.xml"
CATCHMENTS_ROOT = REPO_ROOT / "data/School/gh-schools"
PRIMARY_CATCHMENTS_SHP = CATCHMENTS_ROOT / "PrimarySchool/PrimarySchoolCatchments.shp"
HIGH_CATCHMENTS_SHP = CATCHMENTS_ROOT / "HighSchool/HighSchoolCatchments.shp"

OUTPUT_DIR = REPO_ROOT / "data/processed"
SA1_OUT = OUTPUT_DIR / "sa1_2021.geojson"
TRANSIT_OUT = OUTPUT_DIR / "transit_services.geojson"
SCHOOLS_OUT = OUTPUT_DIR / "schools_2019.geojson"
CATCHMENTS_OUT = OUTPUT_DIR / "school_catchments.geojson"
ARCGIS_OUT = OUTPUT_DIR / "arcgis_layers"


def _flatten_excel_columns(columns):
    flattened = []
    for idx, col in enumerate(columns):
        if isinstance(col, tuple):
            parts = [
                str(part).strip()
                for part in col
                if part and not str(part).startswith("Unnamed")
            ]
            name = " ".join(parts).strip()
        else:
            name = str(col).strip()
        if not name:
            name = f"column_{idx}"
        flattened.append(name)
    return flattened


def _load_seifa_table(path: Path):
    df = pd.read_excel(
        path,
        sheet_name="Table 1",
        header=[4, 5],
        engine="openpyxl",
    )
    df.columns = _flatten_excel_columns(df.columns)
    needed_cols = [
        "2021 Statistical Area Level 1 (SA1)",
        "Index of Relative Socio-economic Disadvantage Score",
        "Index of Relative Socio-economic Disadvantage Decile",
        "Index of Relative Socio-economic Advantage and Disadvantage Score",
        "Index of Relative Socio-economic Advantage and Disadvantage Decile",
        "Index of Economic Resources Score",
        "Index of Economic Resources Decile",
        "Index of Education and Occupation Score",
        "Index of Education and Occupation Decile",
        "Usual Resident Population",
    ]
    rename_map = {
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
    available_cols = [col for col in needed_cols if col in df.columns]
    missing = sorted(set(needed_cols) - set(available_cols))
    if missing:
        print(
            f"Warning: missing SEIFA columns {missing}. Continuing with available columns."
        )
    df = df.loc[:, available_cols].rename(columns=rename_map)
    df = df.dropna(subset=["SA1_CODE21"])
    df["SA1_CODE21"] = df["SA1_CODE21"].astype(str).str.strip()
    numeric_cols = [col for col in df.columns if col != "SA1_CODE21"]
    df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors="coerce")
    df = df[~df["SA1_CODE21"].str.contains("Table", na=False)]
    return df


def _compute_school_stage(low_year: str, high_year: str):
    low = (low_year or "").upper()
    high = (high_year or "").upper()

    def year_to_int(val: str | None):
        if val and val.startswith("Y") and len(val) >= 3:
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


def _normalize_school_name(name: str | None) -> str:
    if not name:
        return ""
    base = name.split(",")[0]
    base = re.sub(r"\.*(?>\(.*$)", " ", base).strip().upper()
    return base


def _levenshtein_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur.append(min(cur[-1] + 1, prev[j] + 1, prev[j - 1] + cost))
        prev = cur
    return prev[-1]


def _find_best_ranking_match(
    name_key: str, ranking_data: dict[str, dict], max_ratio=0.25
):
    if not name_key:
        return None, None
    if name_key in ranking_data:
        return ranking_data[name_key], name_key
    best_entry = None
    best_ratio = None
    best_candidate = None
    for candidate, entry in ranking_data.items():
        distance = _levenshtein_distance(name_key, candidate)
        longest = max(len(name_key), len(candidate)) or 1
        ratio = distance / longest
        if best_ratio is None or ratio < best_ratio:
            best_ratio = ratio
            best_entry = entry
            best_candidate = candidate
    if best_ratio is not None and best_ratio <= max_ratio:
        return best_entry, best_candidate
    return None, None


def load_school_rankings(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Ranking XML not found: {path}")
    text = path.read_text(encoding="utf-8")
    wrapper = f"<root>{text}</root>"
    root = ET.fromstring(wrapper)
    rankings = {}
    for tr in root.findall(".//tr"):
        cells = ["".join(td.itertext()).strip() for td in tr.findall("td")]
        if not cells or len(cells) < 5:
            continue
        try:
            rank = int(cells[0])
        except ValueError:
            continue
        name = cells[1]
        if not name:
            continue
        locality = cells[2] if len(cells) > 2 else ""
        overall = cells[3] if len(cells) > 3 else ""
        percentile = cells[4] if len(cells) > 4 else ""
        enrolments = cells[7] if len(cells) > 7 else ""
        sector = cells[9] if len(cells) > 9 else ""
        icsea = cells[10] if len(cells) > 10 else ""

        def to_int(value):
            try:
                return int(value.replace("%", "").strip())
            except Exception:
                return None

        key = _normalize_school_name(name)
        rankings[key] = {
            "ranking_rank": rank,
            "ranking_locality": locality,
            "ranking_score": to_int(overall),
            "ranking_percentile": percentile,
            "ranking_enrolments": to_int(enrolments),
            "ranking_sector": sector,
            "ranking_icsea": to_int(icsea),
        }
    return rankings


def _merge_school_rankings(gdf: gpd.GeoDataFrame):
    ranking_fields = [
        "ranking_rank",
        "ranking_locality",
        "ranking_score",
        "ranking_percentile",
        "ranking_enrolments",
        "ranking_sector",
        "ranking_icsea",
        "matched_key",
    ]

    for field in ranking_fields:
        if field not in gdf.columns:
            gdf[field] = None

    if not SCHOOL_RANKING_XML.exists():
        print(f"Warning: school ranking XML not found at {SCHOOL_RANKING_XML}.")
        return

    try:
        ranking_data = load_school_rankings(SCHOOL_RANKING_XML)
    except Exception as exc:
        print(f"Warning: failed to parse ranking XML: {exc}")
        return

    matched = 0
    for idx, row in gdf.iterrows():
        key = _normalize_school_name(row.get("schoolname"))
        entry, matched_name = _find_best_ranking_match(key, ranking_data)
        if entry:
            matched += 1
            for field, value in entry.items():
                gdf.at[idx, field] = value
            gdf.at[idx, "matched_key"] = matched_name
    print(f"Attached ranking metadata to {matched} of {len(gdf)} schools.")


def _load_catchment_layer(path: Path, level: str):
    if not path.exists():
        raise FileNotFoundError(path)
    gdf = gpd.read_file(path).to_crs(epsg=4326)
    rename_map = {
        "School": "schoolname",
        "Type": "catchment_type",
        "Notes": "catchment_notes",
        "Score": "catchment_score",
        "ScoreStrat": "catchment_score_strat",
    }
    existing = {k: v for k, v in rename_map.items() if k in gdf.columns}
    gdf = gdf.rename(columns=existing)
    if "schoolname" not in gdf.columns:
        raise ValueError(f"'School' column missing from {path.name}")
    gdf["catchment_level"] = level
    gdf["school_key"] = gdf["schoolname"].apply(_normalize_school_name)
    for col in [
        "catchment_type",
        "catchment_notes",
        "catchment_score",
        "catchment_score_strat",
    ]:
        if col not in gdf.columns:
            gdf[col] = None
    keep_cols = [
        "schoolname",
        "catchment_type",
        "catchment_level",
        "catchment_notes",
        "catchment_score",
        "catchment_score_strat",
        "school_key",
        "geometry",
    ]
    return gdf[keep_cols]


def convert_sa1(ste_names: list[str] | None = None):
    if not SA1_SHP.exists():
        raise FileNotFoundError(f"SA1 shapefile missing: {SA1_SHP}")
    if not SEIFA_XLS.exists():
        raise FileNotFoundError(f"SEIFA workbook missing: {SEIFA_XLS}")

    print("Converting SA1 shapefile to GeoJSON...")
    gdf = gpd.read_file(SA1_SHP)

    if ste_names:
        if "STE_NAME21" not in gdf.columns:
            raise ValueError(
                "STE_NAME21 column missing from SA1 dataset; cannot filter by state."
            )
        normalized = sorted(
            {name.strip().lower() for name in ste_names if name and name.strip()}
        )
        if normalized:
            gdf = gdf[
                gdf["STE_NAME21"].astype(str).str.strip().str.lower().isin(normalized)
            ]
            print(
                "  Filtered SA1 polygons by STE_NAME21, keeping "
                f"{len(gdf)} matching rows."
            )
            if gdf.empty:
                print(
                    "  Warning: STE_NAME21 filter returned no rows. "
                    "Check the provided values."
                )

    seifa_df = _load_seifa_table(SEIFA_XLS)
    gdf = gdf.merge(seifa_df, on="SA1_CODE21", how="left")
    # Drop LOCI URI metadata – it is large, unused, and bloats the GeoJSON.
    gdf = gdf.drop(
        columns=[
            "CHG_FLAG21",
            "CHG_LBL21",
            "SA2_CODE21",
            "SA3_CODE21",
            "SA4_CODE21",
            "GCC_CODE21",
            "STE_CODE21",
            "AUS_CODE21",
            "AREASQKM21",
            "LOCI_URI21",
            "AUS_NAME21"
            "SA4_NAME21",
            "GCC_NAME21"
        ],
        errors="ignore",
    )
    gdf = gdf.to_crs(epsg=4326)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    gdf.to_file(SA1_OUT, driver="GeoJSON")
    print(f"Saved SA1 GeoJSON to {SA1_OUT}")


def convert_transit():
    if not TRANSIT_SHP.exists():
        raise FileNotFoundError(f"Transit shapefile missing: {TRANSIT_SHP}")
    print("Converting transit services shapefile to GeoJSON...")
    gdf = gpd.read_file(TRANSIT_SHP).to_crs(epsg=4326)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    gdf.to_file(TRANSIT_OUT, driver="GeoJSON")
    print(f"Saved transit GeoJSON to {TRANSIT_OUT}")


def convert_schools():
    if not SCHOOLS_SHP.exists():
        raise FileNotFoundError(f"Schools shapefile missing: {SCHOOLS_SHP}")
    print("Converting schools shapefile to GeoJSON...")
    gdf = gpd.read_file(SCHOOLS_SHP).to_crs(epsg=4326)
    if "lowyear" in gdf.columns and "highyear" in gdf.columns:
        gdf["stage"] = gdf.apply(
            lambda row: _compute_school_stage(row.get("lowyear"), row.get("highyear")),
            axis=1,
        )
    else:
        gdf["stage"] = "other"

    _merge_school_rankings(gdf)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    gdf.to_file(SCHOOLS_OUT, driver="GeoJSON")
    print(f"Saved schools GeoJSON to {SCHOOLS_OUT}")


def convert_catchments():
    missing = [
        path
        for path in [PRIMARY_CATCHMENTS_SHP, HIGH_CATCHMENTS_SHP]
        if not path.exists()
    ]
    if missing:
        missing_str = ", ".join(str(p) for p in missing)
        raise FileNotFoundError(f"Catchment shapefile(s) missing: {missing_str}")

    print("Merging primary and high school catchment polygons...")
    primary = _load_catchment_layer(PRIMARY_CATCHMENTS_SHP, "primary")
    high = _load_catchment_layer(HIGH_CATCHMENTS_SHP, "high")
    catchments = pd.concat([primary, high], ignore_index=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    catchments.to_file(CATCHMENTS_OUT, driver="GeoJSON")
    print(f"Saved school catchments GeoJSON to {CATCHMENTS_OUT}")


def _download_arcgis_layer(url: str, where: str = "1=1", out_fields: str = "*"):
    if not url:
        raise ValueError("ArcGIS FeatureServer URL is required.")
    base = url.strip()
    if not base.lower().endswith("/query"):
        base = base.rstrip("/") + "/query"
    params = {"where": where or "1=1", "outFields": out_fields or "*", "f": "geojson"}
    separator = "&" if "?" in base else "?"
    query_url = f"{base}{separator}{urlencode(params)}"
    with urlopen(query_url) as response:
        data = json.load(response)
    if "error" in data:
        message = data["error"].get("message") or "Unknown ArcGIS error"
        raise RuntimeError(f"ArcGIS download failed: {message}")
    return data


def convert_arcgis_layers(definitions: list[str | dict], out_dir: Path = ARCGIS_OUT):
    if not definitions:
        print("No ArcGIS URLs provided; skipping.")
        return

    def derive_name(entry, index):
        if isinstance(entry, dict) and entry.get("name"):
            return str(entry["name"]).strip()
        url = ""
        if isinstance(entry, dict):
            url = entry.get("url", "")
        elif isinstance(entry, str):
            url = entry
        url = url.strip()
        if not url:
            return f"arcgis_layer_{index}"
        parts = url.rstrip("/").split("/")
        if len(parts) >= 2 and parts[-2].isdigit() is False:
            return parts[-2]
        if parts:
            last = parts[-1]
            if last.isdigit():
                return f"arcgis_layer_{last}"
            return last or f"arcgis_layer_{index}"
        return f"arcgis_layer_{index}"

    out_dir.mkdir(parents=True, exist_ok=True)
    for idx, entry in enumerate(definitions, start=1):
        if isinstance(entry, str):
            url = entry
            where = "1=1"
        elif isinstance(entry, dict):
            url = entry.get("url")
            where = entry.get("where", "1=1")
        else:
            continue
        if not url:
            print(f"Skipping ArcGIS layer #{idx}: missing URL.")
            continue
        layer_name = derive_name(entry, idx)
        safe_name = (
            re.sub(r"[^A-Za-z0-9_.-]+", "_", layer_name) or f"arcgis_layer_{idx}"
        )
        print(f"Downloading ArcGIS layer #{idx} ({safe_name}) from {url} ...")
        try:
            geojson = _download_arcgis_layer(url, where=where)
        except Exception as exc:
            print(f"  Failed: {exc}")
            continue
        out_path = out_dir / f"{safe_name}.geojson"
        out_path.write_text(json.dumps(geojson), encoding="utf-8")
        print(f"  Saved to {out_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Convert shapefiles into GeoJSON for faster runtime loading."
    )
    parser.add_argument(
        "--sa1",
        action="store_true",
        help="Convert SA1 + SEIFA shapefile to GeoJSON.",
    )
    parser.add_argument(
        "--state",
        action="append",
        dest="states",
        metavar="STE_NAME21",
        help=(
            "Filter SA1 polygons to matching STE_NAME21 values. "
            "Repeat for multiple states."
        ),
    )
    parser.add_argument(
        "--transit",
        action="store_true",
        help="Convert transit services shapefile to GeoJSON.",
    )
    parser.add_argument(
        "--schools",
        action="store_true",
        help="Convert schools shapefile to GeoJSON.",
    )
    parser.add_argument(
        "--catchments",
        action="store_true",
        help="Convert public school catchment shapefiles to GeoJSON.",
    )
    parser.add_argument(
        "--arcgis-url",
        action="append",
        help="ArcGIS FeatureServer base URL to export as GeoJSON (can specify multiple).",
    )
    args = parser.parse_args()

    if not any(
        [args.sa1, args.transit, args.schools, args.catchments, args.arcgis_url]
    ):
        args.sa1 = args.transit = args.schools = args.catchments = True

    if args.sa1:
        convert_sa1(args.states)
    if args.transit:
        convert_transit()
    if args.schools:
        convert_schools()
    if args.catchments:
        convert_catchments()
    if args.arcgis_url:
        convert_arcgis_layers(args.arcgis_url)


if __name__ == "__main__":
    main()
