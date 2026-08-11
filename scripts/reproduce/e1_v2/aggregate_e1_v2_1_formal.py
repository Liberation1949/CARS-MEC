# -*- coding: utf-8 -*-
"""E1-V2-1 Formal 聚合（读取 raw_records.jsonl）。

输出：
- results/e1_v2/e1_v2_1_formal/summary_formal.json（mean±std per method per N）
- results/e1_v2/e1_v2_1_formal/paired_delta.json（CARS vs 各 baseline 的 paired
  ΔTSSR/ΔRbar/ΔUbar + 95% bootstrap CI，逐 N；重点 N=200）
- results/e1_v2/e1_v2_1_formal/table_e1_1.csv（N=200 汇总表）
- results/e1_v2/e1_v2_1_formal/claim_audit.json（outcome-neutral Claim 判定）

统计协议（E1_V2_PROTOCOL_V1 §7）：mean±std；paired 95% bootstrap CI（10000
resamples，rng 20260809）；timeout/error 完整进入（不删除）；8/10 completion
仅作 paired 推断门槛（<8/10 仍报告，不做 superiority inference）。
"""
from __future__ import annotations

import csv
import json
import os
import random
import sys

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OUT_DIR = os.path.join(_PROJECT, "results", "e1_v2", "e1_v2_1_formal")
RAW_PATH = os.path.join(OUT_DIR, "raw_records.jsonl")

MAIN_METHODS = ["cars", "bpso_rata_la", "jtora_adapted", "nfa_adapted",
                "reliability_only", "local_only"]
DIAGNOSTIC = ["foa"]
ALL_METHODS = MAIN_METHODS + DIAGNOSTIC
NS = [20, 50, 80, 110, 140, 170, 200]
METRICS = ["tssr", "rbar_eff", "ubar_eff"]
# 2026-08-09 用户批准：efficiency 主口径=算法执行时间 method_runtime_ms；
# total_wall_time_ms（端到端，含实验框架固定开销）保留为补充参考。
RUNTIME_MAIN = "method_runtime_ms"
RUNTIME_SUP = "total_wall_time_ms"
RNG_SEED = 20260809
RESAMPLES = 10000


def load_raw():
    recs = []
    with open(RAW_PATH, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                recs.append(json.loads(line))
    return recs


def mean_std(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None, None
    m = sum(vals) / len(vals)
    var = sum((v - m) ** 2 for v in vals) / len(vals)
    return round(m, 6), round(var ** 0.5, 6)


def bootstrap_ci(pairs, resamples=RESAMPLES, seed=RNG_SEED, alpha=0.05):
    """paired Δ 的 bootstrap 95% CI（mean）。pairs = [(x_cars, x_base), ...]。"""
    if len(pairs) < 2:
        return None, None, None
    rng = random.Random(seed)
    n = len(pairs)
    deltas = [a - b for a, b in pairs]
    means = []
    for _ in range(resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        s = sum(deltas[i] for i in idx) / n
        means.append(s)
    means.sort()
    lo = means[int(alpha / 2 * resamples)]
    hi = means[int((1 - alpha / 2) * resamples) - 1]
    return round(sum(deltas) / n, 6), round(lo, 6), round(hi, 6)


def main() -> int:
    recs = load_raw()
    # 1. summary_formal.json：mean±std per method per N
    summary = {}
    for m in ALL_METHODS:
        summary[m] = {}
        for n in NS:
            sub = [r for r in recs if r["method_id"] == m and r["n"] == n]
            n_completed = sum(1 for r in sub if r["method_status"] != "TIMEOUT" and r["method_status"] != "METHOD_ERROR")
            timeout = sum(1 for r in sub if r["method_status"] == "TIMEOUT")
            err = sum(1 for r in sub if r["method_status"] == "METHOD_ERROR")
            entry = {"n_completed": n_completed, "timeout": timeout, "method_error": err}
            for k in METRICS + [RUNTIME_MAIN, RUNTIME_SUP]:
                vals = [r[k] for r in sub]
                m_, s_ = mean_std(vals)
                entry[k + "_mean"] = m_
                entry[k + "_std"] = s_
            v_vals = [r["v_r"] for r in sub]
            vm, vs = mean_std(v_vals)
            entry["v_r_mean"], entry["v_r_std"] = vm, vs
            summary[m][str(n)] = entry

    with open(os.path.join(OUT_DIR, "summary_formal.json"), "w", encoding="utf-8") as fh:
        json.dump({"stage": "E1-V2-1 formal", "metrics": METRICS, "methods": ALL_METHODS,
                   "summary": summary}, fh, ensure_ascii=False, indent=2)

    # 2. paired_delta.json：CARS vs 各 baseline 逐 N
    paired = {}
    for base in MAIN_METHODS[1:]:
        paired[base] = {}
        for n in NS:
            cars_recs = {r["seed"]: r for r in recs if r["method_id"] == "cars" and r["n"] == n}
            base_recs = {r["seed"]: r for r in recs if r["method_id"] == base and r["n"] == n}
            shared = sorted(set(cars_recs) & set(base_recs))
            valid = [s for s in shared if cars_recs[s]["tssr"] is not None and base_recs[s]["tssr"] is not None]
            entry = {"n_paired": len(valid), "low_completion": len(valid) < 8}
            for k in METRICS:
                pairs = [(cars_recs[s][k], base_recs[s][k]) for s in valid
                         if cars_recs[s][k] is not None and base_recs[s][k] is not None]
                d, lo, hi = bootstrap_ci(pairs)
                entry["delta_" + k] = {"mean": d, "ci_lo": lo, "ci_hi": hi,
                                       "n_paired_metric": len(pairs)}
            paired[base][str(n)] = entry

    with open(os.path.join(OUT_DIR, "paired_delta.json"), "w", encoding="utf-8") as fh:
        json.dump({"rng_seed": RNG_SEED, "resamples": RESAMPLES, "paired": paired},
                  fh, ensure_ascii=False, indent=2)

    # 3. table_e1_1.csv：N=200 汇总
    with open(os.path.join(OUT_DIR, "table_e1_1.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Method", "TSSR", "Rbar_eff", "Ubar_eff", "V_R",
                    "method_runtime_ms", "total_wall_time_ms", "Completion", "Timeout"])
        for m in ALL_METHODS:
            e = summary[m]["200"]
            w.writerow([m, e["tssr_mean"], e["rbar_eff_mean"], e["ubar_eff_mean"],
                        e["v_r_mean"], e["method_runtime_ms_mean"], e["total_wall_time_ms_mean"],
                        e["n_completed"], e["timeout"]])

    # 4. claim_audit.json（outcome-neutral；Q1/Q2/Q3 判定）
    claim = {"Q1_scalability": {}, "Q2_pressure_zone": {}, "Q3_runtime": {}}
    for m in MAIN_METHODS[1:]:
        c20 = summary["cars"]["20"]["tssr_mean"]
        c200 = summary["cars"]["200"]["tssr_mean"]
        b20 = summary[m]["20"]["tssr_mean"]
        b200 = summary[m]["200"]["tssr_mean"]
        if c20 is None or c200 is None or b20 is None or b200 is None:
            claim["Q1_scalability"][m] = "INSUFFICIENT_COMPLETION"
            continue
        drop_c = c200 - c20
        drop_b = b200 - b20
        # paired @200
        p200 = paired[m]["200"]["delta_tssr"]
        supported = (p200["mean"] is not None and p200["mean"] > 0 and p200["ci_lo"] > 0)
        claim["Q1_scalability"][m] = {
            "cars_drop": round(drop_c, 4), "base_drop": round(drop_b, 4),
            "cars_slower_decline": drop_c > drop_b - 1e-9,
            "paired_delta_tssr_200": p200,
            "verdict_200": "supported" if supported else ("not_supported" if p200["ci_hi"] is not None and p200["ci_hi"] < 0 else "conditionally_supported"),
        }
    # Q2：优势出现的压力区间（按四区 paired 正向 seed 比例）
    for zone_name, zone_ns in (("LOW", [20, 50]), ("TRANSITION", [80, 110, 140]),
                               ("HIGH", [170]), ("NEAR_SATURATION", [200])):
        claim["Q2_pressure_zone"][zone_name] = {}
        for m in MAIN_METHODS[1:]:
            pos = 0
            tot = 0
            for n in zone_ns:
                e = paired[m].get(str(n), {})
                if e.get("delta_tssr", {}).get("mean") is not None:
                    tot += 1
                    if e["delta_tssr"]["mean"] > 0:
                        pos += 1
            claim["Q2_pressure_zone"][zone_name][m] = {
                "paired_delta_positive_n_points": pos, "n_points": tot}
    # Q3：runtime 对比 @200（主口径 method_runtime_ms；补充 total_wall_time_ms）
    for m in MAIN_METHODS[1:]:
        cr = summary["cars"]["200"][RUNTIME_MAIN + "_mean"]
        br = summary[m]["200"][RUNTIME_MAIN + "_mean"]
        cw = summary["cars"]["200"][RUNTIME_SUP + "_mean"]
        bw = summary[m]["200"][RUNTIME_SUP + "_mean"]
        claim["Q3_runtime"][m] = {
            "cars_method_runtime_ms_200": cr, "base_method_runtime_ms_200": br,
            "ratio_cars_over_base": (round(cr / br, 2) if br and br > 0 else None),
            "cars_total_wall_ms_200": cw, "base_total_wall_ms_200": bw}

    with open(os.path.join(OUT_DIR, "claim_audit.json"), "w", encoding="utf-8") as fh:
        json.dump(claim, fh, ensure_ascii=False, indent=2)

    # 打印核心表（N=200）
    print("=== Table E1-1 (N=200) ===")
    print("%-17s | %-7s %-7s %-7s %-7s %-8s %-9s | %s" % (
        "Method", "TSSR", "Rbar", "Ubar", "V_R", "alg_ms", "wall_ms", "Comp/TO"))
    for m in ALL_METHODS:
        e = summary[m]["200"]
        print("%-17s | %-7s %-7s %-7s %-7s %-8s %-9s | %d/%d" % (
            m, e["tssr_mean"], e["rbar_eff_mean"], e["ubar_eff_mean"],
            e["v_r_mean"], e["method_runtime_ms_mean"], e["total_wall_time_ms_mean"],
            e["n_completed"], e["timeout"]))
    print("\nwritten: summary_formal.json / paired_delta.json / table_e1_1.csv / claim_audit.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
