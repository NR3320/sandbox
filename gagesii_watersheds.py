"""Split GAGES-II watershed polygons into one closed shapefile per USGS gage.

Each watershed is written to its own folder so ArcGIS sees a single shapefile
and the parent directory sorts cleanly by gage ID:

    approved_gage_watershed_boundaries/
        data_01011000/
            boundary_01011000.shp
            boundary_01011000.shx
            boundary_01011000.dbf
            boundary_01011000.prj
            boundary_01011000.cpg

Run with the geo conda environment:

    conda activate geo
    python gagesii_watersheds.py
"""

from __future__ import annotations

from pathlib import Path

import fiona
from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.geometry.polygon import orient

SOURCE_SHP = Path(
    r"G:\Shared drives\Signatures -- large scale\baseflow\RAraki\data"
    r"\GAGES2\GAGES_II_Geospa\all_gages2_polygons.shp"
)
OUTPUT_DIR = Path(
    r"C:\Users\flipl\OneDrive - Cal Poly\NR3320_share\2026F"
    r"\approved_gage_watershed_boundaries"
)
GAGE_ID_FIELD = "GAGE_ID"
MIN_GAGE_ID_DIGITS = 8
SHAPEFILE_SCHEMA = {
    "geometry": "Polygon",
    "properties": {
        "AREA": "float:24.15",
        "PERIMETER": "float:24.15",
        "GAGE_ID": "str:80",
    },
}


def format_gage_id(value: object) -> str:
    """Return a USGS gage ID with at least 8 digits (keep longer IDs as-is)."""
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    if text.isdigit():
        return text.zfill(MIN_GAGE_ID_DIGITS)
    return text


def close_ring(coords) -> list[tuple[float, float]]:
    """Return a 2D ring whose first and last vertices are identical."""
    ring = [(float(x), float(y)) for x, y, *_ in coords]
    if ring and ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring


def close_polygon(geom):
    """Close every exterior and interior ring; keep a valid polygonal geometry."""
    if geom is None or geom.is_empty:
        return geom

    geom_type = geom.geom_type
    if geom_type == "Polygon":
        closed = Polygon(
            close_ring(geom.exterior.coords),
            [close_ring(ring.coords) for ring in geom.interiors],
        )
        if not closed.is_valid:
            closed = closed.buffer(0)
        if closed.geom_type == "Polygon":
            closed = orient(closed, sign=1.0)
        elif closed.geom_type == "MultiPolygon":
            closed = close_polygon(closed)
        return closed

    if geom_type == "MultiPolygon":
        parts = [close_polygon(part) for part in geom.geoms]
        parts = [part for part in parts if part is not None and not part.is_empty]
        if not parts:
            return geom
        if len(parts) == 1:
            return parts[0]
        return MultiPolygon(parts)

    return geom


def rings_are_closed(geom) -> bool:
    if geom is None or geom.is_empty:
        return False
    parts = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
    for part in parts:
        if part.geom_type != "Polygon":
            return False
        rings = [part.exterior, *part.interiors]
        for ring in rings:
            coords = list(ring.coords)
            if len(coords) < 4 or coords[0] != coords[-1]:
                return False
    return True


def shapefile_properties(props: dict, gage_id: str) -> dict:
    area = props.get("AREA")
    perimeter = props.get("PERIMETER")
    return {
        "AREA": None if area is None else float(area),
        "PERIMETER": None if perimeter is None else float(perimeter),
        "GAGE_ID": gage_id,
    }


def write_shapefile(shp_path: Path, geom, properties: dict, crs) -> None:
    """Write one closed polygon as an ArcGIS-readable shapefile."""
    schema = dict(SHAPEFILE_SCHEMA)
    if geom.geom_type == "MultiPolygon":
        schema["geometry"] = "MultiPolygon"

    shp_path.parent.mkdir(parents=True, exist_ok=True)
    with fiona.open(
        shp_path,
        mode="w",
        driver="ESRI Shapefile",
        crs=crs,
        schema=schema,
        encoding="utf-8",
    ) as dst:
        dst.write(
            {
                "geometry": mapping(geom),
                "properties": properties,
            }
        )


def main() -> None:
    if not SOURCE_SHP.exists():
        raise FileNotFoundError(f"Source shapefile not found: {SOURCE_SHP}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    n_written = 0
    n_skipped = 0
    n_existing = 0
    used_names: dict[str, int] = {}

    with fiona.open(SOURCE_SHP) as src:
        n_features = len(src)
        print(f"Reading {n_features} watersheds from {SOURCE_SHP}")
        print(f"Writing closed shapefiles to {OUTPUT_DIR}")

        for i, feature in enumerate(src, start=1):
            props = dict(feature["properties"])
            gage_id = format_gage_id(props.get(GAGE_ID_FIELD, ""))
            if not gage_id or gage_id.lower() in {"none", "nan"}:
                n_skipped += 1
                print(f"  Skipping feature {i}: missing {GAGE_ID_FIELD}")
                continue

            stem = f"boundary_{gage_id}"
            if stem in used_names:
                used_names[stem] += 1
                stem = f"{stem}_{used_names[stem]}"
            else:
                used_names[stem] = 0

            gage_dir = OUTPUT_DIR / f"data_{gage_id}"
            shp_path = gage_dir / f"{stem}.shp"
            if shp_path.exists():
                n_existing += 1
                if i % 100 == 0 or i == n_features:
                    print(
                        f"  {i}/{n_features} processed, "
                        f"{n_written} written, {n_existing} already present"
                    )
                continue

            geom = close_polygon(shape(feature["geometry"]))
            if geom is None or geom.is_empty or not rings_are_closed(geom):
                n_skipped += 1
                print(f"  Skipping {gage_id}: geometry is empty or could not be closed")
                continue

            write_shapefile(
                shp_path,
                geom,
                shapefile_properties(props, gage_id),
                src.crs,
            )
            n_written += 1

            if i % 100 == 0 or i == n_features:
                print(
                    f"  {i}/{n_features} processed, "
                    f"{n_written} written, {n_existing} already present"
                )

    print(
        f"Done. Wrote {n_written} shapefiles, "
        f"skipped {n_skipped}, already present {n_existing}."
    )


if __name__ == "__main__":
    main()
