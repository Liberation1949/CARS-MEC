#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""CARS Quick Start.

Runs the formal CARS method (AADA -> RCLA) on a deterministic tiny scenario
from the frozen E0-V2 environment and evaluates it with the unified Evaluator.

Usage:
    python -m pip install -e .
    python scripts/quick_start.py

Output: seed / status / TSSR / Rbar_eff / Ubar_eff / runtime /
deterministic result fingerprint (same seed -> same fingerprint).
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_REPRO = os.path.join(_HERE, "reproduce")
for _p in (_REPRO, os.path.join(_REPRO, "e0_v2")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from build_e0_v2_environment import build_e0_v2_environment  # noqa: E402
from cars.evaluator import evaluator as ev  # noqa: E402
from cars.methods.cars.method import CarsMethod  # noqa: E402
from cars.methods.protocol import MethodContext  # noqa: E402
from cars.simulator.derived_state import DerivedState  # noqa: E402
from cars.simulator.scenario_materializer import materialize  # noqa: E402

SEED = 201
N = 4
M = 2
N_MAX = 20
SOFT_DEADLINE = 27.0
HARD_TIMEOUT = 30.0


def decision_fingerprint(decision) -> str:
    """Deterministic fingerprint of the full decision (X, A, F)."""
    payload = json.dumps(decision, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def run_once(seed: int = SEED) -> dict:
    """Run Scenario -> CARS -> Evaluator once; return a summary dict."""
    env = build_e0_v2_environment(seed=seed, n=N, n_max=N_MAX)
    scenario = materialize(env)
    derived = DerivedState(scenario)

    with open(os.path.join(_ROOT, "configs", "cars_v4", "cars_frozen_v4.yaml"), encoding="utf-8") as fh:
        cars_cfg = yaml.safe_load(fh)

    method = CarsMethod(cars_cfg)
    ctx = MethodContext(
        scenario=scenario,
        derived=derived,
        config=cars_cfg,
        method_seed=seed,
        soft_deadline_seconds=SOFT_DEADLINE,
        hard_timeout_seconds=HARD_TIMEOUT,
    )
    proposal = method.run(ctx)

    out = ev.evaluate(scenario, proposal.decision, derived)
    sm = (out.get("evaluator_output") or {}).get("system_metrics") or {}

    return {
        "seed": seed,
        "status": proposal.method_status,
        "TSSR": sm.get("tssr"),
        "Rbar_eff": sm.get("mean_effective_reliability"),
        "Ubar_eff": sm.get("mean_effective_utility"),
        "runtime_seconds": round(float(proposal.runtime_seconds), 6),
        "fingerprint": decision_fingerprint(proposal.decision),
    }


def main() -> int:
    print("CARS Quick Start (AADA -> RCLA)")
    print("=" * 56)
    r1 = run_once(SEED)
    r2 = run_once(SEED)
    deterministic = r1["fingerprint"] == r2["fingerprint"]

    def show(r):
        for k, v in r.items():
            print("  %-16s %s" % (k, v))

    print("Run 1 (seed=%d):" % SEED)
    show(r1)
    print("Run 2 (seed=%d):" % SEED)
    show(r2)
    print("-" * 56)
    print("Deterministic (same seed -> same fingerprint): %s" % deterministic)
    if not deterministic:
        print("ERROR: non-deterministic result (same seed produced different fingerprint).")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
