# -*- coding: utf-8 -*-
"""E2-V2-1 Formal 聚合（读取 raw_records.jsonl；统计协议 E2_V2_FORMAL_PROTOCOL_V1 §7）。

输出：
- results/e2_v2/e2_v2_1_formal/summary_formal.json（mean±std 逐 CV_F × 方法）
- results/e2_v2/e2_v2_1_formal/paired_delta.json（CARS vs 各 baseline 的 paired
  ΔTSSR/ΔRbar/ΔUbar + 95% bootstrap CI，逐 CV_F；重点 CV=1.2）
- results/e2_v2/e2_v2_1_formal/table_e2_1.csv（端点比较 CV=0 vs CV=1.2 + degradation）
- results/e2_v2/e2_v2_1_formal/claim_audit.json（outcome-neutral Claim 判定辅助）

统计协议（E2_V2_FORMAL_PROTOCOL_V1 §7）：mean±std；paired 95% bootstrap CI
（10000 resamples，rng 20260809）；timeout/error 完整进入（不删除）；<8/10
completion 仅作 paired 推断门槛（仍报告，不做 superiority inference）。
degradation(Y) = (Y(CV=1.2) − Y(CV=0)) / Y(CV=0)。
"""
from __future__ import annotations

import csv
import json
import os
import random
import sys

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OUT_DIR = os.path.join(_PROJECT, "results", "e2_v2", "e2_v2_1_formal")
RAW_PATH = os.path.join(OUT_DIR, "raw_records.jsonl")

CV_GRID = [0.0, 0.3, 0.6, 0.9, 1.2]
METHODS = ["cars", "bpso_rata_la", "jtora_adapted", "nfa_adapted",
           "reliability_only", "local_only", "foa"]
BASELINES = ["bpso_rata_la", "jtora_adapted", "nfa_adapted",
             "reliability_only", "local_only"]
RESAMPLES = 10000
RNG_SEED = 20260809
METRICS = ["tssr", "rbar_eff", "ubar_eff"]


def load_raw():
    recs = []
    if os.path.exists(RAW_PATH):
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
    n = len(vals)
    mu = sum(vals) / n
    var = sum((x - mu) ** 2 for x in vals) / n
    return round(mu, 6), round(var ** 0.5, 6)


def bootstrap_ci(pairs, resamples=RESAMPLES, seed=RNG_SEED, alpha=0.05):
    """paired Δ 的 bootstrap 95% CI（mean）。pairs = [(x_cars, x_base), ...]。"""
    if len(pairs) < 2:
        return None, None, None
    deltas = [a - b for a, b in pairs]
    n = len(deltas)
    rng = random.Random(seed)
    means = []
    for _ in range(resamples):
        s = 0.0
        for _ in range(n):
            s += deltas[rng.randrange(n)]
        means.append(s / n)
    means.sort()
    lo = means[int(alpha / 2 * resamples)]
    hi = means[int((1 - alpha / 2) * resamples) - 1]
    return round(sum(deltas) / n, 6), round(lo, 6), round(hi, 6)


def main() -> int:
    global RAW_PATH, OUT_DIR
    import argparse
    ap = argparse.ArgumentParser(description="E2-V2-1 Formal 聚合")
    ap.add_argument("--raw", default=RAW_PATH, help="raw_records.jsonl 路径")
    ap.add_argument("--out-dir", default=OUT_DIR, help="输出目录")
    args = ap.parse_args()
    RAW_PATH, OUT_DIR = args.raw, args.out_dir
    recs = load_raw()
    if not recs:
        print("no raw records at", RAW_PATH)
        return 1

    # 1. summary_formal.json：mean±std 逐 (cv, method)
    summary = {}
    for cv in CV_GRID:
        summary[("%.1f" % cv).rstrip("0").rstrip(".") if cv != 0.0 else "0"] = {}
    for cv in CV_GRID:
        key = ("%.1f" % cv).rstrip("0").rstrip(".") if cv != 0.0 else "0"
        for m in METHODS:
            rows = [r for r in recs if r["method_id"] == m and abs(r["cv_f"] - cv) < 1e-9]
            cell = {}
            for met in METRICS:
                mu, sd = mean_std([r.get(met) for r in rows])
                cell[met] = {"mean": mu, "std": sd}
            cell["method_runtime_ms"] = {"mean": mean_std(
                [r.get("method_runtime_ms") for r in rows])[0]}
            cell["completion"] = {"n": len(rows),
                                  "timeout": sum(1 for r in rows if r.get("timed_out")),
                                  "error": sum(1 for r in rows if r.get("method_status") not in
                                               ("SUCCESS", "BUDGET_EXHAUSTED", "NO_IMPROVEMENT"))}
            summary[key][m] = cell
    with open(os.path.join(OUT_DIR, "summary_formal.json"), "w", encoding="utf-8") as fh:
        json.dump({"cv_grid": CV_GRID, "methods": METHODS, "summary": summary},
                  fh, ensure_ascii=False, indent=2)

    # 2. paired_delta.json：CARS vs 各 baseline 逐 CV_F
    paired = {}
    for base in BASELINES:
        paired[base] = {}
        for cv in CV_GRID:
            key = ("%.1f" % cv).rstrip("0").rstrip(".") if cv != 0.0 else "0"
            pairs = {met: [] for met in METRICS}
            seeds = sorted({r["seed"] for r in recs})
            for s in seeds:
                rc = [r for r in recs if r["method_id"] == "cars" and r["seed"] == s
                      and abs(r["cv_f"] - cv) < 1e-9]
                rb = [r for r in recs if r["method_id"] == base and r["seed"] == s
                      and abs(r["cv_f"] - cv) < 1e-9]
                if not rc or not rb:
                    continue
                for met in METRICS:
                    if rc[0].get(met) is not None and rb[0].get(met) is not None:
                        pairs[met].append((rc[0][met], rb[0][met]))
            n_paired = len(pairs["tssr"])
            entry = {"n_paired": n_paired, "low_completion": n_paired < 8}
            for met in METRICS:
                d, lo, hi = bootstrap_ci(pairs[met])
                entry["delta_" + met] = {"mean": d, "ci_lo": lo, "ci_hi": hi,
                                         "n_paired_metric": len(pairs[met])}
            paired[base][key] = entry
    with open(os.path.join(OUT_DIR, "paired_delta.json"), "w", encoding="utf-8") as fh:
        json.dump({"rng_seed": RNG_SEED, "resamples": RESAMPLES, "paired": paired},
                  fh, ensure_ascii=False, indent=2)

    # 3. table_e2_1.csv：端点比较 CV=0 vs CV=1.2 + degradation
    def get(cv, m, met):
        key = ("%.1f" % cv).rstrip("0").rstrip(".") if cv != 0.0 else "0"
        return (summary[key].get(m, {}).get(met, {}) or {}).get("mean")

    cols = ["method", "tssr_0", "tssr_high", "degradation_tssr",
            "rbar_0", "rbar_high", "degradation_rbar",
            "ubar_0", "ubar_high", "degradation_ubar",
            "runtime_ms_high", "completion_high", "timeout_high"]
    with open(os.path.join(OUT_DIR, "table_e2_1.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for m in METHODS:
            row = [m]
            for met, c0, ch in [("tssr", 0, 1), ("rbar_eff", 2, 3), ("ubar_eff", 4, 5)]:
                y0 = get(0.0, m, met)
                yh = get(1.2, m, met)
                deg = (yh - y0) / y0 if y0 not in (None, 0.0) else None
                row += [y0, yh, round(deg, 6) if deg is not None else None]
            key_h = "1.2"
            row += [summary[key_h].get(m, {}).get("method_runtime_ms", {}).get("mean"),
                    summary[key_h].get(m, {}).get("completion", {}).get("n"),
                    summary[key_h].get(m, {}).get("completion", {}).get("timeout")]
            w.writerow(row)

    # 4. claim_audit.json：outcome-neutral 辅助
    audit = {"q1_degradation_least": {}, "q2_advantage_zone": {},
             "q3_runtime": {}}
    # Q1：degradation_tssr 排序（CARS 退化是否最缓）
    degs = {}
    for m in METHODS:
        y0 = get(0.0, m, "tssr"); yh = get(1.2, m, "tssr")
        degs[m] = (yh - y0) / y0 if y0 not in (None, 0.0) else None
    audit["q1_degradation_least"]["degradation_tssr_by_method"] = degs
    audit["q1_degradation_least"]["cars_least"] = (
        min(degs.items(), key=lambda kv: (kv[1] is None, kv[1]))[0] == "cars"
        if any(v is not None for v in degs.values()) else None)
    # Q2：CV=1.2 paired 正向
    audit["q2_advantage_zone"]["paired_delta_tssr_at_1_2"] = {
        base: paired[base]["1.2"].get("delta_tssr") for base in BASELINES}
    # Q3：runtime@1.2
    audit["q3_runtime"]["method_runtime_ms_at_1_2"] = {
        m: summary["1.2"].get(m, {}).get("method_runtime_ms", {}).get("mean")
        for m in METHODS}
    with open(os.path.join(OUT_DIR, "claim_audit.json"), "w", encoding="utf-8") as fh:
        json.dump(audit, fh, ensure_ascii=False, indent=2)

    # 打印可读表
    print("=== Table E2-1（CV=0 vs CV=1.2；3 主指标 degradation）===")
    print("%-16s | %-9s %-9s %-9s | %-9s %-9s %-9s | %-10s" % (
        "method", "TSSR@0", "TSSR@1.2", "degTSSR", "Rbar@0", "Rbar@1.2", "degRbar", "runt@1.2"))
    for m in METHODS:
        y0 = get(0.0, m, "tssr"); yh = get(1.2, m, "tssr")
        dgt = (yh - y0) / y0 if y0 not in (None, 0.0) else None
        r0 = get(0.0, m, "rbar_eff"); rh = get(1.2, m, "rbar_eff")
        dgr = (rh - r0) / r0 if r0 not in (None, 0.0) else None
        rt = summary["1.2"].get(m, {}).get("method_runtime_ms", {}).get("mean")
        print("%-16s | %-9s %-9s %-9s | %-9s %-9s %-9s | %-10s" % (
            m, y0, yh, round(dgt, 6) if dgt is not None else None,
            r0, rh, round(dgr, 6) if dgr is not None else None, rt))
    print("\nwritten: summary_formal.json / paired_delta.json / table_e2_1.csv / claim_audit.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
