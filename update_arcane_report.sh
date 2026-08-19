#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
VENV_DIR="$SCRIPT_DIR/.venv"
WORK_DIR="${TMPDIR:-/tmp}/warframe_arcane_return"
OUTPUT_DIR="$SCRIPT_DIR/outputs/daily_arcane_return"
OUTPUT_FILE="$OUTPUT_DIR/Arcane_Return_Report_Latest.xlsx"

if [ ! -x "$VENV_DIR/bin/python" ]; then
  python3 -m venv "$VENV_DIR"
fi

if ! "$VENV_DIR/bin/python" -c "import openpyxl" >/dev/null 2>&1; then
  "$VENV_DIR/bin/python" -m pip install --disable-pip-version-check -r "$SCRIPT_DIR/requirements.txt"
fi

mkdir -p "$WORK_DIR" "$OUTPUT_DIR"
"$VENV_DIR/bin/python" "$SCRIPT_DIR/warframe_arcane_prices.py" \
  --output "$WORK_DIR/arcane_prices.csv" \
  --summary-output "$WORK_DIR/pack_summary.csv" \
  --json "$WORK_DIR/arcane_data.json" \
  --preview 0
"$VENV_DIR/bin/python" "$SCRIPT_DIR/build_arcane_workbook.py" \
  "$WORK_DIR/arcane_data.json" "$OUTPUT_FILE"

printf 'Update complete: %s\n' "$OUTPUT_FILE"
