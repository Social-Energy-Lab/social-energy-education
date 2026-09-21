"""Convert a spreadsheet to readable markdown, for the private context library.

Source documents reach the context library as markdown so that agents can read them. This
handles the .xlsx ones; `markitdown` handles the rest. It writes to stdout and never reads or
writes anything in this repo: send the output to $SOCIAL_ENERGY_DATA, never here.

    uv run --with openpyxl python scripts/xlsx2md.py <workbook.xlsx> "<title>" \\
        > "$SOCIAL_ENERGY_DATA/<study-id>/context/personal/<name>.md"
"""

import sys

import openpyxl


def cell(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip().replace("|", "\\|").replace("\n", " ")


wb = openpyxl.load_workbook(sys.argv[1], data_only=True)
out = [f"# {sys.argv[2]}", ""]
for ws in wb.worksheets:
    # A merged range repeats its value across the span; keep only the top-left cell.
    merged = {
        (r, c)
        for rng in ws.merged_cells.ranges
        for r in range(rng.min_row, rng.max_row + 1)
        for c in range(rng.min_col, rng.max_col + 1)
        if (r, c) != (rng.min_row, rng.min_col)
    }
    rows = []
    for ri, row in enumerate(ws.iter_rows(max_col=30, values_only=False), start=1):
        values = [None if (ri, ci) in merged else c.value for ci, c in enumerate(row, start=1)]
        # Some header rows repeat one sentence across the whole span; keep the first cell.
        filled = [v for v in values if v is not None and str(v).strip()]
        if len(filled) > 2 and len(set(map(str, filled))) == 1:
            values = [values[next(i for i, v in enumerate(values) if v is not None)]]
        if filled:
            rows.append(values)
    if not rows:
        continue
    width = max(i + 1 for r in rows for i, v in enumerate(r) if v is not None and str(v).strip())
    out += [f"## {ws.title}", "", f"_{len(rows) - 1} data rows, {width} columns._", ""]
    header = [cell(v) or f"col{i}" for i, v in enumerate(rows[0][:width])]
    out += ["| " + " | ".join(header) + " |", "|" + "---|" * width]
    out += [
        "| " + " | ".join(cell(v) for v in (list(r[:width]) + [None] * width)[:width]) + " |"
        for r in rows[1:]
    ]
    out.append("")
sys.stdout.write("\n".join(out) + "\n")
