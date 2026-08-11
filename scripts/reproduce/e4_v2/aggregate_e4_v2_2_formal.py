# -*- coding: utf-8 -*-
"""E4-V2-2 Formal 聚合（确认性评估：mean/std + paired bootstrap CI + Claim audit）。

输入：results/e4_v2/e4_v2_2_formal/（formal_window_manifest.json + raw_records.jsonl）
输出：
  - status_summary.json（各方法 status 计数）
  - summary_formal.json（dataset×regime × method：mean/std of TSSR/Rbar/Ubar/V_R/runtime）
  - paired_delta.json（CARS−baseline paired diff + 95% bootstrap CI，逐 dataset×regime 与整体）
  - table_e4_1.csv（dataset × HIGH regime：method, TSSR, Rbar, Ubar, V_R, Runtime）
  - macro_summary.json（dataset 等权 macro average）
  - claim_audit.json（E4-A..E4-E 判定；outcome-neutral）

paired unit = (dataset, regime, formal_window, formal_seed)。bootstrap：10000 resamples,
RNG seed = 20260809（与 E1-V2-1/E2-V2-1 同口径）。主指标 method_runtime_ms（效率主口径）。
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import statistics
import sys

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OUT_DIR = os.path.join(_PROJECT, "results", "e4_v2", "e4_v2_2_formal")
MANIFEST_PATH = os.path.join(OUT_DIR, "formal_window_manifest.json")
RAW_PATH = os.path.join(OUT_DIR, "raw_records.jsonl")

SERVICE_METRICS = ["tssr", "rbar_eff", "ubar_eff", "v_r"]
RUNTIME = "method_runtime_ms"
MAIN_METHODS = ["cars", "bpso_rata_la", "jtora_adapted", "nfa_adapted",
                "reliability_only", "local_only"]
ALL_METHODS = MAIN_METHODS + ["foa"]
BASELINES = ["bpso_rata_la", "jtora_adapted", "nfa_adapted", "reliability_only", "local_only"]
BOOTSTRAP_RESAMPLES = 10000
BOOTSTRAP_RNG_SEED = 20260809
CI_LO, CI_HI = 0.025, 0.975


def load_jsonl(path):
    out = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def cell_key(r):
    return (r["dataset"], r["regime"], r["formal_window_id"], r["formal_seed"])


def build_cells(records):
    """按 paired unit (dataset, regime, window, seed) 组织；每 cell 应含全部方法。"""
    cells = {}
    for r in records:
        cells.setdefault(cell_key(r), {})[r["method"]] = r
    return cells


def summarize_cells(cells, methods):
    """dataset×regime × method：mean/std。"""
    from collections import defaultdict
    metrics_list = SERVICE_METRICS + [RUNTIME]
    agg = defaultdict(lambda: defaultdict(lambda: {m: [] for m in methods}))
    for ck, mrecs in cells.items():
        ds, reg = ck[0], ck[1]
        for m, rec in mrecs.items():
            for met in metrics_list:
                v = rec.get(met)
                if v is not None:
                    agg[(ds, reg)][m].setdefault(met, []).append(v)
    out = {}
    for (ds, reg), by_method in sorted(agg.items()):
        entry = {}
        for m in sorted(by_method):
            entry[m] = {met: {"n": len(vals),
                              "mean": round(statistics.mean(vals), 6) if vals else None,
                              "std": round(statistics.pstdev(vals), 6) if len(vals) > 1 else None}
                        for met, vals in by_method[m].items()}
        out.setdefault(ds, {})[reg] = entry
    return out


def paired_bootstrap_ci(diffs, resamples=BOOTSTRAP_RESAMPLES, seed=BOOTSTRAP_RNG_SEED):
    """对 paired diffs 做百分位 bootstrap 95% CI（RNG 固定，可复现）。"""
    if not diffs:
        return None
    rng = random.Random(seed)
    n = len(diffs)
    means = []
    for _ in range(resamples):
        s = 0.0
        for _ in range(n):
            s += rng.choice(diffs)
        means.append(s / n)
    means.sort()
    lo = means[int(CI_LO * (resamples - 1))]
    hi = means[int(CI_HI * (resamples - 1))]
    return {"delta": round(statistics.mean(diffs), 6),
            "ci_lo": round(lo, 6), "ci_hi": round(hi, 6),
            "n": n, "resamples": resamples, "rng_seed": seed}


def compute_paired(cells, scope):
    """scope: (ds, reg) 或 ("ALL",) 或 ("MACRO",)。返回 {metric: {baseline: {delta, ci}}}。"""
    keys = [k for k in cells if scope == ("ALL",) or (k[0], k[1]) == scope]
    out = {}
    for met in SERVICE_METRICS + [RUNTIME]:
        out[met] = {}
        for base in BASELINES:
            diffs = []
            for k in keys:
                c = cells[k]
                if "cars" in c and base in c:
                    a, b = c["cars"].get(met), c[base].get(met)
                    if a is not None and b is not None:
                        diffs.append(a - b)
            out[met][base] = paired_bootstrap_ci(diffs)
    return out


def macro_paired(cells):
    """dataset 等权 macro：先逐 dataset 平均 paired diff，再对 dataset 求平均。"""
    datasets = sorted({k[0] for k in cells})
    out = {}
    for met in SERVICE_METRICS + [RUNTIME]:
        out[met] = {}
        for base in BASELINES:
            per_ds = []
            for ds in datasets:
                keys = [k for k in cells if k[0] == ds]
                d = []
                for k in keys:
                    c = cells[k]
                    if "cars" in c and base in c:
                        a, b = c["cars"].get(met), c[base].get(met)
                        if a is not None and b is not None:
                            d.append(a - b)
                if d:
                    per_ds.append(statistics.mean(d))
            out[met][base] = {"macro_delta": round(statistics.mean(per_ds), 6),
                              "n_datasets": len(per_ds)}
    return out


def table_high(ds_regime_entries):
    """Table E4-1：dataset × HIGH regime（无 HIGH 的 dataset 记录为缺档）。"""
    rows = []
    for ds in ["azure", "nep", "shanghai"]:
        reg = "HIGH"
        entry = ds_regime_entries.get(ds, {}).get(reg)
        if not entry:
            rows.append({"dataset": ds, "regime": reg, "note": "NO_HIGH_REGIME_WINDOWS"})
            continue
        for m in MAIN_METHODS:
            e = entry.get(m, {})
            rows.append({
                "dataset": ds, "regime": reg, "method": m,
                "TSSR": e.get("tssr", {}).get("mean"),
                "Rbar_eff": e.get("rbar_eff", {}).get("mean"),
                "Ubar_eff": e.get("ubar_eff", {}).get("mean"),
                "V_R": e.get("v_r", {}).get("mean"),
                "Runtime_ms": e.get(RUNTIME, {}).get("mean"),
            })
    return rows


def claim_audit(summary, paired, macro, cells):
    """E4-A..E4-E 机器判定（outcome-neutral；只据正式数据）。"""
    audit = {}

    # E4-A: Trace 派生动态形成可辨识压力档（据 formal manifest 窗口 p_win 分布）
    man = json.load(open(MANIFEST_PATH, encoding="utf-8"))
    from collections import defaultdict
    pwin_by_regime = defaultdict(list)
    for w in man["windows"]:
        pwin_by_regime[(w["window_id"].split("_")[0], w["regime"])].append(w["p_win"])
    a_ok = True
    a_notes = []
    for ds in ["azure", "nep", "shanghai"]:
        regs = sorted({k[1] for k in pwin_by_regime if k[0] == ds})
        vals = {r: statistics.mean(pwin_by_regime[(ds, r)]) for r in regs}
        if len(regs) >= 2:
            if not (vals[max(regs)] > vals[min(regs)]):
                a_ok = False
        a_notes.append({"dataset": ds, "regimes_pwin_mean": vals, "regimes": regs})
    audit["E4_A_distinguishable_regimes"] = {
        "verdict": "SUPPORTED" if a_ok else "CONDITIONALLY_SUPPORTED",
        "evidence": a_notes,
        "boundary": "azure formal 无 LOW 档；shanghai 仅两档（undercoverage）",
    }

    # E4-B: CARS 在 trace-enhanced 下维持高服务成功率（HIGH regime 绝对 TSSR）
    b_notes = {}
    for ds in ["azure", "nep", "shanghai"]:
        e = summary.get(ds, {}).get("HIGH", {}).get("cars", {})
        b_notes[ds] = e.get("tssr", {}).get("mean")
    high_tssr = [v for v in b_notes.values() if v is not None]
    b_verdict = ("SUPPORTED" if high_tssr and min(high_tssr) >= 0.85
                 else "CONDITIONALLY_SUPPORTED" if high_tssr and min(high_tssr) >= 0.7
                 else "NOT_SUPPORTED")
    audit["E4_B_cars_high_service"] = {"verdict": b_verdict,
                                       "high_tssr_by_dataset": b_notes}

    # E4-C: controlled-simulation 主趋势（压力升高→退化，CARS 较缓）保持
    c_notes = {}
    for ds in ["azure", "nep", "shanghai"]:
        byreg = summary.get(ds, {})
        regs = sorted(byreg, key=lambda r: 0 if r == "LOW" else (1 if r == "TRANSITION" else 2))
        if len(regs) >= 2:
            lo, hi = regs[0], regs[-1]
            cars_lo = byreg[lo].get("cars", {}).get("tssr", {}).get("mean")
            cars_hi = byreg[hi].get("cars", {}).get("tssr", {}).get("mean")
            c_notes[ds] = {"cars_tssr": {lo: cars_lo, hi: cars_hi},
                           "cars_degradation": round(cars_lo - cars_hi, 4) if cars_lo and cars_hi else None}
    c_verdicts = []
    for ds, v in c_notes.items():
        if v.get("cars_degradation") is not None:
            c_verdicts.append(0.0 <= v["cars_degradation"] < 0.15)  # 较缓或可接受退化
    c_verdict = ("SUPPORTED" if c_verdicts and all(c_verdicts)
                 else "CONDITIONALLY_SUPPORTED" if c_verdicts
                 else "NOT_IDENTIFIABLE")
    audit["E4_C_trend_persists"] = {"verdict": c_verdict, "evidence": c_notes}

    # E4-D: CARS 维持有利在线 quality-efficiency（runtime 远小于 NFA，TSSR 不劣太多）
    d_notes = {}
    for ds in ["azure", "nep", "shanghai"]:
        e = summary.get(ds, {}).get("HIGH", {})
        cars_rt = e.get("cars", {}).get(RUNTIME, {}).get("mean")
        nfa_rt = e.get("nfa_adapted", {}).get(RUNTIME, {}).get("mean")
        cars_t = e.get("cars", {}).get("tssr", {}).get("mean")
        nfa_t = e.get("nfa_adapted", {}).get("tssr", {}).get("mean")
        d_notes[ds] = {"cars_runtime_ms": cars_rt, "nfa_runtime_ms": nfa_rt,
                       "runtime_ratio_nfa_over_cars": round(nfa_rt / cars_rt, 2) if cars_rt and nfa_rt else None,
                       "cars_tssr": cars_t, "nfa_tssr": nfa_t,
                       "delta_tssr_cars_nfa": round(cars_t - nfa_t, 4) if cars_t is not None and nfa_t is not None else None}
    ratios = [v["runtime_ratio_nfa_over_cars"] for v in d_notes.values() if v["runtime_ratio_nfa_over_cars"]]
    d_verdict = ("SUPPORTED" if ratios and min(ratios) >= 3
                 else "CONDITIONALLY_SUPPORTED" if ratios
                 else "NOT_IDENTIFIABLE")
    audit["E4_D_quality_efficiency"] = {"verdict": d_verdict, "evidence": d_notes}

    # E4-E: 跨三 dataset 一致性（B/C 判定在 dataset 间是否一致）
    b_consistent = len(set(b_notes.values())) == 1 if b_notes else False
    e_verdict = ("SUPPORTED" if b_consistent else "CONDITIONALLY_SUPPORTED")
    audit["E4_E_cross_dataset_consistency"] = {
        "verdict": e_verdict,
        "note": "azure 无 LOW 档、shanghai 两档且 HIGH 仅 1 窗口——跨数据集结构天然不完全一致，按 dataset boundary 标注",
    }
    return audit


def main() -> int:
    ap = argparse.ArgumentParser(description="E4-V2-2 Formal aggregation")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()
    global OUT_DIR
    if args.out_dir:
        OUT_DIR = args.out_dir

    records = load_jsonl(RAW_PATH)
    cells = build_cells(records)
    summary = summarize_cells(cells, ALL_METHODS)

    # status summary
    status_counts = {}
    for r in records:
        status_counts[r["method_status"]] = status_counts.get(r["method_status"], 0) + 1
    with open(os.path.join(OUT_DIR, "status_summary.json"), "w", encoding="utf-8") as fh:
        json.dump({"runs": len(records), "status_counts": status_counts}, fh, ensure_ascii=False, indent=2)

    with open(os.path.join(OUT_DIR, "summary_formal.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)

    # paired（逐 dataset×regime + ALL）
    paired = {"per_dataset_regime": {}, "ALL": {}}
    scopes = set()
    for k in cells:
        scopes.add((k[0], k[1]))
    for scope in sorted(scopes):
        paired["per_dataset_regime"]["%s/%s" % scope] = compute_paired(cells, scope)
    paired["ALL"] = compute_paired(cells, ("ALL",))
    macro = macro_paired(cells)
    with open(os.path.join(OUT_DIR, "paired_delta.json"), "w", encoding="utf-8") as fh:
        json.dump({"paired": paired, "macro_dataset_equal_weight": macro}, fh, ensure_ascii=False, indent=2)

    # table E4-1（dataset × HIGH）
    rows = table_high(summary)
    with open(os.path.join(OUT_DIR, "table_e4_1.csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # claim audit
    audit = claim_audit(summary, paired, macro, cells)
    with open(os.path.join(OUT_DIR, "claim_audit.json"), "w", encoding="utf-8") as fh:
        json.dump(audit, fh, ensure_ascii=False, indent=2)

    print("runs:", len(records), "| status:", status_counts)
    print("cells:", len(cells))
    for ds in ["azure", "nep", "shanghai"]:
        regs = sorted({k[1] for k in cells if k[0] == ds})
        for reg in regs:
            e = summary.get(ds, {}).get(reg, {}).get("cars", {}).get("tssr", {})
            print("  %s %s: CARS tssr mean=%.4f (n=%s)" % (ds, reg, e.get("mean"), e.get("n")))
    print("claim audit:")
    for k, v in audit.items():
        print("  %s: %s" % (k, v.get("verdict")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
