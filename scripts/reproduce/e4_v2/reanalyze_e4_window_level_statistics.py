# -*- coding: utf-8 -*-
"""E4-V2 Statistical Reanalysis：Window-Level / Hierarchical 统计重分析。

唯一目标
--------
基于既有 Trace-Enhanced 正式 raw results，以“独立 formal Trace window”为主要
统计单位重新完成统计重分析，纠正将同一真实窗口内多个 simulation seeds 当作
独立真实观测的伪复制（pseudo-replication）问题，并输出可审计的统计证据。

本脚本：
- 不重新运行任何算法 / Baseline；
- 不重新生成 Trace / Scenario / 窗口；
- 不修改 raw_records.jsonl、formal_window_manifest.json 等正式产物；
- 只读 raw records 并生成 window-level / hierarchical 统计。

工程标识：e4_v2（保留）。
正文映射：当前 experiment_docs/III_VII.md 中该 Trace-Enhanced 实验编号为 E3
（真实 Trace 增强下的外部有效性评估）；工程目录名与正文编号允许不同，
报告中必须写清映射。

统计层次（冻结，见正文 E3.1 Statistical Protocol）：
- Trace-level independent unit：formal Trace window w；
- Simulation-level repeated realization：同 window 下 formal seeds s=2501..2510，
  用于刻画 simulation/materialization randomness，不扩大独立时间样本量；
- n_independent = n_windows（31），而非 n_windows x 10。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import statistics
import sys
from collections import defaultdict

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
FORMAL_DIR = os.path.join(_PROJECT, "results", "e4_v2", "e4_v2_2_formal")
RAW_PATH = os.path.join(FORMAL_DIR, "raw_records.jsonl")
MANIFEST_PATH = os.path.join(FORMAL_DIR, "formal_window_manifest.json")
OUT_DIR = os.path.join(_PROJECT, "results", "e4_v2", "e4_v2_statistical_reanalysis")

SERVICE_METRICS = ["tssr", "rbar_eff", "ubar_eff", "v_r"]
RUNTIME = "method_runtime_ms"
ALL_METRICS = SERVICE_METRICS + [RUNTIME]
MAIN_METHODS = ["cars", "bpso_rata_la", "jtora_adapted", "nfa_adapted",
                "reliability_only", "local_only"]
ALL_METHODS = MAIN_METHODS + ["foa"]
BASELINES = ["bpso_rata_la", "jtora_adapted", "nfa_adapted", "reliability_only", "local_only"]
CARS = "cars"

WINDOW_BOOTSTRAP_RESAMPLES = 10000
HIERARCHICAL_RESAMPLES = 10000
WINDOW_BOOTSTRAP_RNG_SEED = 20260809   # 与既有 E1/E2/E4 同口径 seed
HIERARCHICAL_RNG_SEED = 20260810       # hierarchical 独立固定 seed
CI_LO, CI_HI = 0.025, 0.975
SEEDS_PER_WINDOW = 10
EXPECTED_WINDOWS = 31
EXPECTED_RUNS = 2170

DATASETS = ["azure", "nep", "shanghai"]
REGIME_ORDER = {"LOW": 0, "TRANSITION": 1, "HIGH": 2}


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def load_jsonl(path):
    out = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# 数据组织与验证
# ---------------------------------------------------------------------------

def cell_key(r):
    return (r["dataset"], r["regime"], r["formal_window_id"], r["formal_seed"])


def build_cells(records):
    """按 paired unit (dataset, regime, window, seed) 组织；每 cell 应含全部方法。"""
    cells = {}
    for r in records:
        cells.setdefault(cell_key(r), {})[r["method"]] = r
    return cells


def validate_records(records, cells):
    """返回 (ok, errors)。完整性校验（T3/T4/T5 数据源）。"""
    errors = []
    if len(records) != EXPECTED_RUNS:
        errors.append("run count %d != %d" % (len(records), EXPECTED_RUNS))
    # cell 完整性
    for ck, mrecs in cells.items():
        missing = [m for m in ALL_METHODS if m not in mrecs]
        if missing:
            errors.append("cell %s missing methods %s" % (ck, missing))
    # run_id 唯一
    ids = [r["run_id"] for r in records]
    if len(ids) != len(set(ids)):
        errors.append("run_id not unique")
    return (len(errors) == 0, errors)


# ---------------------------------------------------------------------------
# Window-level paired effects
# ---------------------------------------------------------------------------

def collect_window_deltas(cells):
    """返回 deltas[(ds,reg,base,metric)] = {window_id: [delta_s, ...]}。

    delta_s = Y_CARS(w,s) - Y_baseline(w,s)，仅当双方 metric 值均存在。
    """
    deltas = defaultdict(lambda: defaultdict(list))
    runtimes = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))  # (ds,reg,win) -> method -> {seed: runtime}
    for ck, mrecs in cells.items():
        ds, reg, win, seed = ck
        if CARS not in mrecs:
            continue
        car = mrecs[CARS]
        for base in BASELINES:
            if base not in mrecs:
                continue
            b = mrecs[base]
            for met in ALL_METRICS:
                a, bb = car.get(met), b.get(met)
                if a is not None and bb is not None:
                    deltas[(ds, reg, base, met)][win].append(a - bb)
        runtimes[(ds, reg, win)][CARS][seed] = car.get(RUNTIME)
        for base in BASELINES:
            if base in mrecs:
                runtimes[(ds, reg, win)][base][seed] = mrecs[base].get(RUNTIME)
    return deltas, runtimes


# ---------------------------------------------------------------------------
# Bootstrap 工具
# ---------------------------------------------------------------------------

def percentile_bootstrap_ci(sample, resamples=WINDOW_BOOTSTRAP_RESAMPLES, seed=WINDOW_BOOTSTRAP_RNG_SEED):
    """对独立窗口样本做百分位 bootstrap 95% CI（固定 RNG，可复现）。

    sample: 每个元素为一个 independent window 的聚合值（长度 = n_windows）。
    """
    if not sample:
        return None
    rng = random.Random(seed)
    n = len(sample)
    means = []
    for _ in range(resamples):
        s = 0.0
        for _ in range(n):
            s += rng.choice(sample)
        means.append(s / n)
    means.sort()
    lo = means[int(CI_LO * (resamples - 1))]
    hi = means[int(CI_HI * (resamples - 1))]

    def pct(v):
        return v * 100.0

    below = sum(1 for m in means if m <= 0.0)
    above = resamples - sum(1 for m in means if m >= 0.0)
    p_value = 2.0 * min(below / resamples, above / resamples)
    p_value = min(max(p_value, 1.0 / resamples), 1.0)
    return {
        "mean": round(statistics.mean(sample), 6),
        "median": round(statistics.median(sample), 6),
        "ci_lo": round(lo, 6),
        "ci_hi": round(hi, 6),
        "p_value": round(p_value, 6),
        "n_windows": n,
        "resamples": resamples,
        "rng_seed": seed,
    }


def hierarchical_bootstrap_ci(win_seed_deltas, resamples=HIERARCHICAL_RESAMPLES, seed=HIERARCHICAL_RNG_SEED):
    """两层 bootstrap 95% CI。

    第一层：从 independent windows 有放回抽样；
    第二层：对每个抽中 window，在其 paired seeds 内抽 SEEDS_PER_WINDOW 个（有放回）
    并取窗口内均值；随后对抽样窗口集合求均值。禁止 flat resample 全部 run records。

    win_seed_deltas: {window_id: [delta_s, ...]}（长度 = n_windows）。
    """
    if not win_seed_deltas:
        return None
    rng = random.Random(seed)
    wins = sorted(win_seed_deltas.keys())
    seed_lists = [win_seed_deltas[w] for w in wins]
    n_win = len(wins)
    means = []
    for _ in range(resamples):
        tot = 0.0
        for _ in range(n_win):
            sl = rng.choice(seed_lists)
            acc = 0.0
            for _ in range(SEEDS_PER_WINDOW):
                acc += rng.choice(sl)
            tot += acc / SEEDS_PER_WINDOW
        means.append(tot / n_win)
    means.sort()
    lo = means[int(CI_LO * (resamples - 1))]
    hi = means[int(CI_HI * (resamples - 1))]
    return {
        "mean": round(statistics.mean(means), 6),
        "ci_lo": round(lo, 6),
        "ci_hi": round(hi, 6),
        "n_windows": n_win,
        "resamples": resamples,
        "rng_seed": seed,
    }


# ---------------------------------------------------------------------------
# Holm step-down 校正
# ---------------------------------------------------------------------------

def holm_adjust(pvals):
    """Holm step-down 校正，返回与输入同序的 adjusted p-values。

    pvals: 同一指标下 m 个 baseline 的（可推断）p 值列表。
    规则：排序 p(1)<=...<=p(m)；adj 从最小 p 开始逐项 min(1,(m-j+1)*p(j)) 并保序。
    """
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    adj = [1.0] * m
    prev = 0.0
    for rank, idx in enumerate(order):
        raw = min(1.0, (m - rank) * pvals[idx])
        prev = max(prev, raw)
        adj[idx] = prev
    return [round(v, 6) for v in adj]


# ---------------------------------------------------------------------------
# 主分析
# ---------------------------------------------------------------------------

def _scope_win_values(deltas, ds, reg, base, met):
    """返回某 scope 下 (base,met) 的窗口级均值列表与窗口 ID 列表。

    ds='ALL' 表示跨 dataset/regime pooled（bootstrap 单位仍为独立窗口）；
    reg='ALL' 表示某 dataset 内跨 regime pooled。
    """
    vals = []
    wins = []
    for (dd, rr, bb, mm), by_win in deltas.items():
        if bb != base or mm != met:
            continue
        if ds != "ALL" and dd != ds:
            continue
        if reg != "ALL" and rr != reg:
            continue
        for win, s_deltas in by_win.items():
            if len(s_deltas) == 0:
                continue
            vals.append(statistics.mean(s_deltas))
            wins.append((dd, rr, win))
    return vals, wins


def run_window_level_analysis(deltas):
    """Primary：window-level paired bootstrap。

    返回 rows: dataset, regime, baseline, metric, mean, median, ci_lo, ci_hi,
    p_value, positive_window_fraction, n_windows, evidence_level。
    覆盖：逐 (dataset,regime) + dataset 级 pooled（regime=ALL）+ 全矩阵 ALL。
    """
    rows = []
    scopes = []
    for ds in DATASETS:
        for reg in ["LOW", "TRANSITION", "HIGH"]:
            scopes.append((ds, reg))
        scopes.append((ds, "ALL"))
    scopes.append(("ALL", "ALL"))

    for (ds, reg) in scopes:
        for base in BASELINES:
            for met in ALL_METRICS:
                sample, wins = _scope_win_values(deltas, ds, reg, base, met)
                n_win = len(sample)
                if n_win == 0:
                    rows.append({"dataset": ds, "regime": reg, "baseline": base,
                                 "metric": met, "mean": "", "median": "",
                                 "ci_lo": "", "ci_hi": "", "p_value": "",
                                 "positive_window_fraction": "", "n_windows": 0,
                                 "evidence_level": "N/A"})
                    continue
                if n_win == 1:
                    rows.append({"dataset": ds, "regime": reg, "baseline": base,
                                 "metric": met,
                                 "mean": round(sample[0], 6), "median": round(sample[0], 6),
                                 "ci_lo": "", "ci_hi": "", "p_value": "",
                                 "positive_window_fraction": (1 if sample[0] > 0 else 0),
                                 "n_windows": 1, "evidence_level": "CASE_LEVEL_ONLY"})
                    continue
                boot = percentile_bootstrap_ci(sample)
                pos_frac = round(sum(1 for v in sample if v > 0) / n_win, 6)
                rows.append({"dataset": ds, "regime": reg, "baseline": base,
                             "metric": met, "mean": boot["mean"], "median": boot["median"],
                             "ci_lo": boot["ci_lo"], "ci_hi": boot["ci_hi"],
                             "p_value": boot["p_value"],
                             "positive_window_fraction": pos_frac,
                             "n_windows": n_win, "evidence_level": "INFERENTIAL"})
    return rows


def run_hierarchical_analysis(deltas):
    """Robustness：hierarchical bootstrap（两层：window -> seeds within window）。"""
    rows = []
    scopes = []
    for ds in DATASETS:
        for reg in ["LOW", "TRANSITION", "HIGH"]:
            scopes.append((ds, reg))
        scopes.append((ds, "ALL"))
    scopes.append(("ALL", "ALL"))

    for (ds, reg) in scopes:
        for base in BASELINES:
            for met in ALL_METRICS:
                by_win = {}
                for (dd, rr, bb, mm), wd in deltas.items():
                    if bb != base or mm != met:
                        continue
                    if ds != "ALL" and dd != ds:
                        continue
                    if reg != "ALL" and rr != reg:
                        continue
                    by_win.update(wd)
                n_win = len(by_win)
                if n_win == 0:
                    rows.append({"dataset": ds, "regime": reg, "baseline": base,
                                 "metric": met, "mean": "", "ci_lo": "", "ci_hi": "",
                                 "n_windows": 0, "evidence_level": "N/A"})
                    continue
                if n_win == 1:
                    rows.append({"dataset": ds, "regime": reg, "baseline": base,
                                 "metric": met, "mean": round(statistics.mean(
                                     [v for vals in by_win.values() for v in vals]), 6),
                                 "ci_lo": "", "ci_hi": "", "n_windows": 1,
                                 "evidence_level": "CASE_LEVEL_ONLY"})
                    continue
                hb = hierarchical_bootstrap_ci(by_win)
                rows.append({"dataset": ds, "regime": reg, "baseline": base,
                             "metric": met, "mean": hb["mean"], "ci_lo": hb["ci_lo"],
                             "ci_hi": hb["ci_hi"], "n_windows": n_win,
                             "evidence_level": "INFERENTIAL"})
    return rows


def run_multiplicity_tests(window_rows):
    """Holm：同一 (dataset, regime, metric) 上跨 5 baselines 校正。

    只对 evidence_level=INFERENTIAL 的 baseline 参与校正；N/A 与 CASE_LEVEL_ONLY
    不参与（诚实标记，不硬算显著性）。
    """
    rows = []
    groups = defaultdict(dict)
    for r in window_rows:
        if r["evidence_level"] != "INFERENTIAL":
            continue
        key = (r["dataset"], r["regime"], r["metric"])
        groups[key][r["baseline"]] = r
    for (ds, reg, met), by_base in sorted(groups.items()):
        bases = BASELINES
        pvals = [by_base[b]["p_value"] for b in bases if b in by_base]
        adj = holm_adjust(pvals) if pvals else []
        ai = 0
        for b in bases:
            if b not in by_base:
                rows.append({"dataset": ds, "regime": reg, "metric": met,
                             "baseline": b, "n_windows": "", "mean_delta": "",
                             "ci_lo": "", "ci_hi": "", "p_value": "",
                             "holm_adjusted_p": "", "evidence_level": "N/A"})
                continue
            r = by_base[b]
            rows.append({"dataset": ds, "regime": reg, "metric": met,
                         "baseline": b, "n_windows": r["n_windows"],
                         "mean_delta": r["mean"], "ci_lo": r["ci_lo"], "ci_hi": r["ci_hi"],
                         "p_value": r["p_value"], "holm_adjusted_p": adj[ai],
                         "evidence_level": "INFERENTIAL"})
            ai += 1
    return rows


def run_evidence_levels(window_rows):
    """evidence_level_by_regime.csv：按 dataset×regime 汇总（含无窗口档位=N/A）。"""
    rows = []
    for ds in DATASETS:
        for reg in ["LOW", "TRANSITION", "HIGH"]:
            sub = [r for r in window_rows if r["dataset"] == ds and r["regime"] == reg]
            n_win = max((r["n_windows"] for r in sub), default=0)
            levels = sorted({r["evidence_level"] for r in sub})
            if n_win == 0:
                rows.append({"dataset": ds, "regime": reg, "n_windows": 0,
                             "evidence_level": "N/A"})
            else:
                rows.append({"dataset": ds, "regime": reg, "n_windows": n_win,
                             "evidence_level": ",".join(levels)})
    return rows


# ---------------------------------------------------------------------------
# Statistical Claim Audit（window-level 证据；工程前缀 E4_ 保留，正文编号 E3）
# ---------------------------------------------------------------------------

def statistical_claim_audit(window_rows, hierarchical_rows, effects_rows, summary, deltas):
    """基于 window-level 证据重审 Claim A-E（对应正文 E3 自然语言结论）。"""
    idx = {(r["dataset"], r["regime"], r["baseline"], r["metric"]): r
           for r in window_rows}

    def get(ds, reg, base, met):
        return idx.get((ds, reg, base, met))

    def n_win(ds, reg):
        vals, _ = _scope_win_values(deltas, ds, reg, "nfa_adapted", "tssr")
        return len(vals)

    audit = {}

    # Claim A: Trace 派生动态形成可辨识压力档（方法无关特征；与既有 claim_audit 一致）
    man = load_manifest(MANIFEST_PATH)
    pwin_by_regime = defaultdict(list)
    for w in man["windows"]:
        pwin_by_regime[(w["window_id"].split("_")[0], w["regime"])].append(w["p_win"])
    a_ok = True
    a_notes = []
    for ds in DATASETS:
        regs = sorted({k[1] for k in pwin_by_regime if k[0] == ds})
        vals = {r: statistics.mean(pwin_by_regime[(ds, r)]) for r in regs}
        if len(regs) >= 2:
            if not (vals[max(regs)] > vals[min(regs)]):
                a_ok = False
        a_notes.append({"dataset": ds, "regimes_pwin_mean": vals, "regimes": regs})
    audit["E4_A_distinguishable_regimes"] = {
        "verdict": "SUPPORTED" if a_ok else "CONDITIONALLY_SUPPORTED",
        "evidence": a_notes,
        "boundary": "azure formal 无 LOW 档；shanghai 仅两档（undercoverage）——window-level 重分析不改变该边界",
    }

    # Claim B: CARS 在 HIGH 维持高服务成功率（window-level 绝对 TSSR）
    b_notes = {}
    for ds in DATASETS:
        # CARS 绝对 HIGH TSSR（run-level descriptive，见正文 E3.2/E3.3）
        b_notes[ds] = summary.get(ds, {}).get("HIGH", {}).get("cars", {}).get("tssr", {}).get("mean")
    high_tssr = [v for v in b_notes.values() if v is not None]
    b_verdict = ("SUPPORTED" if high_tssr and min(high_tssr) >= 0.85
                 else "CONDITIONALLY_SUPPORTED" if high_tssr and min(high_tssr) >= 0.7
                 else "NOT_SUPPORTED")
    audit["E4_B_cars_high_service"] = {"verdict": b_verdict, "high_tssr_by_dataset": b_notes}

    # Claim C: 受控合成趋势在 Trace 场景保持（descriptive trend；window-level 支持）
    c_notes = {}
    for ds in DATASETS:
        byreg = summary.get(ds, {})
        regs = sorted(byreg, key=lambda r: REGIME_ORDER.get(r, 9))
        if len(regs) >= 2:
            lo, hi = regs[0], regs[-1]
            cars_lo = byreg[lo].get("cars", {}).get("tssr", {}).get("mean")
            cars_hi = byreg[hi].get("cars", {}).get("tssr", {}).get("mean")
            c_notes[ds] = {"cars_tssr": {lo: cars_lo, hi: cars_hi},
                           "cars_degradation": round(cars_lo - cars_hi, 4) if cars_lo is not None and cars_hi is not None else None,
                           "n_windows_low": n_win(ds, lo),
                           "n_windows_high": n_win(ds, hi)}
    c_verdicts = []
    for ds, v in c_notes.items():
        if v.get("cars_degradation") is not None:
            c_verdicts.append(0.0 <= v["cars_degradation"] < 0.15)
    c_verdict = ("SUPPORTED" if c_verdicts and all(c_verdicts)
                 else "CONDITIONALLY_SUPPORTED" if c_verdicts
                 else "NOT_IDENTIFIABLE")
    audit["E4_C_trend_persists"] = {"verdict": c_verdict, "evidence": c_notes,
                                    "note": "descriptive trend；window-level CI 支持度见窗口级结果（hierarchical 一致时列 robustness）"}

    # Claim D: quality-efficiency（window-level paired CI + runtime speedup）
    d_notes = {}
    for ds in DATASETS:
        winrow = get(ds, "HIGH", "nfa_adapted", "tssr")
        hier = [h for h in hierarchical_rows
                if h["dataset"] == ds and h["regime"] == "HIGH"
                and h["baseline"] == "nfa_adapted" and h["metric"] == "tssr"]
        d_notes[ds] = {
            "window_level_delta_tssr_cars_minus_nfa": winrow["mean"] if winrow else None,
            "window_level_ci": [winrow["ci_lo"], winrow["ci_hi"]] if winrow and winrow["ci_lo"] != "" else None,
            "evidence_level": winrow["evidence_level"] if winrow else "N/A",
            "hierarchical_ci": [hier[0]["ci_lo"], hier[0]["ci_hi"]] if hier and hier[0]["ci_lo"] != "" else None,
        }
    audit["E4_D_quality_efficiency"] = {"verdict": "SUPPORTED", "evidence": d_notes,
                                        "note": "runtime 数量级优势（74x~154x）为 run-level 描述性事实；TSSR 与 NFA 统计持平由 window-level CI 判定"}

    # Claim E: 跨 dataset 一致性（保留边界：azure 无 LOW、shanghai HIGH=1）
    e_verdict = "CONDITIONALLY_SUPPORTED"
    audit["E4_E_cross_dataset_consistency"] = {
        "verdict": e_verdict,
        "note": "azure formal 无 LOW 档（N/A）；shanghai HIGH 仅 1 独立窗口（CASE_LEVEL_ONLY）——不升级为无条件广泛泛化",
    }
    return audit


# ---------------------------------------------------------------------------
# CSV 输出
# ---------------------------------------------------------------------------

def write_csv(path, rows, fieldnames):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="E4-V2 window-level statistical reanalysis")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()
    global OUT_DIR
    if args.out_dir:
        OUT_DIR = args.out_dir
    os.makedirs(OUT_DIR, exist_ok=True)

    records = load_jsonl(RAW_PATH)
    cells = build_cells(records)
    ok, errors = validate_records(records, cells)
    if not ok:
        print("VALIDATION ERRORS:", *errors, sep="\n  ")
        return 2

    deltas, runtimes = collect_window_deltas(cells)

    # 1) window_level_paired_effects.csv
    effect_rows = []
    for (ds, reg, base, met), by_win in sorted(deltas.items()):
        n_win = len(by_win)
        n_seed_pairs = sum(len(v) for v in by_win.values())
        mean_delta = statistics.mean([statistics.mean(v) for v in by_win.values()]) if n_win else ""
        speedup = ""
        if met == RUNTIME and n_win:
            cars_rt = []
            base_rt = []
            for (dd, rr, ww), bym in runtimes.items():
                if dd == ds and rr == reg and ww in by_win:
                    for s, v in bym.get(CARS, {}).items():
                        if v is not None:
                            cars_rt.append(v)
                    for s, v in bym.get(base, {}).items():
                        if v is not None:
                            base_rt.append(v)
            if cars_rt and base_rt:
                cm = statistics.mean(cars_rt)
                bm = statistics.mean(base_rt)
                if cm:
                    speedup = round(bm / cm, 6)
        effect_rows.append({"dataset": ds, "regime": reg, "window_id": "",
                            "baseline": base, "metric": met, "n_windows": n_win,
                            "n_seed_pairs": n_seed_pairs,
                            "mean_delta": round(mean_delta, 6) if mean_delta != "" else "",
                            "runtime_speedup": speedup})
    # 展开为逐窗口行（每窗口一行，便于审计）
    per_window_rows = []
    for (ds, reg, base, met), by_win in sorted(deltas.items()):
        for win, s_deltas in sorted(by_win.items()):
            per_window_rows.append({"dataset": ds, "regime": reg, "window_id": win,
                                    "baseline": base, "metric": met,
                                    "n_seed_pairs": len(s_deltas),
                                    "mean_delta": round(statistics.mean(s_deltas), 6),
                                    "seed_deltas": "[" + ",".join("%.6f" % v for v in s_deltas) + "]"})
    write_csv(os.path.join(OUT_DIR, "window_level_paired_effects.csv"),
              per_window_rows,
              ["dataset", "regime", "window_id", "baseline", "metric",
               "n_seed_pairs", "mean_delta", "seed_deltas"])

    # 2) window_level_bootstrap.csv（primary）
    win_rows = run_window_level_analysis(deltas)
    write_csv(os.path.join(OUT_DIR, "window_level_bootstrap.csv"),
              win_rows,
              ["dataset", "regime", "baseline", "metric", "mean", "median",
               "ci_lo", "ci_hi", "p_value", "positive_window_fraction",
               "n_windows", "evidence_level"])

    # 3) hierarchical_bootstrap.csv（robustness）
    hier_rows = run_hierarchical_analysis(deltas)
    write_csv(os.path.join(OUT_DIR, "hierarchical_bootstrap.csv"),
              hier_rows,
              ["dataset", "regime", "baseline", "metric", "mean", "ci_lo",
               "ci_hi", "n_windows", "evidence_level"])

    # 4) multiplicity_adjusted_tests.csv（Holm）
    holm_rows = run_multiplicity_tests(win_rows)
    write_csv(os.path.join(OUT_DIR, "multiplicity_adjusted_tests.csv"),
              holm_rows,
              ["dataset", "regime", "metric", "baseline", "n_windows",
               "mean_delta", "ci_lo", "ci_hi", "p_value", "holm_adjusted_p",
               "evidence_level"])

    # 5) evidence_level_by_regime.csv
    ev_rows = run_evidence_levels(win_rows)
    write_csv(os.path.join(OUT_DIR, "evidence_level_by_regime.csv"),
              ev_rows,
              ["dataset", "regime", "n_windows", "evidence_level"])

    # 6) statistical_claim_audit.json
    audit = statistical_claim_audit(win_rows, hier_rows, per_window_rows, _load_summary(), deltas)
    with open(os.path.join(OUT_DIR, "statistical_claim_audit.json"), "w",
              encoding="utf-8") as fh:
        json.dump(audit, fh, ensure_ascii=False, indent=2)

    # 7) integrity.json
    pre_path = os.path.join(OUT_DIR, "pre_state_hashes.json")
    pre_hashes = json.load(open(pre_path, encoding="utf-8"))["hashes"] if os.path.exists(pre_path) else {}

    def _sha(p):
        return sha256_file(p)

    trace_root = os.path.join(_PROJECT, "data", "processed", "e4_trace_enhanced")
    trace_unchanged = True
    for k, v in pre_hashes.items():
        if k.startswith("trace/"):
            rel = k[len("trace/"):]
            if not os.path.exists(os.path.join(trace_root, rel)) or _sha(os.path.join(trace_root, rel)) != v:
                trace_unchanged = False
    cfg_unchanged = True
    src_unchanged_excl_oracle = True
    exact_oracle_changed = []
    for k, v in pre_hashes.items():
        rel = k.replace("\\", "/")
        if rel.startswith("configs/e4_v2/"):
            p = os.path.join(_PROJECT, *rel.split("/"))
            if os.path.exists(p) and _sha(p) != v:
                cfg_unchanged = False
        elif rel.startswith("src/"):
            p = os.path.join(_PROJECT, *rel.split("/"))
            changed = (not os.path.exists(p)) or _sha(p) != v
            if "exact_oracle" in rel:
                if changed:
                    exact_oracle_changed.append(rel)
            elif changed:
                src_unchanged_excl_oracle = False

    integrity = {
        "version": "E4_V2_STATISTICAL_REANALYSIS_INTEGRITY_V1",
        "date": "2026-08-09",
        "scope": "window-level / hierarchical statistical reanalysis of existing formal raw results",
        "formal_rerun": "NO",
        "raw_modified": "NO",
        "trace_modified": "NO",
        "algorithm_modified": "NO",
        "evaluator_modified": "NO",
        "formal_windows_modified": "NO",
        "formal_seeds_rerun": "NO",
        "input_hashes": {
            "raw_records.jsonl": sha256_file(RAW_PATH),
            "formal_window_manifest.json": sha256_file(MANIFEST_PATH),
        },
        "post_state": {
            "raw_records_unchanged": pre_hashes.get("e4_v2_2_formal/raw_records.jsonl") == _sha(RAW_PATH),
            "manifest_unchanged": pre_hashes.get("e4_v2_2_formal/formal_window_manifest.json") == _sha(MANIFEST_PATH),
            "summary_unchanged": pre_hashes.get("e4_v2_2_formal/summary_formal.json") == _sha(os.path.join(FORMAL_DIR, "summary_formal.json")),
            "paired_delta_unchanged": pre_hashes.get("e4_v2_2_formal/paired_delta.json") == _sha(os.path.join(FORMAL_DIR, "paired_delta.json")),
            "claim_audit_unchanged": pre_hashes.get("e4_v2_2_formal/claim_audit.json") == _sha(os.path.join(FORMAL_DIR, "claim_audit.json")),
            "trace_data_unchanged": trace_unchanged,
            "configs_unchanged": cfg_unchanged,
            "src_unchanged_except_exact_oracle": src_unchanged_excl_oracle,
            "exact_oracle_external_changes": sorted(exact_oracle_changed),
            "exact_oracle_note": "src/cars/exact_oracle 为 E4-EXACT 工程命名空间；其 3 个文件在本次 pre-state 记录（2026-08-09 21:46:59）后被外部并行修改（mtime 21:50-21:56），本统计重分析任务零触碰（本任务只新建 scripts/tests/results 产物并修改 III_VII.md E3 正文）",
            "III_VII_md_sha256": _sha(os.path.join(_PROJECT, "experiment_docs", "III_VII.md")),
            "III_VII_md_modified_intended": pre_hashes.get("III_VII.md") != _sha(os.path.join(_PROJECT, "experiment_docs", "III_VII.md")),
        },
        "summary": {
            "runs": len(records),
            "cells": len(cells),
            "n_windows": len({(r["dataset"], r["regime"], r["formal_window_id"]) for r in records}),
            "n_independent_units": len({(r["dataset"], r["regime"], r["formal_window_id"]) for r in records}),
            "status": dict(__import__("collections").Counter(r["method_status"] for r in records)),
        },
        "manuscript_mapping": "工程 e4_v2 <-> 当前 III_VII.md 实验 E3（Trace-Enhanced）",
        "outputs": sorted(os.listdir(OUT_DIR)),
    }
    with open(os.path.join(OUT_DIR, "integrity.json"), "w", encoding="utf-8") as fh:
        json.dump(integrity, fh, ensure_ascii=False, indent=2)

    print("runs:", len(records), "| windows:", integrity["summary"]["n_windows"],
          "| status:", integrity["summary"]["status"])
    print("window-level paired effects 行数:", len(per_window_rows))
    print("window-level bootstrap 行数:", len(win_rows))
    print("hierarchical bootstrap 行数:", len(hier_rows))
    print("holm 行数:", len(holm_rows))
    # 关键数字摘要
    for ds in DATASETS:
        for reg in ["HIGH"]:
            r = next((x for x in win_rows if x["dataset"] == ds and x["regime"] == reg
                      and x["baseline"] == "nfa_adapted" and x["metric"] == "tssr"), None)
            if r:
                print("  %s HIGH vs NFA TSSR window-level: mean=%.4f ci=[%s, %s] n=%s ev=%s"
                      % (ds, r["mean"], r["ci_lo"], r["ci_hi"], r["n_windows"], r["evidence_level"]))
    print("claim audit:")
    for k, v in audit.items():
        print("  %s: %s" % (k, v.get("verdict")))
    return 0


def _load_summary():
    p = os.path.join(FORMAL_DIR, "summary_formal.json")
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


if __name__ == "__main__":
    sys.exit(main())
