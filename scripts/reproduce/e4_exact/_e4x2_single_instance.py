# -*- coding: utf-8 -*-
"""E4-EXACT-2 Pilot 单实例 worker（被 run_e4_exact_2_pilot.py 以 subprocess 调用）。

职责：运行单个 (n, regime, seed) 的 Exact Oracle，输出 JSON 到 stdout。
不访问 formal seeds；Oracle 语义冻结（本 worker 只计时、不修改 Oracle）。
"""

from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts", "reproduce", "e1_v2")))

import build_e1_v2_environment as B  # noqa: E402
from cars.exact_oracle.certificate import (  # noqa: E402
    VALID_REFERENCE_STATUSES, TIMEOUT_UNCERTIFIED, SOLVER_ERROR,
)
from cars.exact_oracle.oracle import solve_exact  # noqa: E402


def scenario_for(n: int, m: int, seed: int, regime: str) -> dict:
    env = B.build_e1_v2_environment(seed=seed, n_max=12, m=m, s_f=1.0,
                                    fragility_profile="MEDIUM")
    servers = env["servers"][:m]
    return {
        "schema_version": "CARS_ACTIVE_SCHEMA_V4",
        "scenario_id": "e4x2_%s_n%d_m%d_seed%d" % (regime, n, m, seed),
        "state_timepoint": "T0",
        "system_params": env["system_params"],
        "tasks": env["tasks"][:n],
        "devices": env["devices"][:n],
        "servers": servers,
        "links": [l for l in env["links"] if int(l["source_device_id"][1:]) <= n],
    }


def main() -> int:
    n = int(sys.argv[1])
    m = int(sys.argv[2])
    regime = sys.argv[3]
    seed = int(sys.argv[4])

    sc = scenario_for(n, m, seed, regime)

    from cars.evaluator.evaluator import evaluate as _default_eval

    _eval_ms = {"acc": 0.0}
    _ev_calls = {"n": 0}

    def _timed_eval(scenario, decision, derived):
        t0 = time.perf_counter()
        out = _default_eval(scenario, decision, derived)
        _eval_ms["acc"] += (time.perf_counter() - t0) * 1000.0
        _ev_calls["n"] += 1
        return out

    t_start = time.perf_counter()
    status = "COMPLETED"
    oracle_status = None
    objective = None
    certificate = None
    error_msg = None
    try:
        res = solve_exact(sc, mode="EXACT_PRUNED", evaluator=_timed_eval)
        oracle_status = res["oracle_status"]
        objective = res["objective_tuple"]
        certificate = res["certificate"]
    except Exception as exc:  # noqa: BLE001 —— 如实记录
        status = "ERROR"
        oracle_status = SOLVER_ERROR
        error_msg = "%s: %s" % (type(exc).__name__, str(exc))
    total_ms = (time.perf_counter() - t_start) * 1000.0

    accepted = oracle_status in VALID_REFERENCE_STATUSES
    cert_pass = bool(certificate) and certificate.get("kkt_residual") is not None

    record = {
        "experiment": "e4_exact_2_pilot",
        "n": n, "m": m, "regime": regime, "seed": seed,
        "status": status,
        "oracle_status": oracle_status,
        "accepted_exact": accepted,
        "certificate_pass": cert_pass,
        "objective_tuple": objective,
        "total_discrete_states": certificate.get("total_discrete_states") if certificate else None,
        "visited_states": certificate.get("visited_states") if certificate else None,
        "safely_pruned_states": certificate.get("safely_pruned_states") if certificate else None,
        "feasible_states": certificate.get("feasible_states") if certificate else None,
        "infeasible_states": certificate.get("infeasible_states") if certificate else None,
        "kkt_residual": certificate.get("kkt_residual") if certificate else None,
        "capacity_residual": certificate.get("capacity_residual") if certificate else None,
        "reliability_residual": certificate.get("reliability_residual") if certificate else None,
        "primal_residual": certificate.get("primal_residual") if certificate else None,
        "canonical_solution_hash": certificate.get("canonical_solution_hash") if certificate else None,
        "exactness_mode": certificate.get("exactness_mode") if certificate else None,
        "total_oracle_runtime_ms": round(total_ms, 3),
        "evaluator_runtime_ms": round(_eval_ms["acc"], 3),
        "evaluator_calls": _ev_calls["n"],
        "enumeration_runtime_ms": None,
        "continuous_solver_runtime_ms": None,
        "timeout_s": float(os.environ.get("E4X2_TIMEOUT_S", "0")),
        "error_msg": error_msg,
    }
    sys.stdout.write(json.dumps(record, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
