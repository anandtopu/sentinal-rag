"""Generate a synthetic month of cost data for the cost report.

Phase 9 portfolio polish artifact. Until we have 30 days of real traffic
through a deployed environment, this script emits a CSV that mirrors the
shape of ``usage_records`` so the cost report can be rendered with
plausible numbers.

Output:
    scripts/cost/synthetic-month.csv

Columns: tenant_id, day, model, requests, input_tokens, output_tokens, cost_usd

Run:
    uv run python scripts/cost/synthetic_month.py \\
        --tenants 4 \\
        --days 30 \\
        --output scripts/cost/synthetic-month.csv

Then render the report:
    uv run python scripts/cost/render_report.py \\
        --input scripts/cost/synthetic-month.csv \\
        --output docs/operations/cost-report.md

We model traffic as a Poisson-distributed count of requests per
tenant-day, with a heavy tail of cheap Ollama-served requests and a
small tail of expensive Anthropic / OpenAI requests.
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

# Pricing snapshot. Matches the shape of MODEL_PRICES in CostService.
# Real pricing is dynamic; these are representative numbers for the report.
MODEL_PRICES_PER_1K = {
    # (input_usd_per_1k, output_usd_per_1k)
    "ollama/llama3.1:8b": (0.00, 0.00),  # self-hosted
    "ollama/nomic-embed-text": (0.00, 0.00),
    "openai/text-embedding-3-small": (0.00002, 0.0),
    "openai/gpt-4o-mini": (0.00015, 0.0006),
    "anthropic/claude-haiku-4-5-20251001": (0.0008, 0.004),
    "anthropic/claude-sonnet-4-6": (0.003, 0.015),
}

# Model mix per tenant size category. Sums to 1.0 within each row.
MODEL_MIX = {
    "free": [("ollama/llama3.1:8b", 0.95), ("openai/gpt-4o-mini", 0.05)],
    "team": [
        ("ollama/llama3.1:8b", 0.5),
        ("openai/gpt-4o-mini", 0.3),
        ("anthropic/claude-haiku-4-5-20251001", 0.2),
    ],
    "scale": [
        ("anthropic/claude-haiku-4-5-20251001", 0.5),
        ("anthropic/claude-sonnet-4-6", 0.3),
        ("openai/gpt-4o-mini", 0.2),
    ],
}

# Per-request token distribution per model. Means; we sample around them.
TOKEN_PROFILE = {
    "ollama/llama3.1:8b": (1200, 350),  # input, output
    "ollama/nomic-embed-text": (300, 0),
    "openai/text-embedding-3-small": (300, 0),
    "openai/gpt-4o-mini": (1500, 400),
    "anthropic/claude-haiku-4-5-20251001": (1800, 500),
    "anthropic/claude-sonnet-4-6": (2000, 700),
}


@dataclass(slots=True)
class Tenant:
    tenant_id: UUID
    name: str
    tier: str  # "free" | "team" | "scale"
    rps_mean: float  # daily request rate (mean)


def _make_tenants(n: int, *, rng: random.Random) -> list[Tenant]:
    tiers = ["free", "free", "team", "team", "scale"]  # weighted
    tenants: list[Tenant] = []
    for i in range(n):
        tier = rng.choice(tiers)
        rps_mean = {
            "free": rng.uniform(20, 80),
            "team": rng.uniform(150, 600),
            "scale": rng.uniform(800, 3000),
        }[tier]
        tenants.append(
            Tenant(
                tenant_id=uuid4(),
                name=f"acme-{tier}-{i:02d}",
                tier=tier,
                rps_mean=rps_mean,
            )
        )
    return tenants


def _pick_model(tier: str, *, rng: random.Random) -> str:
    mix = MODEL_MIX[tier]
    r = rng.random()
    cum = 0.0
    for model, p in mix:
        cum += p
        if r <= cum:
            return model
    return mix[-1][0]


def _sample_tokens(model: str, *, rng: random.Random) -> tuple[int, int]:
    mu_in, mu_out = TOKEN_PROFILE[model]
    # Log-normal-ish distribution to get a plausible long tail.
    in_tokens = max(1, int(rng.gauss(mu=mu_in, sigma=mu_in * 0.35)))
    out_tokens = max(0, int(rng.gauss(mu=mu_out, sigma=mu_out * 0.35))) if mu_out else 0
    return in_tokens, out_tokens


def _cost(model: str, in_tokens: int, out_tokens: int) -> float:
    p_in, p_out = MODEL_PRICES_PER_1K[model]
    return (in_tokens / 1000.0) * p_in + (out_tokens / 1000.0) * p_out


def generate(
    *,
    n_tenants: int,
    n_days: int,
    seed: int,
    output_path: Path,
) -> None:
    rng = random.Random(seed)
    tenants = _make_tenants(n_tenants, rng=rng)
    today = datetime.now(tz=UTC).date()
    start = today - timedelta(days=n_days - 1)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "tenant_id",
                "tenant_name",
                "tier",
                "day",
                "model",
                "requests",
                "input_tokens",
                "output_tokens",
                "cost_usd",
            ]
        )

        for tenant in tenants:
            for d in range(n_days):
                day = start + timedelta(days=d)
                # Weekly seasonality: weekdays 1.0x, weekends 0.4x.
                # day.weekday(): Monday=0..Sunday=6, so 5+ are Sat+Sun.
                weekday_scale = 0.4 if day.weekday() >= 5 else 1.0  # noqa: PLR2004
                # Per-day Poisson around the tenant's mean.
                lam = tenant.rps_mean * weekday_scale
                requests = max(0, int(rng.gauss(lam, lam**0.5)))

                # Group by model across the day's requests.
                model_buckets: dict[str, list[tuple[int, int]]] = {}
                for _ in range(requests):
                    model = _pick_model(tenant.tier, rng=rng)
                    model_buckets.setdefault(model, []).append(_sample_tokens(model, rng=rng))

                for model, samples in model_buckets.items():
                    in_total = sum(s[0] for s in samples)
                    out_total = sum(s[1] for s in samples)
                    cost = _cost(model, in_total, out_total)
                    w.writerow(
                        [
                            str(tenant.tenant_id),
                            tenant.name,
                            tenant.tier,
                            day.isoformat(),
                            model,
                            len(samples),
                            in_total,
                            out_total,
                            f"{cost:.4f}",
                        ]
                    )

    print(f"Wrote {output_path}", file=sys.stderr)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="synthetic_month",
        description="Generate a synthetic month of usage_records-shaped cost data.",
    )
    p.add_argument("--tenants", type=int, default=4)
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--output", type=Path, default=Path("scripts/cost/synthetic-month.csv"))
    return p


def main() -> int:
    args = _build_parser().parse_args()
    generate(
        n_tenants=args.tenants,
        n_days=args.days,
        seed=args.seed,
        output_path=args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
