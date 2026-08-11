# -*- coding: utf-8 -*-
"""E4-EXACT-3 Formal 聚合（Tier-1/2/3 gap、match、paired bootstrap CI、Table 数据）。

依据：configs/e4_exact/e4_exact_formal_protocol.yaml §6（metrics/statistics：
unit = (regime, N, formal_seed)；paired bootstrap 95% CI）。

输入：results/e4_exact/e4_exact_3_formal/formal_raw_records.jsonl（20 条，方案 A）
输出：
  - results/e4_exact/e4_exact_3_formal/formal_aggregated.json
  - results/e4_exact/e4_exact_3_formal/table_e4_exact_1.csv（Table E4-Exact-1 数据）
  - results/e4_exact/e4_exact_3_formal/tier1_gap_by_instance.csv（逐实例 gap；禁只存均值）

**禁止**：读取/聚合 CARS 之外任何方法；删除 timeout/infeasible/error 实例；
把不可计算实例当缺失；按结果事后改口径。
"""

from __future__ import annotations

import csv
import json
import os
import random
import statistics
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
OUT_DIR = os.path.join(ROOT, "results", "e4_exact", "e4_exact_3_formal")
RAW = os.path.join(OUT_DIR, "formal_raw_records.jsonl")
AGG = os.path.join(OUT_DIR, "formal_aggregated.json")
TABLE_CSV = os.path.join(OUT_DIR, "table_e4_exact_1.csv")
INSTANCE_CSV = os.path.join(OUT_DIR, "tier1_gap_by_instance.csv")

BOOTSTRAP_SEED = 20260810
BOOTSTRAP_N = 10000
ALPHA = 0.05


def load_records() -> list:
    recs = []
    if not os.path.exists(RAW):
        sys.stderr.write("[FAIL] no formal raw records found\n")
        sys.exit(1)
    for line in open(RAW, encoding="utf-8"):
        line = line.strip()
        if line:
            recs.append(json.loads(line))
    return recs


def _mean(xs):
    return round(statistics.mean(xs), 6) if xs else None


def _bootstrap_ci(gaps: list) -> dict:
    """paired bootstrap 95% CI（重采样实例；固定 seed 确定性）。"""
    if len(gaps) < 2:
        return {"n": len(gaps), "mean": _mean(gaps), "ci95_low": None, "ci95_high": None}
    rng = random.Random(BOOTSTRAP_SEED)
    means = []
    k = len(gaps)
    for _ in range(BOOTSTRAP_N):
        sample = [gaps[rng.randrange(k)] for _ in range(k)]
        means.append(statistics.mean(sample))
    means.sort()
    lo = means[int(ALPHA / 2 * BOOTSTRAP_N)]
    hi = means[int((1 - ALPHA / 2) * BOOTSTRAP_N) - 1]
    return {"n": len(gaps), "mean": _mean(gaps), "ci95_low": round(lo, 6), "ci95_high": round(hi, 6)}


def main() -> int:
    recs = load_records()
    groups = {}
    for r in recs:
        groups.setdefault(r["n"], []).append(r)

    agg = {
        "experiment": "e4_exact_3_formal",
        "aggregation_version": "E4_EXACT_3_AGGREGATE_V1",
        "records_total": len(recs),
        "bootstrap": {"method": "paired bootstrap 95% CI (fixed seed)", "seed": BOOTSTRAP_SEED,
                      "n_resamples": BOOTSTRAP_N},
        "groups": {},
    }

    table_rows = []
    instance_rows = []
    for n in sorted(groups):
        items = groups[n]
        computable = []
        failures = {"timeout": 0, "error": 0}
        for r in items:
            if r.get("status") == "TIMEOUT":
                failures["timeout"] += 1
            elif r.get("status") == "ERROR":
                failures["error"] += 1
            m = r.get("metrics") or {}
            if m.get("computable"):
                computable.append((r, m))

        oracle_t1 = [m["tier1_gap"] + r["oracle"]["objective_tuple"][0]
                     for (r, m) in computable if r["oracle"]["objective_tuple"]]
        cars_t1 = [r["cars"]["tssr"] for (r, m) in computable]
        tier1_gaps = [m["tier1_gap"] for (r, m) in computable]
        first_tier_match = [m["tier1_match"] for (r, m) in computable]
        full_lex_match = [m["full_lex_match"] for (r, m) in computable]
        cond_t2 = [m["tier2_gap"] for (r, m) in computable if m["tier2_gap"] is not None]
        cond_t3 = [m["tier3_gap"] for (r, m) in computable if m["tier3_gap"] is not None]
        oracle_rt = [r["oracle"]["total_oracle_runtime_ms"] for (r, m) in computable]
        cars_rt = [r["cars"]["method_runtime_ms"] for (r, m) in computable
                   if r["cars"].get("method_runtime_ms") is not None]

        gap_ci = _bootstrap_ci(tier1_gaps) if tier1_gaps else {"n": 0, "mean": None,
                                                               "ci95_low": None, "ci95_high": None}

        agg["groups"][str(n)] = {
            "instances": len(items),
            "computable": len(computable),
            "failures": failures,
            "oracle_tier1_mean": _mean(oracle_t1),
            "cars_tier1_mean": _mean(cars_t1),
            "tier1_gap_mean": gap_ci["mean"],
            "tier1_gap_ci95": [gap_ci["ci95_low"], gap_ci["ci95_high"]],
            "first_tier_match_rate": round(statistics.mean(first_tier_match), 6) if first_tier_match else None,
            "conditional_tier2_gap_mean": _mean(cond_t2),
            "conditional_tier3_gap_mean": _mean(cond_t3),
            "full_lex_match_rate": round(statistics.mean(full_lex_match), 6) if full_lex_match else None,
            "oracle_runtime_ms_mean": _mean(oracle_rt),
            "cars_runtime_ms_mean": _mean(cars_rt),
        }

        table_rows.append({
            "N": n,
            "Oracle_Tier1": gap_ci["mean"] + _mean(cars_t1) if gap_ci["mean"] is not None and _mean(cars_t1) is not None else None,
            "CARS_Tier1": _mean(cars_t1),
            "Tier1_Gap": gap_ci["mean"],
            "First_Tier_Match_Rate": agg["groups"][str(n)]["first_tier_match_rate"],
            "Conditional_Tier2_Gap": agg["groups"][str(n)]["conditional_tier2_gap_mean"],
            "Conditional_Tier3_Gap": agg["groups"][str(n)]["conditional_tier3_gap_mean"],
            "Oracle_Runtime_ms": agg["groups"][str(n)]["oracle_runtime_ms_mean"],
            "CARS_Runtime_ms": agg["groups"][str(n)]["cars_runtime_ms_mean"],
        })
        for (r, m) in sorted(computable, key=lambda x: x[0]["formal_seed"]):
            instance_rows.append({
                "N": r["n"], "regime": r["regime"], "formal_seed": r["formal_seed"],
                "oracle_tssr": r["oracle"]["objective_tuple"][0],
                "cars_tssr": r["cars"]["tssr"],
                "tier1_gap": m["tier1_gap"],
                "tier1_match": m["tier1_match"],
                "full_lex_match": m["full_lex_match"],
            })

    with open(AGG, "w", encoding="utf-8") as fh:
        json.dump(agg, fh, ensure_ascii=False, indent=2)
    with open(TABLE_CSV, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(table_rows[0].keys()) if table_rows else ["N"])
        w.writeheader()
        for row in table_rows:
            w.writerow(row)
    with open(INSTANCE_CSV, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["N", "regime", "formal_seed", "oracle_tssr",
                                           "cars_tssr", "tier1_gap", "tier1_match",
                                           "full_lex_match"])
        w.writeheader()
        for row in instance_rows:
            w.writerow(row)

    print("aggregated", len(recs), "records into", len(agg["groups"]), "N-groups")
    for n in sorted(agg["groups"]):
        g = agg["groups"][str(n)]
        print("  N=%s computable=%d/%d tier1_gap=%s ci95=%s match_rate=%s full_lex=%s"
              % (n, g["computable"], g["instances"], g["tier1_gap_mean"],
                 g["tier1_gap_ci95"], g["first_tier_match_rate"], g["full_lex_match_rate"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
