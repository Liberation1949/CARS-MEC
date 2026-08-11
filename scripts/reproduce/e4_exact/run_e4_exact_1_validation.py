# -*- coding: utf-8 -*-
"""E4-EXACT-1 validation runner（只运行 validation cases；formal seeds 零访问）。

依据：E4-EXACT-1 阶段合同 §十/§十一（性能边界、Mandatory 产物 5）。
- 只运行 ultra-tiny validation cases（N<=3/M<=2 用于 production==naive cross-check；
  另附 N=4 production-only runtime 记录）；
- 显式拒绝 formal seeds：命令行出现 --authorize-formal-seeds 立即报错退出；
- 生成 results/e4_exact/e4_exact_1_validation/ 下全部机器产物；
- 墙上时钟 runtime 只作记录，不进入 canonical 字段。

用法：
  python scripts/reproduce/e4_exact/run_e4_exact_1_validation.py
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time

# 拒绝 formal seeds（合同：FORMAL_SEEDS_ACCESSED=NO）
if "--authorize-formal-seeds" in sys.argv:
    sys.stderr.write("[FATAL] formal seeds authorization forbidden in E4-EXACT-1\n")
    sys.exit(2)

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "tests")))

from e4_exact import _scenario_factory as sf
from e4_exact.reference_naive_exhaustive import naive_exhaustive
from cars.exact_oracle.certificate import EXACT_OPTIMAL, CERTIFIED_NUMERICAL_EXACT
from cars.exact_oracle.oracle import solve_exact

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
OUT_DIR = os.path.join(ROOT, "results", "e4_exact", "e4_exact_1_validation")


def _task(local_cpu_rate, local_failure_rate, fragility, cpu_cycles):
    return {
        "local_cpu_rate": local_cpu_rate, "local_failure_rate": local_failure_rate,
        "switch_capacitance": 1.0e-27, "tx_power_watts": 0.1, "data_bits": 1.0e6,
        "cpu_cycles": cpu_cycles, "fragility": fragility,
        "delay_weight": 0.5, "energy_weight": 0.5,
        "min_reliability": 0.9, "deadline_seconds": 100.0,
    }


def task_ok():
    return _task(1.0e9, 5.0e-9, 1.0e-9, 1.0e9)


def task_fail():
    return _task(1.0e9, 0.6, 0.001, 2.0e11)


def server(capacity=1.0e10, lambda_j=1.0e-9):
    return {"capacity_cycles_per_sec": capacity, "nominal_failure_rate": lambda_j}


def _fl(n, m):
    return {(i, j): sf.default_link_spec() for i in range(n) for j in range(m)}


def build_cross_cases():
    """production==naive cross-check cases（N<=3, M<=2）。"""
    cases = []
    cases.append(sf.make_scenario("v01", [task_ok()], [server()], _fl(1, 1)))
    cases.append(sf.make_scenario("v02", [task_fail()], [server()], _fl(1, 1)))
    cases.append(sf.make_scenario("v03", [task_ok(), task_ok()], [server()],
                                  {(0, 0): sf.default_link_spec(), (1, 0): sf.default_link_spec()}))
    cases.append(sf.make_scenario("v04", [task_fail(), task_fail()], [server()],
                                  {(0, 0): sf.default_link_spec(), (1, 0): sf.default_link_spec()}))
    cases.append(sf.make_scenario("v05", [task_ok(), task_fail()], [server()],
                                  {(0, 0): sf.default_link_spec(), (1, 0): sf.default_link_spec()}))
    cases.append(sf.make_scenario("v06", [task_fail(), task_ok()],
                                  [server(), server(1.0e9)], _fl(2, 2)))
    cases.append(sf.make_scenario("v07", [task_fail(), task_fail()],
                                  [server(), server(5.0e3)], _fl(2, 2)))
    cases.append(sf.make_scenario("v08", [task_ok(), task_ok(), task_fail()], [server()],
                                  {(0, 0): sf.default_link_spec(), (1, 0): sf.default_link_spec(),
                                   (2, 0): sf.default_link_spec()}))
    cases.append(sf.make_scenario("v09", [task_fail(), task_fail(), task_fail()], [server()],
                                  {(0, 0): sf.default_link_spec(), (1, 0): sf.default_link_spec(),
                                   (2, 0): sf.default_link_spec()}))
    cases.append(sf.make_scenario("v10", [task_ok(), task_fail(), task_fail()],
                                  [server(8.0e3), server(8.0e3)], _fl(3, 2)))
    cases.append(sf.make_scenario("v11", [task_fail(), task_fail(), task_fail()],
                                  [server(4.0e3), server(4.0e3)], _fl(3, 2)))
    cases.append(sf.make_scenario("v12", [task_ok(), task_ok(), task_ok()],
                                  [server(), server(1.0e9)], _fl(3, 2)))
    cases.append(sf.make_scenario("v13", [task_fail(), task_ok()], [server()],
                                  {(0, 0): sf.default_link_spec()}))
    return cases


def build_runtime_cases():
    """production-only runtime 记录（N=4；naive 上限 N<=3 故不做 cross-check）。"""
    return [
        sf.make_scenario("v14", [task_fail(), task_ok(), task_fail(), task_ok()],
                         [server(2.0e10), server(2.0e10)], _fl(4, 2)),
        sf.make_scenario("v15", [task_fail(), task_fail(), task_fail(), task_fail()],
                         [server(1.0e10), server(1.0e10), server(1.0e10), server(1.0e10)],
                         _fl(4, 4)),
    ]


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    cross_cases = build_cross_cases()
    runtime_cases = build_runtime_cases()

    validation_cases = []
    oracle_results = []
    certificates = []
    crosscheck = []

    # --- cross-check cases（production vs naive）---
    for sc in cross_cases:
        sid = sc["scenario_id"]
        t0 = time.perf_counter()
        rp = solve_exact(sc, mode="EXACT_PRUNED")
        prod_ms = (time.perf_counter() - t0) * 1000.0
        t0 = time.perf_counter()
        rn = naive_exhaustive(sc)
        naive_ms = (time.perf_counter() - t0) * 1000.0
        match = (
            rn["found"]
            and rp["objective_tuple"] is not None
            and all(abs(rp["objective_tuple"][k] - rn["objective_tuple"][k]) <= 1e-9
                    for k in range(3))
        )
        validation_cases.append({
            "case_id": sid, "n": len(sc["tasks"]), "m": len(sc["servers"]),
            "cross_check": True, "naive_capable": True,
        })
        oracle_results.append({
            "case_id": sid, "oracle_status": rp["oracle_status"],
            "objective_tuple": rp["objective_tuple"],
            "decision": rp["decision"],
            "runtime_ms": round(prod_ms, 4),
            "cross_check": True,
        })
        certificates.append({
            "case_id": sid, "oracle_status": rp["oracle_status"],
            "certificate": rp["certificate"],
        })
        crosscheck.append({
            "case_id": sid,
            "production_objective": rp["objective_tuple"],
            "naive_objective": rn["objective_tuple"],
            "naive_found": rn["found"],
            "match": match,
            "production_runtime_ms": round(prod_ms, 4),
            "naive_runtime_ms": round(naive_ms, 4),
        })
        if not match:
            sys.stderr.write("[FAIL] case %s production != naive\n" % sid)
            return 1

    # --- runtime-only cases（N=4；不 cross-check）---
    for sc in runtime_cases:
        sid = sc["scenario_id"]
        t0 = time.perf_counter()
        rp = solve_exact(sc, mode="EXACT_PRUNED")
        ms = (time.perf_counter() - t0) * 1000.0
        validation_cases.append({
            "case_id": sid, "n": len(sc["tasks"]), "m": len(sc["servers"]),
            "cross_check": False, "naive_capable": False,
        })
        oracle_results.append({
            "case_id": sid, "oracle_status": rp["oracle_status"],
            "objective_tuple": rp["objective_tuple"],
            "decision": rp["decision"],
            "runtime_ms": round(ms, 4),
            "cross_check": False,
        })
        certificates.append({
            "case_id": sid, "oracle_status": rp["oracle_status"],
            "certificate": rp["certificate"],
        })

    # --- 产物 ---
    all_match = all(c["match"] for c in crosscheck)
    runtime_summary = {
        "cases_total": len(validation_cases),
        "cross_check_cases": len(cross_cases),
        "runtime_cases": len(runtime_cases),
        "all_cross_check_match": all_match,
        "cross_check_match_rate": (
            sum(1 for c in crosscheck if c["match"]) / len(crosscheck)
            if crosscheck else 0.0
        ),
        "runtimes_ms": [r["runtime_ms"] for r in oracle_results],
        "note": "墙上时钟仅记录；不进入 canonical 字段；N=4 为 production-only runtime 记录",
        "formal_seeds_accessed": False,
        "pilot_executed": False,
        "formal_executed": False,
    }

    integrity = {
        "integrity_version": "E4_EXACT_1_VALIDATION_V1",
        "stage": "E4-EXACT-1",
        "status": "VALIDATION_DONE",
        "formal_seeds_accessed": False,
        "pilot_executed": False,
        "formal_executed": False,
        "oracle_statuses": sorted({c["oracle_status"] for c in certificates}),
        "cross_check_all_match": all_match,
        "num_validation_cases": len(validation_cases),
        "num_cross_check_cases": len(crosscheck),
    }

    def _w(name, obj):
        p = os.path.join(OUT_DIR, name)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        return hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]

    out_files = {
        "validation_cases.json": validation_cases,
        "oracle_results.jsonl": [json.dumps(r, ensure_ascii=False) for r in oracle_results],
        "exactness_certificates.jsonl": [
            json.dumps(c, ensure_ascii=False) for c in certificates
        ],
        "naive_crosscheck.json": crosscheck,
        "runtime_summary.json": runtime_summary,
    }
    hashes = {}
    for name, obj in out_files.items():
        if name.endswith(".jsonl"):
            text = "\n".join(obj) + "\n"
            p = os.path.join(OUT_DIR, name)
            with open(p, "w", encoding="utf-8") as f:
                f.write(text)
            hashes[name] = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        else:
            hashes[name] = _w(name, obj)
    integrity["output_file_hashes"] = hashes
    _w("integrity.json", integrity)

    print("E4-EXACT-1 validation done: %d cases, cross-check all match = %s"
          % (len(validation_cases), all_match))
    print("  oracle statuses:", sorted({c["oracle_status"] for c in certificates}))
    return 0 if all_match else 1


if __name__ == "__main__":
    sys.exit(main())
