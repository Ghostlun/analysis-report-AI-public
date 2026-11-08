"""Single entry point for the analyses.   python run.py            -> list commands
                                           python run.py <command> -> run one
All analyses are offline and read-only (CSV in, tables/CSVs out)."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

pd.set_option("display.width", 250, "display.max_columns", 60, "display.max_rows", 400, "display.float_format", "{:.4f}".format)


def show(title, obj):
    print(f"\n=== {title} ===")
    if isinstance(obj, dict):
        for k, v in obj.items():
            print(f"--- {k}")
            print(v)
    else:
        print(obj)


def _m():
    import momentum
    return momentum


def actual():
    """ACTUAL live momentum results: reconciliation, losing trades, buckets, calibration."""
    m = _m()
    show("ACTUAL: audit and reconciliation", m.actual_audit())
    t = m.actual_trades()
    show("ACTUAL: losing trades", m.actual_losses(t))
    show("ACTUAL: buckets", m.actual_buckets(t))
    show("ACTUAL: z calibration", m.actual_calibration(t))


def simulated():
    """SIMULATED v1 vs dev-selected v2 on identical historical markets (dev/test split) + live-vs-replay check."""
    m = _m()
    show("SIMULATED: chosen v2 (selected on dev only)", dict(m.chosen_v2()))
    show("SIMULATED: v1 vs v2", m.v1_vs_v2())
    show("SIMULATED: test paired difference v2 - v1", m.paired_diff())
    show("SIMULATED vs ACTUAL: replay fidelity", m.fidelity())


def filters():
    """SIMULATED effect of each v2 filter on trade count and P&L (dev and test)."""
    m = _m()
    for period in ("dev", "test"):
        show(f"SIMULATED: filter impact, {period} period, slip+0.01, N={m.N_CONTRACTS}", m.filter_impact(period))


def check():
    """Verify headline numbers from MOMENTUM_V2_ANALYSIS.md are reproduced."""
    m = _m()
    s = m.actual_audit()["summary"].iloc[0]
    v = m.v1_vs_v2().set_index(["period", "rule", "scenario"])
    t1, t2 = v.loc[("test", "v1", "slip+0.01")], v.loc[("test", "v2", "slip+0.01")]
    checks = [
        ("live settled momentum trades", s.settled, 146, 0),
        ("live net P&L", s.net_pnl, -6.0343, 5e-4),
        ("live fees", s.fees, 2.9403, 5e-4),
        ("live P&L identity error", s.max_abs_pnl_identity_error, 0, 1e-9),
        ("v2 rule (std_only, z>=1.5, persist 1, ask<=0.97)", [dict(m.chosen_v2())[k] for k in ("mode", "zmin", "persist", "maxp")],
         ["std_only", 1.5, 1, 0.97], None),
        ("test v1 trades", t1.n, 342, 0), ("test v1 net", t1.net, -19.95, 5e-3),
        ("test v2 trades", t2.n, 145, 0), ("test v2 net", t2.net, 0.13, 5e-3), ("test v2 maxdd", t2.maxdd, 9.8, 0.05),
    ]
    bad = 0
    for name, got, want, tol in checks:
        ok = got == want if tol is None else abs(got - want) <= tol
        bad += not ok
        print(("OK   " if ok else "FAIL ") + f"{name}: got {got} expected {want}")
    sys.exit(1 if bad else 0)


def model():
    """SIMULATED pattern model: P(yes) from % gap to strike and its recent path; accuracy by time and entry-policy EV."""
    import pattern_model
    for title, obj in pattern_model.run().items():
        show(f"MODEL: {title}", obj)


def gap():
    """SIMULATED gap rule: minimum % gap to strike per time bin that was safe enough; buy once reached (dev fit, test check)."""
    import gap_rule
    for title, obj in gap_rule.run().items():
        show(f"GAP RULE: {title}", obj)


def legacy(name=None):
    """Run one of the earlier one-off experiments: python run.py legacy <file> (see experiments\\)."""
    files = sorted(p.stem for p in (ROOT / "experiments").glob("*.py"))
    if name not in files:
        print("experiments:", ", ".join(files))
        return
    subprocess.run([sys.executable, str(ROOT / "experiments" / f"{name}.py")], check=True)


COMMANDS = {"actual": actual, "simulated": simulated, "filters": filters, "check": check, "model": model, "gap": gap, "legacy": legacy}

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else None
    if cmd not in COMMANDS:
        print("Usage: python run.py <command>\n")
        for k, f in COMMANDS.items():
            print(f"  {k:10s} {f.__doc__.splitlines()[0]}")
        sys.exit(0 if cmd is None else 2)
    COMMANDS[cmd](*sys.argv[2:])
