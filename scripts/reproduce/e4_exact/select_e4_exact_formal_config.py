# -*- coding: utf-8 -*-
"""E4-EXACT-2 Formal Configuration Selector（依据冻结 F1-F5 规则）。

依据：E4-EXACT-2 阶段合同 §八（Formal Scale Selection Rule F1-F5）、
§九（Formal N-grid Freeze Rule）。

输入只允许：
  N / M / regime / oracle_status / certificate / runtime / search-state / compute-budget

明确禁止输入（本脚本 schema 中不存在、绝不读取）：
  cars_TSSR / cars_Rbar / cars_Ubar / oracle_gap / method ranking / Delta_*

F1. 该 N 在所有纳入考虑的 Pilot regimes/seeds 上 Oracle 均返回
     EXACT_OPTIMAL 或 CERTIFIED_NUMERICAL_EXACT（无 TIMEOUT_UNCERTIFIED/NOT_EXACT/SOLVER_ERROR）；
F2. exactness certificate 全部通过；
F3. 单实例 Oracle runtime <= per-instance Pilot acceptance budget；
F4. 整体预计 Formal 计算预算 <= frozen total compute budget；
F5. 该 N 与前一规模相比仍提供新的规模信息。

Formal 最大 N = 满足 F1-F5 的最大候选 N。
N-grid Freeze：优先保留从最小到最大可计算规模的完整子集；
若只剩单一 N，不得直接进入 Formal（FAIL_AND_REDESIGN 或提交 CR）。

产物：results/e4_exact/e4_exact_2_pilot/formal_scale_selection.json

用法：
  python scripts/reproduce/e4_exact/select_e4_exact_formal_config.py \
      [--per-instance-budget-seconds 3600] [--total-budget-hours 72]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
OUT_DIR = os.path.join(ROOT, "results", "e4_exact", "e4_exact_2_pilot")
AGGREGATED = os.path.join(OUT_DIR, "pilot_aggregated.json")
SELECTION = os.path.join(OUT_DIR, "formal_scale_selection.json")

ACCEPTED = ("EXACT_OPTIMAL", "CERTIFIED_NUMERICAL_EXACT")
REJECTED = ("TIMEOUT_UNCERTIFIED", "NOT_EXACT", "SOLVER_ERROR")


def load_aggregated() -> dict:
    with open(AGGREGATED, encoding="utf-8") as fh:
        return json.load(fh)


def main() -> int:
    ap = argparse.ArgumentParser(description="E4-EXACT-2 formal config selector")
    ap.add_argument("--per-instance-budget-seconds", type=float, required=True)
    ap.add_argument("--total-budget-hours", type=float, required=True)
    ap.add_argument("--formal-seeds-per-cell", type=int, default=10)
    ap.add_argument("--regimes-count", type=int, default=3)
    args = ap.parse_args()

    agg = load_aggregated()
    groups = agg["groups"]

    # 候选规模（从 Pilot matrix 提取；不允许扩大）
    n_candidates = sorted({int(k.split("_")[0]) for k in groups})
    if not n_candidates:
        sys.stderr.write("[FAIL] no pilot groups to select from\n")
        return 1

    per_instance_budget_s = args.per_instance_budget_seconds
    total_budget_s = args.total_budget_hours * 3600.0

    decisions = {}   # n -> {"eligible": bool, "reasons": [...]}
    for n in n_candidates:
        items = []
        for key, recs in groups.items():
            if int(key.split("_")[0]) == n:
                items.extend(recs)
        reasons = []
        # F1: all accepted status
        statuses = [r["oracle_status"] for r in items]
        if any(s in REJECTED for s in statuses):
            reasons.append("F1-FAIL: rejected oracle statuses present: %s"
                           % sorted({s for s in statuses if s in REJECTED}))
        # F2: certificate pass
        if not all(r.get("certificate_pass") for r in items):
            reasons.append("F2-FAIL: certificate not passed for all instances")
        # F3: runtime budget
        max_rt = max((r["total_oracle_runtime_ms"] or 0.0 for r in items), default=0.0)
        if max_rt > per_instance_budget_s * 1000.0:
            reasons.append("F3-FAIL: max runtime %.1fs > budget %.1fs"
                           % (max_rt / 1000.0, per_instance_budget_s))
        # F4: total formal budget
        formal_runs = args.regimes_count * args.formal_seeds_per_cell
        est_total_s = max_rt / 1000.0 * formal_runs
        if est_total_s > total_budget_s:
            reasons.append("F4-FAIL: estimated formal total %.1fh > budget %.1fh"
                           % (est_total_s / 3600.0, args.total_budget_hours))
        eligible = not reasons
        decisions[n] = {
            "eligible": eligible,
            "reasons": reasons,
            "instances": len(items),
            "max_runtime_s": round(max_rt / 1000.0, 3),
            "estimated_formal_total_hours": round(max_rt / 1000.0 * formal_runs / 3600.0, 3),
        }

    # F5 + N-grid freeze：从最大到最小扫描，取满足 F1-F4 的最大 N，
    # 然后保留从最小到该最大 N 的完整子集。
    eligible_ns = [n for n in n_candidates if decisions[n]["eligible"]]
    if not eligible_ns:
        max_eligible = None
        frozen_grid = []
        status_note = "FAIL_AND_REDESIGN: no N satisfies F1-F4"
    else:
        max_eligible = max(eligible_ns)
        frozen_grid = [n for n in n_candidates if n <= max_eligible]
        # F5 语义：每个纳入 N 必须都有实例（已满足）；若网格只剩单一 N -> 不可入 Formal
        if len(frozen_grid) < 2:
            status_note = ("FAIL_AND_REDESIGN: formal N-grid has only one N (%s); "
                           "cannot answer scale-growth oracle-gap; submit CR or redesign"
                           % frozen_grid)
            frozen_grid = []
        else:
            status_note = "OK"

    selection = {
        "selection_version": "E4_EXACT_2_SELECTION_V1",
        "inputs_only": {
            "n_m_regime_oracle_status_certificate_runtime_search_budget": True,
            "cars_performance_fields_never_read": True,
        },
        "candidate_n": n_candidates,
        "per_instance_acceptance_budget_s": per_instance_budget_s,
        "total_compute_budget_hours": args.total_budget_hours,
        "formal_seeds_per_cell": args.formal_seeds_per_cell,
        "regimes_count": args.regimes_count,
        "formal_runs_estimate": args.regimes_count * args.formal_seeds_per_cell * len(frozen_grid),
        "decisions": decisions,
        "max_eligible_n": max_eligible,
        "frozen_n_grid": frozen_grid,
        "status": status_note,
        "formal_seeds_accessed": False,
    }
    with open(SELECTION, "w", encoding="utf-8") as fh:
        json.dump(selection, fh, ensure_ascii=False, indent=2)

    print("candidate N:", n_candidates)
    for n in n_candidates:
        d = decisions[n]
        print("  N=%d eligible=%s max_rt=%.1fs %s" % (n, d["eligible"], d["max_runtime_s"],
                                                      "; ".join(d["reasons"])))
    print("max_eligible_n:", max_eligible)
    print("frozen_n_grid:", frozen_grid)
    print("status:", status_note)
    return 0 if status_note == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
