# -*- coding: utf-8 -*-
"""E4-V2-1 Pilot runner（Trace 动态区域识别 + Layer B sanity）。

执行合同：E4_V2_1_PILOT_PROTOCOL_V1 + E4_V2_TRACE_FIELD_MAPPING_V1。
唯一目标：从 calibration+pilot Trace 分区识别代表性压力区域（LOW/TRANSITION/HIGH，
或由数据直接支持的等价档），并冻结 E4-V2-2 Formal 的构造/窗口/判定/环境/采样规则。

**两层设计（用户冻结，顺序不可反转）**：
  Layer A（方法无关 Trace/Scenario 诊断）→ 冻结候选窗口 → Layer B（sanity 方法）。
  环境选择只能依据 Layer A；Layer B 只验证可运行性，不参与窗口排名。

**形式拒绝**：本脚本只允许读取 pilot 协议 allowed_partitions 列出的文件；
任何路径含 "formal" 立即 SystemExit（formal-test 零访问）。

**禁止**：写 data/；重新 preprocessing/normalization；把 NEP 全零 workload 字段当真实信号；
用 Trace 改写 λ_j / R_min / 算法参数；依据方法结果选窗口。
burstiness = NOT_AVAILABLE（burst_score 全 0 占位，不参与分类）。

输出：results/e4_v2/e4_v2_1_pilot/
  - trace_regime_diagnostics.csv（全部窗口 Layer A 诊断）
  - candidate_windows.json（冻结候选窗口）
  - scenarios/（候选窗口 Scenario，Schema V4 语义）
  - pilot_raw_records.jsonl（Layer B sanity，NOT_FORMAL）
  - pilot_sanity_summary.json / regime_selection.json
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
import sys

import yaml

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(_PROJECT, "src"))
sys.path.insert(0, os.path.join(_PROJECT, "scripts", "reproduce", "e1_v2"))
sys.path.insert(0, os.path.join(_PROJECT, "scripts", "reproduce", "e4_v2"))

from build_e1_v2_environment import build_e1_v2_environment, prefix_scenario  # noqa: E402
from cars.runner.runner import MethodRunner  # noqa: E402
from cars.simulator.scenario_materializer import materialize  # noqa: E402
from cars.simulator.derived_state import DerivedState  # noqa: E402

# ---------------------------------------------------------------------------
# 冻结常量（E4-V2-1；镜像到 e4_v2_environment_selected.yaml）
# ---------------------------------------------------------------------------
TRACE_ROOT = os.path.join(_PROJECT, "data", "processed", "e4_trace_enhanced")
PILOT_PROTOCOL_PATH = os.path.join(_PROJECT, "configs", "e4_v2", "e4_v2_1_pilot_protocol.yaml")
MAPPING_PATH = os.path.join(_PROJECT, "configs", "e4_v2", "e4_v2_trace_field_mapping.yaml")
OUT_DIR = os.path.join(_PROJECT, "results", "e4_v2", "e4_v2_1_pilot")

WINDOW_LEN = 24          # 窗口长度（槽数；azure=2h/nep=2h/shanghai=24h）
STRIDE = 24              # 非重叠连续窗口
N_MIN = 50               # 最小任务数（azure/shanghai 桥接）
N_MAX = 200              # 最大任务数（azure/shanghai 桥接）
CAP_REF = 0.12           # NEP cpu_pressure 参考（≈P95≈0.106）
CAP_FLOOR = 0.40         # NEP 容量缩放下限
CAP_ALPHA = 0.50         # NEP 容量缩放强度
DATASET_SEEDS = {"azure": 2401, "nep": 2402, "shanghai": 2403}  # 基础环境 seed（互斥新段）

# 区域判定：dataset-relative quantile（P33/P66 三档；shanghai 仅 P33 两档）
REGIME_RULE = {
    "azure": {"mode": "p33_p66"},
    "nep": {"mode": "p33_p66"},
    "shanghai": {"mode": "p33_only", "note": "workload 呈低尾+高压平台，不支持稳定 TRANSITION"},
}

# Layer B sanity 方法子集（用户推荐：CARS/BPSO/NFA/reliability_only）
LAYER_B_METHODS = ["cars", "bpso_rata_la", "nfa_adapted", "reliability_only"]
TIMEOUT = 30.0

CONFIGS = {
    "cars": os.path.join(_PROJECT, "configs", "cars_v4", "cars_frozen_v4.yaml"),
    "bpso_rata_la": os.path.join(_PROJECT, "configs", "r6", "frozen_method_configs", "bpso_frozen.yaml"),
    "nfa_adapted": os.path.join(_PROJECT, "configs", "r6", "frozen_method_configs", "nfa_frozen.yaml"),
    "reliability_only": os.path.join(_PROJECT, "configs", "r6", "frozen_method_configs", "reliability_only_frozen.yaml"),
}

CANDIDATES_PER_REGIME = 2   # 每档取 2 个代表窗口（median 最近 + P25 最近）

# 禁止在 Layer A 使用的 method-dependent / 不可用诊断
EXCLUDED_LAYER_A_DIAGNOSTICS = [
    "li_dem", "rho_dem", "burst_level", "workload_burstiness",
    "reliability_only_rate", "tssr", "method_runtime_ms",
]


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_jsonl(path):
    out = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def guard_partitions():
    """formal 分区强制拒绝：只允许 pilot 协议 allowed_partitions。"""
    proto = load_yaml(PILOT_PROTOCOL_PATH)
    allowed = []
    for ds, paths in proto["allowed_partitions"].items():
        for p in paths:
            allowed.append(p)
    for p in allowed:
        if "formal" in p.replace("\\", "/").lower():
            raise SystemExit("REFUSED: allowed_partitions must not contain formal; got %s" % p)
    # 运行时再逐文件拒绝
    return allowed


def allowed_file(path):
    if "formal" in path.replace("\\", "/").lower():
        raise SystemExit("REFUSED: formal partition access: %s (formal-test 零访问)" % path)
    return path


def window_p_win(ds, w):
    """窗口压力分数（只使用映射中合法真实字段）。"""
    if ds in ("azure", "shanghai"):
        return statistics.mean(r["workload_intensity"] for r in w)
    cp = [r["cpu_pressure"] for r in w if r["cpu_pressure"] is not None]
    return statistics.median(cp) if cp else 0.0


def build_window_scenario(ds, p_win, seed, materialized=True):
    """Trace→Scenario 构造（冻结规则；E4-V2-0 mapping 允许字段）。

    - azure/shanghai：N_t = 50 + round(150*p_win)（trace 驱动 workload 规模）
    - nep：N_t = 100（无 workload 信号）；cpu_pressure 驱动服务器可用容量
      F_j = F_j^base * max(0.40, 1 - 0.50*min(1, p_win/0.12))（容量侧；λ_j 不变）

    materialized=True：返回 T0 场景（Layer A 诊断用）；
    materialized=False：返回原始 cfg（mode=explicit，Layer B runner 内部 materialize）。
    """
    base = build_e1_v2_environment(seed=seed, n_max=N_MAX, s_f=1.0, fragility_profile="MEDIUM")
    if ds in ("azure", "shanghai"):
        n = min(N_MAX, max(N_MIN, round(N_MIN + (N_MAX - N_MIN) * p_win)))
        sc = prefix_scenario(base, n)
    else:
        n = 100
        sc = prefix_scenario(base, n)
        cap_scale = max(CAP_FLOOR, 1.0 - CAP_ALPHA * min(1.0, p_win / CAP_REF))
        for s in sc["servers"]:
            s["capacity_cycles_per_sec"] = int(round(s["capacity_cycles_per_sec"] * cap_scale))
    if materialized:
        sc = materialize(sc)
    return sc


def layer_a_diagnostics(ds, sc):
    """Layer A 场景诊断（全部决策前、方法无关）。"""
    d = DerivedState(sc)
    n = len(d.task_ids)
    m = len(d.server_ids)
    b_loc = [tl["b_loc"] for tl in d.task_local]
    local_feasible = sum(b_loc) / n
    edge_tot = 0
    sp = [0.0] * m
    per_task_min_floor = [0.0] * n
    for i in range(n):
        mn = None
        for j in range(m):
            ls = d.link(i, j)
            if ls is None or ls["e_rec"] != 1:
                continue
            edge_tot += 1
            ell = ls["ell_R"]
            sp[j] += ell
            if mn is None or ell < mn:
                mn = ell
        if mn is not None:
            per_task_min_floor[i] = mn
    edge_feasible = edge_tot / (n * m) if n * m else 0.0
    agg = sum(per_task_min_floor)
    cap = sum(s["F_j"] for s in d.server_state)
    dc = agg / cap if cap else 0.0
    F = [s["F_j"] for s in d.server_state]
    pn = [sp[j] / F[j] if F[j] > 0 else 0.0 for j in range(m)]
    mean_p = sum(pn) / m if m else 0.0
    var_p = sum((x - mean_p) ** 2 for x in pn) / m if m else 0.0
    return {
        "n": n,
        "local_feasible_ratio": round(local_feasible, 6),
        "edge_feasible_ratio": round(edge_feasible, 6),
        "recoverable_edge_ratio": round(edge_feasible, 6),
        "aggregate_min_floor_demand": round(agg, 3),
        "total_capacity": round(cap, 3),
        "demand_capacity_ratio": round(dc, 6),
        "per_server_pressure_max": round(max(pn), 6),
        "per_server_pressure_mean": round(mean_p, 6),
        "pressure_dispersion": round(math.sqrt(var_p), 6),
        "predecision_infeasible_ratio": round(len(d.predecision_infeasible) / n, 6),
    }


def classify_regime(ds, p_win, thresholds):
    if ds == "shanghai":
        return "LOW" if p_win <= thresholds["p33"] else "HIGH"
    if p_win <= thresholds["p33"]:
        return "LOW"
    if p_win <= thresholds["p66"]:
        return "TRANSITION"
    return "HIGH"


def quantile(xs, x):
    ss = sorted(xs)
    return ss[int(x * (len(ss) - 1))]


def run_layer_a():
    """Layer A：窗口构造 → trace 信号 → 场景诊断 → 区域分类 → 候选选择。"""
    proto = load_yaml(PILOT_PROTOCOL_PATH)
    allowed = guard_partitions()
    all_windows = []
    for ds in ["azure", "nep", "shanghai"]:
        paths = []
        for part in ["calibration", "pilot"]:
            paths.append(os.path.join(TRACE_ROOT, "splits", ds, f"{ds}_{part}.jsonl"))
        recs = []
        for p in paths:
            recs.extend(load_jsonl(allowed_file(p)))
        wins = []
        for k in range(0, len(recs) - WINDOW_LEN + 1, STRIDE):
            w = recs[k:k + WINDOW_LEN]
            p_win = window_p_win(ds, w)
            # 每个窗口构造场景并计算 Layer A 诊断（决策前、方法无关）
            sc = build_window_scenario(ds, p_win, DATASET_SEEDS[ds])
            diag = layer_a_diagnostics(ds, sc)
            wins.append({
                "trace_dataset": ds,
                "partition": "calibration" if k < 0 else "calibration_or_pilot",
                "window_id": f"{ds}_win_{k // STRIDE:04d}",
                "start_slot": w[0]["slot_id"],
                "start_ts": w[0]["timestamp"],
                "end_ts": w[-1]["timestamp"],
                "p_win": round(p_win, 6),
                **diag,
            })
        ps = [x["p_win"] for x in wins]
        if REGIME_RULE[ds]["mode"] == "p33_p66":
            th = {"p33": quantile(ps, 0.33), "p66": quantile(ps, 0.66)}
        else:
            th = {"p33": quantile(ps, 0.33)}
        for x in wins:
            x["regime"] = classify_regime(ds, x["p_win"], th)
        all_windows.append({"dataset": ds, "thresholds": th, "windows": wins})
    return all_windows, allowed


def select_candidates(per_dataset):
    """每数据集×每档取 CANDIDATES_PER_REGIME 个代表窗口（median 最近 + P25 最近）。"""
    candidates = []
    for ds_block in per_dataset:
        ds = ds_block["dataset"]
        regimes = sorted({x["regime"] for x in ds_block["windows"]})
        for reg in regimes:
            g = [x for x in ds_block["windows"] if x["regime"] == reg]
            gs = sorted(x["p_win"] for x in g)
            anchors = [quantile(gs, 0.50), quantile(gs, 0.25)]
            picked = []
            for a in anchors:
                pick = min(g, key=lambda x: abs(x["p_win"] - a))
                if pick["window_id"] not in [p["window_id"] for p in picked]:
                    picked.append(pick)
                if len(picked) >= CANDIDATES_PER_REGIME:
                    break
            for p in picked:
                p["role"] = "layer_b_candidate"
                candidates.append({"dataset": ds, "regime": reg, **p})
    return candidates


def write_scenario(ds, cand, scen_dir):
    os.makedirs(scen_dir, exist_ok=True)
    sc = build_window_scenario(ds, cand["p_win"], DATASET_SEEDS[ds], materialized=False)
    sc["scenario_id"] = f"e4v21_{ds}_{cand['window_id']}_n{len(sc['tasks'])}"
    path = os.path.join(scen_dir, f"scenario_{ds}_{cand['window_id']}.yaml")
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(sc, fh, allow_unicode=True, sort_keys=False)
    return path


def run_layer_b(candidates):
    """Layer B sanity：4 方法 × 候选窗口（NOT_FORMAL；统一 runner/Evaluator/timeout）。"""
    runner = MethodRunner()
    scen_dir = os.path.join(OUT_DIR, "scenarios")
    records = []
    for cand in candidates:
        ds = cand["dataset"]
        path = write_scenario(ds, cand, scen_dir)
        for mid in LAYER_B_METHODS:
            mcfg = load_yaml(CONFIGS[mid])
            rec = runner.run(method_id=mid, scenario_cfg_path=path, method_config=mcfg,
                             method_seed=mcfg["method_seed"], hard_timeout_seconds=TIMEOUT)
            ev = rec.get("evaluator_output") or {}
            sm = ev.get("system_metrics") or {}
            records.append({
                "NOT_FORMAL": True,
                "trace_dataset": ds,
                "window_id": cand["window_id"],
                "regime": cand["regime"],
                "method": mid,
                "method_status": rec.get("method_status"),
                "tssr": sm.get("tssr"),
                "rbar_eff": sm.get("rbar_eff"),
                "ubar_eff": sm.get("ubar_eff"),
                "v_r": sm.get("v_r"),
                "method_runtime_ms": rec.get("method_runtime_ms"),
                "total_wall_time_ms": rec.get("total_wall_time_ms"),
                "runtime_censored": rec.get("runtime_censored", False),
                "timeout": rec.get("runtime_censored", False),
                "error": rec.get("method_error"),
            })
    return records


def main() -> int:
    ap = argparse.ArgumentParser(description="E4-V2-1 Pilot runner (Layer A + Layer B)")
    ap.add_argument("--layer-b", action="store_true", help="运行 Layer B sanity（默认仅 Layer A）")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()
    global OUT_DIR
    if args.out_dir:
        OUT_DIR = args.out_dir

    os.makedirs(OUT_DIR, exist_ok=True)

    # ---- Layer A ----
    per_dataset, allowed = run_layer_a()
    rows = []
    for blk in per_dataset:
        for x in blk["windows"]:
            rows.append(x)
    csv_path = os.path.join(OUT_DIR, "trace_regime_diagnostics.csv")
    if rows:
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    candidates = select_candidates(per_dataset)
    cand_path = os.path.join(OUT_DIR, "candidate_windows.json")
    with open(cand_path, "w", encoding="utf-8") as fh:
        json.dump({"candidates": candidates,
                   "rule": {"window_len": WINDOW_LEN, "stride": STRIDE,
                            "regime_rule": REGIME_RULE,
                            "n_min": N_MIN, "n_max": N_MAX,
                            "nep_capacity": {"cap_ref": CAP_REF, "cap_floor": CAP_FLOOR,
                                             "cap_alpha": CAP_ALPHA},
                            "dataset_seeds": DATASET_SEEDS},
                   "thresholds": {blk["dataset"]: blk["thresholds"] for blk in per_dataset}},
                  fh, ensure_ascii=False, indent=2)

    # ---- Layer B ----
    records = []
    if args.layer_b:
        records = run_layer_b(candidates)
        with open(os.path.join(OUT_DIR, "pilot_raw_records.jsonl"), "w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        print("Layer B runs:", len(records))

    print("windows total:", sum(len(b["windows"]) for b in per_dataset))
    print("candidates:", len(candidates))
    print("csv:", csv_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
