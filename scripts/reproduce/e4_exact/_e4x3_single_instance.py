# -*- coding: utf-8 -*-
"""E4-EXACT-3 Formal 单实例 worker（被 run_e4_exact_3_formal.py 以 subprocess 调用）。

职责：对单个 (regime, N, formal_seed) 实例：
  1) 构建共享 Scenario（E1-V2 缩小族；M=4；确定性 seed）；
  2) 运行 Exact Oracle（solve_exact；Route A；期望 CERTIFIED_NUMERICAL_EXACT）；
  3) 运行正式 CARS（CARS_FROZEN_V4；MethodRunner；hard timeout 30s）；
  4) 由统一 Evaluator 分别评估（Oracle 内部计时 evaluator；CARS 的 RunRecord 自带
     evaluator_output）；
  5) 计算 Tier-1/2/3 gap 与 match（字典序；EPS_CMP=1e-9）。

formal seeds 3501-3510 仅由已授权 runner 传入本 worker；worker 不自行选择 seed。
Oracle / CARS / Evaluator / 物理模型均零改动（本 worker 只组装与计时）。

依据：configs/e4_exact/e4_exact_formal_protocol.yaml（方案 A；metrics §6；
authorized 2026-08-10）；E4_EXACT_ORACLE_CONTRACT_V1.md。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time

import yaml

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts", "reproduce", "e1_v2")))

import build_e1_v2_environment as B  # noqa: E402
from cars.exact_oracle.certificate import (  # noqa: E402
    VALID_REFERENCE_STATUSES, SOLVER_ERROR,
)
from cars.exact_oracle.lexicographic import EPS_CMP  # noqa: E402
from cars.exact_oracle.oracle import solve_exact  # noqa: E402
from cars.runner.runner import MethodRunner  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CARS_CONFIG = os.path.join(ROOT, "configs", "cars_v4", "cars_frozen_v4.yaml")
CARS_TIMEOUT_S = 30.0


def scenario_config_for(n: int, m: int, seed: int, regime: str) -> dict:
    """E1-V2 缩小族 explicit 配置（含 mode=explicit；materializer 可物化）。

    与 E1-V2 formal runner 同法：build_e1_v2_environment 返回含 mode=explicit 的
    配置；prefix_scenario 取前 n 个任务/设备/链路（确定性前缀）。Oracle 与 CARS
    共享同一物化场景。
    """
    env = B.build_e1_v2_environment(seed=seed, n_max=12, m=m, s_f=1.0,
                                    fragility_profile="MEDIUM")
    cfg_n = B.prefix_scenario(env, n)
    cfg_n["scenario_id"] = "e4x3_%s_n%d_m%d_seed%d" % (regime, n, m, seed)
    return cfg_n


def materialized_scenario(cfg_n: dict) -> dict:
    """物化显式场景（Oracle 与 CARS 共享；MethodRunner 内部亦调用同一 materialize）。"""
    from cars.simulator.scenario_materializer import materialize
    return materialize(cfg_n)


def run_oracle(cfg_n: dict) -> dict:
    """Exact Oracle 求解 + 计时（Evaluator 调用计数）。"""
    from cars.evaluator.evaluator import evaluate as _default_eval

    sc = materialized_scenario(cfg_n)

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
    return {
        "status": status,
        "oracle_status": oracle_status,
        "accepted_exact": accepted,
        "certificate_pass": cert_pass,
        "objective_tuple": objective,
        "certificate_fields": {
            "total_discrete_states": certificate.get("total_discrete_states") if certificate else None,
            "visited_states": certificate.get("visited_states") if certificate else None,
            "feasible_states": certificate.get("feasible_states") if certificate else None,
            "kkt_residual": certificate.get("kkt_residual") if certificate else None,
            "capacity_residual": certificate.get("capacity_residual") if certificate else None,
            "reliability_residual": certificate.get("reliability_residual") if certificate else None,
            "primal_residual": certificate.get("primal_residual") if certificate else None,
            "canonical_solution_hash": certificate.get("canonical_solution_hash") if certificate else None,
            "exactness_mode": certificate.get("exactness_mode") if certificate else None,
        } if certificate else None,
        "total_oracle_runtime_ms": round(total_ms, 3),
        "evaluator_runtime_ms": round(_eval_ms["acc"], 3),
        "evaluator_calls": _ev_calls["n"],
        "error_msg": error_msg,
    }


def run_cars(cfg_n: dict) -> dict:
    """正式 CARS（CARS_FROZEN_V4）运行 + 统一 Evaluator 输出。

    MethodRunner 内部通过 materialize(cfg) 物化同一 explicit 配置，与 Oracle
    共享同一场景。
    """
    tmp = tempfile.mkdtemp(prefix="e4x3_cars_")
    scen_path = os.path.join(tmp, "scenario.yaml")
    with open(scen_path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg_n, fh, allow_unicode=True, sort_keys=False)
    cars_cfg = yaml.safe_load(open(CARS_CONFIG, encoding="utf-8"))
    t_start = time.perf_counter()
    try:
        runner = MethodRunner()
        rec = runner.run(
            method_id="cars",
            scenario_cfg_path=scen_path,
            method_config=cars_cfg,
            method_seed=int(cars_cfg.get("method_seed", 1)),
            hard_timeout_seconds=CARS_TIMEOUT_S,
        )
    except Exception as exc:  # noqa: BLE001 —— 如实记录
        return {
            "status": "ERROR",
            "method_status": "METHOD_ERROR",
            "error_msg": "%s: %s" % (type(exc).__name__, str(exc)),
            "runtime_ms": round((time.perf_counter() - t_start) * 1000.0, 3),
            "tssr": None, "rbar_eff": None, "ubar_eff": None,
            "method_runtime_ms": None, "runtime_censored": False,
        }
    total_ms = (time.perf_counter() - t_start) * 1000.0
    ev = rec.get("evaluator_output") or {}
    sm = ev.get("system_metrics") or {}
    return {
        "status": "COMPLETED",
        "method_status": rec.get("method_status"),
        "tssr": sm.get("tssr"),
        "rbar_eff": sm.get("mean_effective_reliability"),
        "ubar_eff": sm.get("mean_effective_utility"),
        "runtime_ms": round(total_ms, 3),
        "method_runtime_ms": rec.get("method_runtime_ms"),
        "runtime_censored": rec.get("runtime_censored", False),
        "method_error": rec.get("method_error"),
        "error_msg": None,
    }


def tier_metrics(oracle_obj, cars: dict) -> dict:
    """字典序 Tier-1/2/3 gap 与 match（EPS_CMP=1e-9；formal protocol §6 metrics）。"""
    if oracle_obj is None or cars.get("tssr") is None:
        return {
            "computable": False, "reason": "oracle or cars missing",
            "tier1_gap": None, "tier1_match": False,
            "tier2_gap": None, "tier2_match": False,
            "tier3_gap": None, "tier3_match": False,
            "full_lex_match": False,
        }
    o_t1, o_t2, o_t3 = oracle_obj
    c_t1 = cars["tssr"]
    c_t2 = cars["rbar_eff"]
    c_t3 = cars["ubar_eff"]
    if c_t2 is None or c_t3 is None:
        return {
            "computable": False, "reason": "cars metrics missing",
            "tier1_gap": None, "tier1_match": False,
            "tier2_gap": None, "tier2_match": False,
            "tier3_gap": None, "tier3_match": False,
            "full_lex_match": False,
        }
    tier1_gap = o_t1 - c_t1
    tier1_match = abs(tier1_gap) <= EPS_CMP
    tier2_gap = (o_t2 - c_t2) if tier1_match else None
    tier2_match = tier1_match and tier2_gap is not None and abs(tier2_gap) <= EPS_CMP
    tier3_gap = (o_t3 - c_t3) if tier2_match else None
    tier3_match = tier2_match and tier3_gap is not None and abs(tier3_gap) <= EPS_CMP
    return {
        "computable": True,
        "tier1_gap": tier1_gap,
        "tier1_match": tier1_match,
        "tier2_gap": tier2_gap,
        "tier2_match": tier2_match,
        "tier3_gap": tier3_gap,
        "tier3_match": tier3_match,
        "full_lex_match": tier3_match,
    }


def main() -> int:
    n = int(sys.argv[1])
    m = int(sys.argv[2])
    regime = sys.argv[3]
    seed = int(sys.argv[4])

    cfg_n = scenario_config_for(n, m, seed, regime)
    oracle = run_oracle(cfg_n)
    cars = run_cars(cfg_n)
    metrics = tier_metrics(oracle.get("objective_tuple"), cars)

    record = {
        "experiment": "e4_exact_3_formal",
        "n": n, "m": m, "regime": regime, "formal_seed": seed,
        "status": oracle["status"],           # COMPLETED / ERROR（TIMEOUT 由 runner 产生）
        "oracle_status": oracle["oracle_status"],
        "accepted_exact": oracle["accepted_exact"],
        "certificate_pass": oracle["certificate_pass"],
        "oracle": oracle,
        "cars": cars,
        "metrics": metrics,
        "timeout_s": float(os.environ.get("E4X3_TIMEOUT_S", "0")),
    }
    sys.stdout.write(json.dumps(record, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
