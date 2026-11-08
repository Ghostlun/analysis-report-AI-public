"""Generate the four public-safe aggregate research dashboard JSON files.

Usage:
    python scripts/generate_dashboards.py [--out public/dashboards] [--market-csv PATH] [--simulated-dir PATH]

All four documents are built and validated (schema, field allowlist, safety scan, finite numbers) before anything is
written. Files are then written atomically (temp file + os.replace), so a failure never leaves a partial or invalid
output and never overwrites existing valid files.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared import dashboards as dash  # noqa: E402
from shared.dashboard_schemas import DASHBOARDS, validate_dashboard  # noqa: E402

DEFAULT_OUT = ROOT / "public" / "dashboards"
DEFAULT_SIM = ROOT / "outputs" / "simulated"


def serialize(doc: dict) -> str:
    return json.dumps(doc, allow_nan=False, separators=(",", ":"), ensure_ascii=True) + "\n"


def build_all(market_csv: Path, simulated_dir: Path, generated_at: str) -> dict[str, dict]:
    src = dash.Sources(market_csv, simulated_dir)
    docs = {name: dash.BUILDERS[name](src, generated_at) for name in DASHBOARDS}
    for name, doc in docs.items():
        validate_dashboard(name, doc)
    return docs


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def generate(out_dir: Path = DEFAULT_OUT, market_csv: Path | None = None, simulated_dir: Path = DEFAULT_SIM,
             generated_at: str | None = None) -> dict[str, Path]:
    market_csv = Path(market_csv) if market_csv else ROOT / "data" / "raw" / "KXBTC15M_all.csv"
    generated_at = generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    docs = build_all(market_csv, Path(simulated_dir), generated_at)
    texts = {name: serialize(doc) for name, doc in docs.items()}  # serialise everything before touching disk
    out = {}
    for name, text in texts.items():
        p = Path(out_dir) / f"{name}.json"
        write_atomic(p, text)
        out[name] = p
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--market-csv", type=Path, default=None)
    ap.add_argument("--simulated-dir", type=Path, default=DEFAULT_SIM)
    a = ap.parse_args(argv)
    try:
        paths = generate(a.out, a.market_csv, a.simulated_dir)
    except Exception as exc:  # existing outputs are left untouched
        print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    for name, p in paths.items():
        print(f"{name}: {p} ({p.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
