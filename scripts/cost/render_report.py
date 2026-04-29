"""Render the cost report from synthetic-month.csv (or real usage_records export).

Reads the CSV produced by ``synthetic_month.py`` (or an export with the
same column shape) and writes a markdown report at the given output
path.

The report covers:
  - Total spend across the month
  - Spend per tenant
  - Spend per model
  - Daily spend trend (sparkline-style table; no chart libs)
  - Top-cost queries (when --requests-csv is supplied; not required)

Run:
    uv run python scripts/cost/render_report.py \\
        --input  scripts/cost/synthetic-month.csv \\
        --output docs/operations/cost-report.md
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


def _load(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _fmt_usd(x: float) -> str:
    return f"${x:,.2f}"


def render(rows: list[dict[str, Any]]) -> str:  # noqa: PLR0915 — straight-line markdown emit
    if not rows:
        return "# Cost report\n\n_No data._\n"

    total = 0.0
    by_tenant: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"cost": 0.0, "requests": 0, "tier": "?", "name": "?"},
    )
    by_model: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"cost": 0.0, "requests": 0, "in_tok": 0, "out_tok": 0},
    )
    by_day: dict[str, float] = defaultdict(float)

    days = set()

    for r in rows:
        cost = float(r["cost_usd"])
        requests = int(r["requests"])
        in_tokens = int(r["input_tokens"])
        out_tokens = int(r["output_tokens"])

        total += cost
        days.add(r["day"])

        t = by_tenant[r["tenant_id"]]
        t["cost"] += cost
        t["requests"] += requests
        t["tier"] = r["tier"]
        t["name"] = r["tenant_name"]

        m = by_model[r["model"]]
        m["cost"] += cost
        m["requests"] += requests
        m["in_tok"] += in_tokens
        m["out_tok"] += out_tokens

        by_day[r["day"]] += cost

    n_days = len(days)
    n_tenants = len(by_tenant)

    lines: list[str] = []
    lines.append("# Cost report")
    lines.append("")
    lines.append(f"- **Window:** {min(days)} → {max(days)} ({n_days} days)")
    lines.append(f"- **Tenants:** {n_tenants}")
    lines.append(f"- **Total spend:** {_fmt_usd(total)}")
    if n_days and n_tenants:
        lines.append(f"- **Avg spend / tenant / day:** {_fmt_usd(total / n_tenants / n_days)}")
    lines.append("")

    # ---- Per-tenant ----
    lines.append("## Spend by tenant")
    lines.append("")
    lines.append("| Tenant | Tier | Requests | Spend | % of total |")
    lines.append("|---|---|---:|---:|---:|")
    sorted_tenants = sorted(by_tenant.items(), key=lambda kv: -kv[1]["cost"])
    for _tenant_id, t in sorted_tenants:
        pct = (t["cost"] / total * 100.0) if total else 0.0
        lines.append(
            f"| {t['name']} | {t['tier']} | {t['requests']:,} | "
            f"{_fmt_usd(t['cost'])} | {pct:.1f}% |"
        )
    lines.append("")

    # ---- Per-model ----
    lines.append("## Spend by model")
    lines.append("")
    lines.append("| Model | Requests | Input tokens | Output tokens | Spend | % of total |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    sorted_models = sorted(by_model.items(), key=lambda kv: -kv[1]["cost"])
    for model, m in sorted_models:
        pct = (m["cost"] / total * 100.0) if total else 0.0
        lines.append(
            f"| `{model}` | {m['requests']:,} | "
            f"{m['in_tok']:,} | {m['out_tok']:,} | "
            f"{_fmt_usd(m['cost'])} | {pct:.1f}% |"
        )
    lines.append("")

    # ---- Daily trend ----
    lines.append("## Daily trend")
    lines.append("")
    lines.append("```")
    sorted_days = sorted(by_day.items())
    if sorted_days:
        max_day_cost = max(c for _, c in sorted_days) or 1.0
        for day, c in sorted_days:
            bars = round(c / max_day_cost * 40)
            lines.append(f"{day}  {'█' * bars}{' ' * (40 - bars)}  {_fmt_usd(c)}")
    lines.append("```")
    lines.append("")

    # ---- Insights ----
    lines.append("## Operator notes")
    lines.append("")
    lines.append(
        "_This section is a free-form interpretation of the numbers above._\n"
        "_Replace with observations once a real-traffic report exists._"
    )
    lines.append("")

    lines.append("## Methodology")
    lines.append("")
    lines.append(
        "Generated from `usage_records` CSV (or the synthetic-month "
        "fixture) by `scripts/cost/render_report.py`. Pricing is the "
        "snapshot in `scripts/cost/synthetic_month.py:MODEL_PRICES_PER_1K` "
        "— update before running against real data so per-token costs match "
        "the period being reported."
    )
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(prog="render_report")
    p.add_argument("--input", required=True, type=Path, help="usage_records-shaped CSV")
    p.add_argument("--output", required=True, type=Path, help="Markdown report path")
    args = p.parse_args()

    rows = _load(args.input)
    out = render(rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(out, encoding="utf-8")
    print(f"Wrote {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
