# -*- coding: utf-8 -*-
"""E1-3 Stage 3 Formal aggregation（独立脚本；统计语义与原始 runner 内嵌版一致）。

输入：results/e1_3_budget/budget_formal/formal_raw.jsonl + frozen 配置
      configs/e1_3_budget/e1_3_budget_formal_frozen.yaml；
输出：results/e1_3_budget/budget_formal/formal_summary.json。

统计计划（Stage-2 预注册冻结；仅执行不修改）：
  - per_method_per_multiplier：mean ± std over seeds（TSSR/Rbar_eff/Ubar_eff/V_R/
    T_alg/consumed），timeout 计数与状态集合；
  - paired_deltas：同 seed 的 ΔTSSR（1×−0.5×、2×−1×、4×−2×、4×−1×）与
    4× vs CARS 的 ΔTSSR（mean ± std，含逐 seed 列表）；
  - cars_reference：CARS 固定参考（不参与 budget sweep）汇总。

用法：
  python scripts/reproduce/e1_3_budget/aggregate_e1_3_budget_formal.py
"""
from __future__ import annotations

import json
import os
import sys

import yaml

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(_PROJECT, "src"))

FROZEN_CONFIG = os.path.join(_PROJECT, "configs", "e1_3_budget", "e1_3_budget_formal_frozen.yaml")
OUT_DIR = os.path.join(_PROJECT, "results", "e1_3_budget", "budget_formal")
RAW_PATH = os.path.join(OUT_DIR, "formal_raw.jsonl")
SUMMARY_PATH = os.path.join(OUT_DIR, "formal_summary.json")


def _mean(xs):
    vals = [x for x in xs if x is not None]
    return round(sum(vals) / len(vals), 6) if vals else None


def _std(xs):
    import statistics
    vals = [x for x in xs if x is not None]
    return round(statistics.pstdev(vals), 6) if vals else None


def build_formal_summary(raw, frozen):
    """从 raw records 构建 formal summary（统计语义与原始 runner 内嵌版一致）。"""
    mults = frozen["methods"]["budget_multipliers"]
    summary = {"per_method_per_multiplier": {}, "cars_reference": {}, "paired_deltas": {}}
    for method in frozen["methods"]["scanned"]:
        summary["per_method_per_multiplier"][method] = {}
        for mult in mults:
            rows = [r for r in raw if r["method"] == method and r["budget_multiplier"] == mult]
            q = {"tssr": _mean([r["tssr"] for r in rows]),
                 "tssr_std": _std([r["tssr"] for r in rows]),
                 "rbar_eff": _mean([r["rbar_eff"] for r in rows]),
                 "ubar_eff": _mean([r["ubar_eff"] for r in rows]),
                 "v_r": _mean([r["v_r"] for r in rows]),
                 "t_alg_ms": _mean([r["t_alg_ms"] for r in rows]),
                 "consumed": _mean([r["actual_consumed_search_evaluations"] for r in rows]),
                 "n": len(rows),
                 "timeout": sum(1 for r in rows if r["timeout"]),
                 "status": sorted({r["result_status"] for r in rows})}
            summary["per_method_per_multiplier"][method][str(mult)] = q
        # paired deltas（同 seed）
        def paired_delta(a, b, metric):
            da = {r["seed"]: r[metric] for r in raw if r["method"] == method and r["budget_multiplier"] == a}
            db = {r["seed"]: r[metric] for r in raw if r["method"] == method and r["budget_multiplier"] == b}
            d = [db[s] - da[s] for s in da if s in db and da[s] is not None and db[s] is not None]
            return d
        summary["paired_deltas"][method] = {}
        for (a, b, label) in [(0.5, 1.0, "1x-0.5x"), (1.0, 2.0, "2x-1x"), (2.0, 4.0, "4x-2x"), (1.0, 4.0, "4x-1x")]:
            d = paired_delta(a, b, "tssr")
            summary["paired_deltas"][method][label] = {
                "delta_tssr_mean": _mean(d),
                "delta_tssr_std": _std(d),
                "n_pairs": len(d),
            }
    # CARS reference
    cars = [r for r in raw if r["method"] == "cars"]
    summary["cars_reference"] = {
        "tssr": _mean([r["tssr"] for r in cars]),
        "tssr_std": _std([r["tssr"] for r in cars]),
        "rbar_eff": _mean([r["rbar_eff"] for r in cars]),
        "ubar_eff": _mean([r["ubar_eff"] for r in cars]),
        "v_r": _mean([r["v_r"] for r in cars]),
        "t_alg_ms": _mean([r["t_alg_ms"] for r in cars]),
        "n": len(cars),
        "timeout": sum(1 for r in cars if r["timeout"]),
        "status": sorted({r["result_status"] for r in cars}),
    }
    # 4x vs CARS paired（对每个 baseline 4x）
    for method in frozen["methods"]["scanned"]:
        b4 = {r["seed"]: r for r in raw if r["method"] == method and r["budget_multiplier"] == 4.0}
        cc = {r["seed"]: r for r in raw if r["method"] == "cars"}
        common = sorted(set(b4) & set(cc))
        d = [b4[s]["tssr"] - cc[s]["tssr"] for s in common
             if b4[s]["tssr"] is not None and cc[s]["tssr"] is not None]
        summary["paired_deltas"][method]["4x_vs_cars_tssr"] = {
            "delta_tssr_mean": _mean(d), "delta_tssr_std": _std(d), "n_pairs": len(d),
            "delta_tssr_list": [round(x, 4) for x in d],
        }
    return summary


def main() -> int:
    if not os.path.exists(RAW_PATH):
        print("raw 缺失（先运行 formal runner）：%s" % RAW_PATH)
        return 2
    frozen = yaml.safe_load(open(FROZEN_CONFIG, encoding="utf-8"))
    raw = [json.loads(line) for line in open(RAW_PATH, encoding="utf-8")]
    summary = build_formal_summary(raw, frozen)
    with open(SUMMARY_PATH, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2, sort_keys=True)
    print("summary ->", SUMMARY_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
