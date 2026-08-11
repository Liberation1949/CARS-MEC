# -*- coding: utf-8 -*-
"""E4-V2-1 Pilot 聚合（Layer A + Layer B → 冻结输出）。

输入（results/e4_v2/e4_v2_1_pilot/）：
  - trace_regime_diagnostics.csv（Layer A 全部窗口诊断）
  - candidate_windows.json（冻结候选窗口 + 阈值 + 规则）
  - pilot_raw_records.jsonl（Layer B sanity，NOT_FORMAL）
输出：
  - pilot_sanity_summary.json（Layer B 汇总：status/timeout/error/TSSR 分组 + 可辨识检查）
  - regime_selection.json（冻结区域结构：regimes/thresholds/selected windows/formal rule）
  - integrity.json（本阶段完整性记录；由 E4-V2-1 关闭时写入）

NOT_FORMAL：全部 Pilot 结果不进入论文正式均值。
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
PILOT_DIR = os.path.join(_PROJECT, "results", "e4_v2", "e4_v2_1_pilot")


def load_jsonl(path):
    out = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def load_csv_rows(path):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def sanity_summary(records):
    """Layer B 汇总（NOT_FORMAL；不参与正式均值）。"""
    from collections import defaultdict
    by = defaultdict(list)
    for r in records:
        by[(r["trace_dataset"], r["regime"], r["method"])].append(r)
    per_cell = {}
    for k, recs in sorted(by.items()):
        tssr = [x["tssr"] for x in recs if x["tssr"] is not None]
        per_cell["/".join(k)] = {
            "n": len(recs),
            "tssr_mean": round(statistics.mean(tssr), 6) if tssr else None,
            "tssr_values": tssr,
        }
    # 可辨识性检查（sanity 层面）
    windows = defaultdict(dict)
    for r in records:
        windows[(r["trace_dataset"], r["window_id"])][r["method"]] = r["tssr"]
    identical = 0
    for w, m in windows.items():
        vals = [v for v in m.values() if v is not None]
        if len(set(round(x, 4) for x in vals)) <= 1:
            identical += 1
    status_counts = {}
    for r in records:
        status_counts[r["method_status"]] = status_counts.get(r["method_status"], 0) + 1
    return {
        "NOT_FORMAL": True,
        "runs": len(records),
        "status_counts": status_counts,
        "timeout_count": sum(1 for r in records if r["timeout"]),
        "error_count": sum(1 for r in records if r.get("error")),
        "windows_with_all_methods_identical_tssr": identical,
        "windows_total": len(windows),
        "per_dataset_regime_method": per_cell,
        "notes": [
            "BUDGET_EXHAUSTED 为方法内部预算耗尽（正常状态；非 timeout/error）",
            "sanity 仅验证环境可运行性与可辨识性；不参与窗口排名/环境选择",
        ],
    }


def regime_selection(candidates, thresholds):
    """冻结区域结构（Layer A 结果 + formal 确定性选择规则）。"""
    from collections import defaultdict
    by = defaultdict(list)
    for c in candidates:
        by[c["dataset"]].append(c)
    datasets = {}
    for ds in ["azure", "nep", "shanghai"]:
        cands = sorted(by.get(ds, []), key=lambda x: (x["regime"], x["window_id"]))
        regimes = sorted({c["regime"] for c in cands})
        datasets[ds] = {
            "available_regimes": regimes,
            "thresholds": thresholds.get(ds, {}),
            "selected_pilot_windows": [
                {"window_id": c["window_id"], "regime": c["regime"],
                 "p_win": c["p_win"], "n": c["n"],
                 "demand_capacity_ratio": c["demand_capacity_ratio"],
                 "start_ts": c["start_ts"], "end_ts": c["end_ts"]}
                for c in cands
            ],
            "formal_selection_rule": _formal_rule(ds, thresholds.get(ds, {})),
        }
    return {
        "status": "FROZEN",
        "window_len": 24,
        "formal_windows_per_regime": 5,
        "datasets": datasets,
    }


def _formal_rule(ds, th):
    """Formal 确定性选择规则（冻结；E4-V2-2 应用于 formal 分区；不得提前查看结果）。"""
    if ds == "shanghai":
        return {
            "rule": "formal partition -> contiguous non-overlapping 24-slot windows -> "
                    "p_win (median cpu_pressure for nep; mean normalized workload_intensity else) "
                    "-> classify by FROZEN pilot thresholds (p33) -> select first 5 windows by "
                    "time order per regime (LOW/HIGH)",
            "thresholds": th,
            "note": "shanghai 仅两档（LOW/HIGH）；不支持稳定 TRANSITION（如实冻结）",
        }
    return {
        "rule": "formal partition -> contiguous non-overlapping 24-slot windows -> "
                "p_win -> classify by FROZEN pilot thresholds (p33/p66) -> select first 5 "
                "windows by time order per regime (LOW/TRANSITION/HIGH)",
        "thresholds": th,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="E4-V2-1 Pilot aggregation")
    ap.add_argument("--pilot-dir", default=None)
    args = ap.parse_args()
    global PILOT_DIR
    if args.pilot_dir:
        PILOT_DIR = args.pilot_dir

    cand = json.load(open(os.path.join(PILOT_DIR, "candidate_windows.json"), encoding="utf-8"))
    records = load_jsonl(os.path.join(PILOT_DIR, "pilot_raw_records.jsonl"))

    summary = sanity_summary(records)
    with open(os.path.join(PILOT_DIR, "pilot_sanity_summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)

    sel = regime_selection(cand["candidates"], cand["thresholds"])
    with open(os.path.join(PILOT_DIR, "regime_selection.json"), "w", encoding="utf-8") as fh:
        json.dump(sel, fh, ensure_ascii=False, indent=2)

    print("sanity runs:", summary["runs"], "| timeout:", summary["timeout_count"],
          "| error:", summary["error_count"])
    print("regimes:", {ds: v["available_regimes"] for ds, v in sel["datasets"].items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
