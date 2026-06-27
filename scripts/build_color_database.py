#!/usr/bin/env python3
"""Build color_database.json from BrickLink Studio's CustomColorDefinition.txt.

Run this once or twice a year after updating BrickLink Studio, then run
seed_colors.py to push the new colors into the database.

Workflow:
  1. Install / update BrickLink Studio (https://www.bricklink.com/v3/studio/download.page)
  2. Copy CustomColorDefinition.txt from the Studio data directory, e.g.:
       Linux:   ~/.local/share/BrickLink/Studio/CustomColorDefinition.txt
       macOS:   ~/Library/Application Support/BrickLink/Studio/CustomColorDefinition.txt
       Windows: %APPDATA%\\BrickLink\\Studio\\CustomColorDefinition.txt
  3. Run:
       python scripts/build_color_database.py [path/to/CustomColorDefinition.txt]
  4. Run:
       python scripts/seed_colors.py

Output defaults to: ../brick_palettes_generator/data/color_database.json
"""
import json
import sys
from pathlib import Path

DEFAULT_INPUT = Path.home() / ".local/share/BrickLink/Studio/CustomColorDefinition.txt"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[2] / "brick_palettes_generator/data/color_database.json"


def safe_int(value: str) -> int | None:
    value = str(value).strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def build_color_database(input_path: Path, output_path: Path) -> None:
    if not input_path.exists():
        print(f"ERROR: {input_path} not found", file=sys.stderr)
        print("See script docstring for where to find CustomColorDefinition.txt", file=sys.stderr)
        sys.exit(1)

    print(f"Loading Studio color definitions from: {input_path}")

    color_database: dict = {
        "studio": {},
        "bricklink": {},
        "ldraw": {},
        "lego": {},
        "studio_variants": {},
    }

    with open(input_path, encoding="utf-8", errors="ignore") as f:
        next(f)  # skip header row

        for line in f:
            line = line.strip()
            if not line:
                continue

            # Tab-delimited columns:
            # 0 Studio Color Code
            # 1 BL Color Code
            # 2 LDraw Color Code
            # 3 LDD Color Code
            # 4 Studio Color Name
            # 5 BL Color Name
            # 6 LDraw Color Name
            # 7 LDD Color Name
            parts = line.split("\t")
            if len(parts) < 8:
                continue

            studio_color_id = safe_int(parts[0])
            bricklink_color_id = safe_int(parts[1])
            ldraw_color_id = safe_int(parts[2])
            lego_color_id = safe_int(parts[3])
            studio_name = parts[4].strip()
            bricklink_name = parts[5].strip()
            ldraw_name = parts[6].strip()
            lego_name = parts[7].strip()

            entry = {
                "studio":    {"id": studio_color_id,    "name": studio_name},
                "bricklink": {"id": bricklink_color_id, "name": bricklink_name},
                "ldraw":     {"id": ldraw_color_id,     "name": ldraw_name},
                "lego":      {"id": lego_color_id,      "name": lego_name},
            }

            if studio_color_id is not None:
                color_database["studio"][str(studio_color_id)] = entry

            # BrickLink index: keep FIRST occurrence only — later entries are
            # material variants (Rubber, Chrome, Pearl, Glitter, Metallic) that
            # should not overwrite the canonical solid color.
            if bricklink_color_id is not None:
                bl_key = str(bricklink_color_id)
                if bl_key not in color_database["bricklink"]:
                    color_database["bricklink"][bl_key] = entry

            if ldraw_color_id is not None:
                ldraw_key = str(ldraw_color_id)
                if ldraw_key not in color_database["ldraw"]:
                    color_database["ldraw"][ldraw_key] = entry

            if lego_color_id is not None:
                lego_key = str(lego_color_id)
                if lego_key not in color_database["lego"]:
                    color_database["lego"][lego_key] = entry

            # All Studio variants (Rubber, Chrome, Pearl, etc.) indexed by
            # a compound key so no canonical entry is lost.
            if bricklink_color_id is not None and studio_color_id is not None:
                variant_key = f"{bricklink_color_id}_{studio_color_id}"
                color_database["studio_variants"][variant_key] = entry

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(color_database, f, indent=2, sort_keys=True)

    print(f"\nSaved: {output_path}")
    print(f"  Studio colors:    {len(color_database['studio'])}")
    print(f"  BrickLink colors: {len(color_database['bricklink'])}")
    print(f"  LDraw colors:     {len(color_database['ldraw'])}")
    print(f"  LEGO colors:      {len(color_database['lego'])}")
    print(f"  Studio variants:  {len(color_database['studio_variants'])}")
    print("\nNext: python scripts/seed_colors.py")


if __name__ == "__main__":
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INPUT
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUTPUT
    build_color_database(input_path, output_path)
