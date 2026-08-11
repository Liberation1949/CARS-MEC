# -*- coding: utf-8 -*-
"""E0-V2-2：正式 Confirmatory Evaluation runner（E0-V2-2 合同；2026-08-09）。

阶段合同（configs/e0_v2/e0_v2_2_formal_protocol.yaml）：
- 正式网格：N={20,50,80,110,140,170,200}（E0_V2_FORMAL_GRID_V1 候选 A，pilot 后冻结）；
- 正式 seeds 601-620（NEW_PAIRED_UNSEEN；pilot 201-205 禁止进入正式统计）；
- 主方法：reliability_only / bpso_rata_la / cars_aada_rcla_candidate（420 runs）；
  诊断控制：local_only（140 runs，不入主图）；
- 同 (seed, N) 全部方法共享同一 canonical scenario（paired；scenario_hash 断言）；
- 统一 Evaluator 唯一正式评价；指标 = 核心 4 + 机制 6（E0-V2-0 字段定义）；
- 禁止：formal 后调网格/指标；隐藏 timeout/error；pilot seeds 入正式统计。

输出：results/e0_v2/e0_v2_2_formal/{scenarios/, formal_raw.jsonl, formal_summary.json}
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
import time

import yaml

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(_PROJECT, "src"))
sys.path.insert(0, os.path.join(_PROJECT, "scripts", "reproduce", "e0_v2"))

from build_e0_v2_environment import (  # noqa: E402
    E0_N_MAX,
    build_e0_v2_super_scenario,
    e0_prefix_scenario,
)
from cars.runner.runner import MethodRunner  # noqa: E402
from cars.simulator.derived_state import DerivedState  # noqa: E402
from cars.simulator.scenario_materializer import materialize  # noqa: E402

from run_e0_v2_pilot import (  # noqa: E402
    ALL_METHODS,
    CANDIDATE_ID,
    METHOD_SEED,
    METHOD_CONFIG_PATHS,
    TIMEOUT,
    _run_baseline,
    _run_candidate,
    compute_e0_mechanism_metrics,
)

# ---------------------------------------------------------------------------
# 冻结规格（E0-V2-2 合同）
# ---------------------------------------------------------------------------
FORMAL_GRID = [20, 50, 80, 110, 140, 170, 200]
FORMAL_SEEDS = list(range(601, 621))
PILOT_SEEDS = [201, 202, 203, 204, 205]
MAIN_METHODS = ["reliability_only", "bpso_rata_la", "cars_aada_rcla_candidate"]
DIAGNOSTIC_METHODS = ["local_only"]
OUT_DIR = os.path.join(_PROJECT, "results", "e0_v2", "e0_v2_2_formal")
SCEN_DIR = os.path.join(OUT_DIR, "scenarios")
RAW_PATH = os.path.join(OUT_DIR, "formal_raw.jsonl")
SUMMARY_PATH = os.path.join(OUT_DIR, "formal_summary.json")


def _load_yaml(rel: str) -> dict:
    with open(os.path.join(_PROJECT, rel), "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def run_formal() -> int:
    os.makedirs(SCEN_DIR, exist_ok=True)
    runner = MethodRunner()
    records = []
    n_runs = 0
    t_start = time.monotonic()

    for seed in FORMAL_SEEDS:
        super_cfg = build_e0_v2_super_scenario(seed=seed, n_max=E0_N_MAX)
        for n in FORMAL_GRID:
            cfg = e0_prefix_scenario(super_cfg, n)
            scen = materialize(cfg)
            derived = DerivedState(scen)
            scen_path = os.path.join(SCEN_DIR, "scenario_seed%d_n%d.yaml" % (seed, n))
            with open(scen_path, "w", encoding="utf-8") as fh:
                yaml.safe_dump(cfg, fh, allow_unicode=True, sort_keys=False)
            with open(scen_path, "rb") as fh:
                scen_hash = hashlib.sha256(fh.read()).hexdigest()

            for method in ALL_METHODS:
                if method == CANDIDATE_ID:
                    rec = _run_candidate(scen, derived)
                else:
                    rec = _run_baseline(runner, method, scen_path, scen, derived)
                record = {
                    "seed": seed,
                    "N": n,
                    "scenario_id": cfg.get("scenario_id"),
                    "scenario_hash16": scen_hash[:16],
                    "scenario_hash": scen_hash,
                    "paired_scenario_shared": True,
                    "formal_seed_used": True,
                    "pilot_seed_used": False,
                    "diagnostic_control": method in DIAGNOSTIC_METHODS,
                    **rec,
                }
                records.append(record)
                n_runs += 1

    elapsed_s = time.monotonic() - t_start

    # ---- 断言：pilot seeds 未混入（AC-3）----
    seeds_used = {r["seed"] for r in records}
    assert not seeds_used.intersection(PILOT_SEEDS), "pilot seeds leaked into formal"
    assert seeds_used == set(FORMAL_SEEDS), "formal seed set mismatch"

    # ---- 断言：paired 共享（AC-2）：同 (seed,N) 内 scenario_hash16 唯一一致 ----
    from collections import defaultdict
    by_cell = defaultdict(set)
    for r in records:
        by_cell[(r["seed"], r["N"])].add(r["scenario_hash16"])
    for cell, hashes in by_cell.items():
        assert len(hashes) == 1, "paired scenario hash mismatch at %s" % (cell,)

    with open(RAW_PATH, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    summary = _build_summary(records)
    summary["n_runs"] = n_runs
    summary["elapsed_seconds"] = round(elapsed_s, 2)
    summary["seeds"] = FORMAL_SEEDS
    summary["grid"] = FORMAL_GRID
    summary["methods_main"] = MAIN_METHODS
    summary["methods_diagnostic"] = DIAGNOSTIC_METHODS
    summary["formal_seeds_used"] = True
    summary["pilot_seeds_used"] = False
    summary["status_counts"] = _status_counts(records)
    summary["timeout_count"] = sum(1 for r in records if r["timed_out"])
    summary["method_error_count"] = sum(1 for r in records if r["method_status"] == "METHOD_ERROR")
    with open(SUMMARY_PATH, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)

    print("written:", RAW_PATH)
    print("written:", SUMMARY_PATH)
    print("n_runs:", n_runs, "| elapsed_s:", round(elapsed_s, 2),
          "| timeout:", summary["timeout_count"], "| error:", summary["method_error_count"])
    return 0


def _status_counts(records) -> dict:
    from collections import Counter
    return dict(Counter(r["method_status"] for r in records))


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return round(statistics.mean(vals), 6) if vals else None


def _std(vals):
    vals = [v for v in vals if v is not None]
    return round(statistics.pstdev(vals), 6) if len(vals) > 1 else None


def _build_summary(records) -> dict:
    from collections import defaultdict
    cells = defaultdict(list)
    for r in records:
        if r["diagnostic_control"]:
            continue  # 主统计不含 local_only（诊断控制）
        cells[(r["N"], r["method"])].append(r)

    core = ["TSSR", "Rbar_eff", "Ubar_eff", "V_R"]
    mech = ["V_F", "median_f_over_ellR", "max_G_over_F", "LI_dem", "edge_ratio"]
    per_cell = {}
    for key, rs in sorted(cells.items()):
        N, method = key
        entry = {"N": N, "method": method, "n_seeds": len(rs)}
        for c in core:
            entry[c + "_mean"] = _mean([r[c] for r in rs])
            entry[c + "_std"] = _std([r[c] for r in rs])
        for c in mech:
            entry[c + "_median"] = _mean([(r["mechanism"] or {}).get(c) for r in rs])
        per_cell["%s|%s" % (N, method)] = entry

    # paired 方法间差（同 N 同 seed）：AADA - BPSO / AADA - reliability_only
    by_seed_n = defaultdict(dict)
    for r in records:
        if r["diagnostic_control"]:
            continue
        by_seed_n[(r["seed"], r["N"])][r["method"]] = r
    paired = {}
    for (seed, N), mrec in sorted(by_seed_n.items()):
        aada = mrec.get("cars_aada_rcla_candidate")
        for other in ["bpso_rata_la", "reliability_only"]:
            o = mrec.get(other)
            if aada and o and aada["TSSR"] is not None and o["TSSR"] is not None:
                key = "%s|AADA-%s" % (N, other)
                paired.setdefault(key, []).append(aada["TSSR"] - o["TSSR"])
    paired_summary = {
        k: {"paired_mean_diff": _mean(v), "paired_std": _std(v),
            "direction_positive_count": sum(1 for x in v if x > 0), "n": len(v)}
        for k, v in sorted(paired.items())
    }
    return {"per_cell": per_cell, "paired_differences": paired_summary,
            "primary_outcome": "TSSR"}


def main() -> int:
    ap = argparse.ArgumentParser(description="E0-V2-2 Formal runner（E0-V2-2 合同）")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()
    global OUT_DIR, SCEN_DIR, RAW_PATH, SUMMARY_PATH
    if args.out_dir:
        OUT_DIR = os.path.join(_PROJECT, args.out_dir)
        SCEN_DIR = os.path.join(OUT_DIR, "scenarios")
        RAW_PATH = os.path.join(OUT_DIR, "formal_raw.jsonl")
        SUMMARY_PATH = os.path.join(OUT_DIR, "formal_summary.json")
    return run_formal()


if __name__ == "__main__":
    sys.exit(main())
