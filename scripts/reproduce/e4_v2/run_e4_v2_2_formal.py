# -*- coding: utf-8 -*-
"""E4-V2-2 Formal runner（正式 Trace-enhanced 确认性评估）。

执行合同：E4_V2_2_FORMAL_PROTOCOL_V1 + E4_V2_ENVIRONMENT_SELECTED_V1（E4-V2-1 冻结）。

**授权守卫**：运行正式方法必须传 --authorize-formal-seeds（用户 E4-V2-2 授权）。
不传授权参数即执行 formal 方法运行 -> SystemExit。

**流程**：
  1) --freeze-manifest：首次访问 formal-test 分区，机械生成并冻结 formal_window_manifest
     （24-slot 非重叠窗口 -> frozen p_win -> E4-V2-1 冻结阈值分类 -> 每档按时间顺序取前 5；
     不足 5 档如实减少并记 FORMAL_REGIME_UNDERCOVERAGE）。此模式禁止运行任何方法。
  2) 正式运行：只接受冻结 manifest；按 (dataset, regime, window, seed, method) 确定顺序执行；
     每个 (window, seed) 只生成一次 canonical Scenario，全部 7 方法共享；timeout=30s；
     全部状态（SUCCESS/BUDGET_EXHAUSTED/TIMEOUT/METHOD_ERROR/...）完整保留；
     resume 仅跳过已完整落盘的 run_id，禁止重跑后二选一。

**禁止**：改阈值/改窗口/改 mapping/改算法/Baseline/timeout/Evaluator/指标；删不利结果；
预查看正式结果后调整 formal 设计；把 trace-enhanced 表述为真实 MEC 部署。

输出：results/e4_v2/e4_v2_2_formal/
  - formal_window_manifest.json（冻结）+ manifest_sha256.txt
  - scenarios/（每个 (window,seed) 一个共享场景）
  - raw_records.jsonl（全部正式运行）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys

import yaml

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(_PROJECT, "src"))
sys.path.insert(0, os.path.join(_PROJECT, "scripts", "reproduce", "e1_v2"))
sys.path.insert(0, os.path.join(_PROJECT, "scripts", "reproduce", "e4_v2"))

from cars.runner.runner import MethodRunner  # noqa: E402
from run_e4_v2_1_pilot import build_window_scenario, load_yaml, load_jsonl  # noqa: E402

# ---------------------------------------------------------------------------
# 冻结常量（E4_V2_ENVIRONMENT_SELECTED_V1；E4_V2_2_FORMAL_PROTOCOL_V1）
# ---------------------------------------------------------------------------
TRACE_ROOT = os.path.join(_PROJECT, "data", "processed", "e4_trace_enhanced")
OUT_DIR = os.path.join(_PROJECT, "results", "e4_v2", "e4_v2_2_formal")
ENV_SELECTED = os.path.join(_PROJECT, "configs", "e4_v2", "e4_v2_environment_selected.yaml")
FORMAL_PROTOCOL = os.path.join(_PROJECT, "configs", "e4_v2", "e4_v2_2_formal_protocol.yaml")
MANIFEST_PATH = os.path.join(OUT_DIR, "formal_window_manifest.json")

WINDOW_LEN = 24
FORMAL_SEEDS = [2501, 2502, 2503, 2504, 2505, 2506, 2507, 2508, 2509, 2510]
TIMEOUT = 30.0

MAIN_METHODS = ["cars", "bpso_rata_la", "jtora_adapted", "nfa_adapted",
                "reliability_only", "local_only"]
DIAGNOSTIC_METHODS = ["foa"]
ALL_METHODS = MAIN_METHODS + DIAGNOSTIC_METHODS

CONFIGS = {
    "cars": os.path.join(_PROJECT, "configs", "cars_v4", "cars_frozen_v4.yaml"),
    "bpso_rata_la": os.path.join(_PROJECT, "configs", "r6", "frozen_method_configs", "bpso_frozen.yaml"),
    "jtora_adapted": os.path.join(_PROJECT, "configs", "r6", "frozen_method_configs", "jtora_frozen.yaml"),
    "nfa_adapted": os.path.join(_PROJECT, "configs", "r6", "frozen_method_configs", "nfa_frozen.yaml"),
    "reliability_only": os.path.join(_PROJECT, "configs", "r6", "frozen_method_configs", "reliability_only_frozen.yaml"),
    "local_only": os.path.join(_PROJECT, "configs", "r6", "frozen_method_configs", "local_only_frozen.yaml"),
    "foa": os.path.join(_PROJECT, "configs", "r6", "frozen_method_configs", "foa_frozen.yaml"),
}


def frozen_thresholds():
    """从 E4_V2_ENVIRONMENT_SELECTED_V1 读取冻结阈值/档数/windows_per_regime。"""
    env = load_yaml(ENV_SELECTED)
    out = {}
    for ds in ["azure", "nep", "shanghai"]:
        d = env["datasets"][ds]
        out[ds] = {
            "regimes": list(d["available_regimes"]),
            "thresholds": dict(d["layer_a_thresholds"]),
            "windows_per_regime": d["formal_selection_rule"]["windows_per_regime"],
        }
    return out


def window_p_win(ds, w):
    if ds in ("azure", "shanghai"):
        return statistics.mean(r["workload_intensity"] for r in w)
    cp = [r["cpu_pressure"] for r in w if r["cpu_pressure"] is not None]
    return statistics.median(cp) if cp else 0.0


def classify(ds, p_win, th):
    if ds == "shanghai":
        return "LOW" if p_win <= th["p33"] else "HIGH"
    if p_win <= th["p33"]:
        return "LOW"
    if p_win <= th["p66"]:
        return "TRANSITION"
    return "HIGH"


def freeze_manifest():
    """首次访问 formal-test 分区；机械生成 formal_window_manifest（零方法运行）。"""
    os.makedirs(OUT_DIR, exist_ok=True)
    ths = frozen_thresholds()
    manifest = {"version": "E4_V2_2_FORMAL_WINDOW_MANIFEST_V1",
                "window_len_slots": WINDOW_LEN,
                "selection_rule": "frozen thresholds (E4-V2-1) + first-5 per regime by time order",
                "undercoverage_policy": "regime 不足 5 窗口则如实减少（FORMAL_REGIME_UNDERCOVERAGE Warning）",
                "windows": []}
    undercoverage = []
    for ds in ["azure", "nep", "shanghai"]:
        th = ths[ds]
        recs = load_jsonl(os.path.join(TRACE_ROOT, "splits", ds, f"{ds}_formal.jsonl"))
        wins = []
        for k in range(0, len(recs) - WINDOW_LEN + 1, WINDOW_LEN):
            w = recs[k:k + WINDOW_LEN]
            wins.append({
                "k": k,
                "window_id": f"{ds}_formal_win_{k // WINDOW_LEN:04d}",
                "start_slot": w[0]["slot_id"],
                "start_ts": w[0]["timestamp"],
                "end_ts": w[-1]["timestamp"],
                "p_win": round(window_p_win(ds, w), 6),
            })
        by_regime = {r: [] for r in th["regimes"]}
        for x in wins:
            x["regime"] = classify(ds, x["p_win"], th["thresholds"])
            by_regime[x["regime"]].append(x)
        for r in th["regimes"]:
            g = sorted(by_regime[r], key=lambda x: x["k"])
            take = min(len(g), th["windows_per_regime"])
            if len(g) < th["windows_per_regime"]:
                undercoverage.append({"dataset": ds, "regime": r,
                                      "available": len(g), "requested": th["windows_per_regime"]})
            for rank, x in enumerate(g[:take], start=1):
                x["selection_rank"] = rank
                x["selection_reason"] = "first-%d by time order (frozen rule)" % th["windows_per_regime"]
                manifest["windows"].append(x)
    manifest["undercoverage"] = undercoverage
    with open(MANIFEST_PATH, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    digest = hashlib.sha256(open(MANIFEST_PATH, "rb").read()).hexdigest()
    with open(os.path.join(OUT_DIR, "manifest_sha256.txt"), "w", encoding="utf-8") as fh:
        fh.write(digest + "\n")
    n_windows = len(manifest["windows"])
    print("formal windows:", n_windows)
    for ds in ["azure", "nep", "shanghai"]:
        cnt = {}
        for w in manifest["windows"]:
            if w["window_id"].startswith(ds):
                cnt[w["regime"]] = cnt.get(w["regime"], 0) + 1
        print("  %s: %s" % (ds, cnt))
    print("undercoverage:", undercoverage)
    print("manifest sha256:", digest)
    return manifest


def expected_runs(manifest):
    return len(manifest["windows"]) * len(FORMAL_SEEDS) * len(ALL_METHODS)


def run_id_of(ds, regime, window_id, seed, method):
    return "%s|%s|%s|%d|%s" % (ds, regime, window_id, seed, method)


def load_existing_run_ids():
    path = os.path.join(OUT_DIR, "raw_records.jsonl")
    ids = set()
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line:
                rec = json.loads(line)
                ids.add(rec.get("run_id"))
    return ids


def main() -> int:
    ap = argparse.ArgumentParser(description="E4-V2-2 Formal runner")
    ap.add_argument("--freeze-manifest", action="store_true", help="只冻结 formal_window_manifest（禁止运行方法）")
    ap.add_argument("--authorize-formal-seeds", action="store_true",
                    help="显式授权运行 formal seeds 2501-2510（用户 E4-V2-2 授权）")
    ap.add_argument("--resume", action="store_true", help="跳过已完整落盘的 run_id")
    ap.add_argument("--limit", type=int, default=None, help="限制运行数（调试/分片用；正式完整运行不传）")
    args = ap.parse_args()

    if args.freeze_manifest:
        m = freeze_manifest()
        print("EXPECTED_FORMAL_RUNS:", expected_runs(m))
        return 0

    # 正式运行路径
    if not args.authorize_formal_seeds:
        raise SystemExit("REFUSED: formal seeds 2501-2510 require --authorize-formal-seeds "
                         "(E4-V2-2 须用户授权；AUTHORIZED_TO_START_E4_V2_2_FORMAL = YES 当前)")
    if not os.path.exists(MANIFEST_PATH):
        raise SystemExit("REFUSED: formal_window_manifest.json missing (run --freeze-manifest first)")

    manifest = json.load(open(MANIFEST_PATH, encoding="utf-8"))
    expected = expected_runs(manifest)
    existing = load_existing_run_ids() if args.resume else set()
    print("EXPECTED_FORMAL_RUNS:", expected, "= %d windows x %d seeds x %d methods"
          % (len(manifest["windows"]), len(FORMAL_SEEDS), len(ALL_METHODS)))

    os.makedirs(os.path.join(OUT_DIR, "scenarios"), exist_ok=True)
    runner = MethodRunner()
    raw_path = os.path.join(OUT_DIR, "raw_records.jsonl")
    ran = 0
    with open(raw_path, "a", encoding="utf-8") as fh:
        for w in manifest["windows"]:
            ds = w["window_id"].split("_")[0]
            for seed in FORMAL_SEEDS:
                # 每个 (window, seed) 只生成一次 canonical Scenario
                sc = build_window_scenario(ds, w["p_win"], seed, materialized=False)
                sc["scenario_id"] = "e4v22_%s_%s_seed%d_n%d" % (
                    ds, w["window_id"], seed, len(sc["tasks"]))
                scen_path = os.path.join(OUT_DIR, "scenarios",
                                         "scenario_%s_%s_seed%d.yaml" % (ds, w["window_id"], seed))
                with open(scen_path, "w", encoding="utf-8") as sfh:
                    yaml.safe_dump(sc, sfh, allow_unicode=True, sort_keys=False)
                for mid in ALL_METHODS:
                    rid = run_id_of(ds, w["regime"], w["window_id"], seed, mid)
                    if rid in existing:
                        continue
                    mcfg = load_yaml(CONFIGS[mid])
                    rec = runner.run(method_id=mid, scenario_cfg_path=scen_path,
                                     method_config=mcfg, method_seed=mcfg["method_seed"],
                                     hard_timeout_seconds=TIMEOUT)
                    ev = rec.get("evaluator_output") or {}
                    sm = ev.get("system_metrics") or {}
                    out = {
                        "run_id": rid,
                        "dataset": ds,
                        "regime": w["regime"],
                        "formal_window_id": w["window_id"],
                        "formal_seed": seed,
                        "method": mid,
                        "start_slot": w["start_slot"],
                        "start_ts": w["start_ts"],
                        "end_ts": w["end_ts"],
                        "trace_driver_value": w["p_win"],
                        "n_tasks": len(sc["tasks"]),
                        "method_status": rec.get("method_status"),
                        "tssr": sm.get("tssr"),
                        "rbar_eff": sm.get("mean_effective_reliability"),
                        "ubar_eff": sm.get("mean_effective_utility"),
                        "v_r": sm.get("reliability_violation_rate"),
                        "method_runtime_ms": rec.get("method_runtime_ms"),
                        "total_wall_time_ms": rec.get("total_wall_time_ms"),
                        "runtime_censored": rec.get("runtime_censored", False),
                        "method_error": rec.get("method_error"),
                    }
                    fh.write(json.dumps(out, ensure_ascii=False) + "\n")
                    fh.flush()
                    ran += 1
                    if args.limit and ran >= args.limit:
                        print("limited runs:", ran)
                        return 0
    print("runs completed this invocation:", ran, "| total expected:", expected)
    return 0


if __name__ == "__main__":
    sys.exit(main())
