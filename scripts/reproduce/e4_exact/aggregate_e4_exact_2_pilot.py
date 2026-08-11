# -*- coding: utf-8 -*-
"""E4-EXACT-2 Pilot 聚合器（只聚合可计算性/可行性字段；严禁 CARS gap）。

依据：E4-EXACT-2 阶段合同 §十（Pilot runtime 指标）、§十一（CARS 输出处理）、§十五.3。

聚合字段仅限：
- runtime（total / evaluator）
- exact completion（oracle_status / accepted / certificate_pass）
- search states（total_discrete / visited / pruned / feasible / infeasible）
- certificate 残差（kkt / capacity / reliability / primal）

Formal configuration selector 绝不读取任何 CARS performance / oracle-gap 字段。

产物：
- results/e4_exact/e4_exact_2_pilot/oracle_runtime_summary.csv
- results/e4_exact/e4_exact_2_pilot/exact_completion_summary.csv
- results/e4_exact/e4_exact_2_pilot/search_space_summary.csv
- results/e4_exact/e4_exact_2_pilot/pilot_aggregated.json

用法：
  python scripts/reproduce/e4_exact/aggregate_e4_exact_2_pilot.py
"""

from __future__ import annotations

import csv
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
OUT_DIR = os.path.join(ROOT, "results", "e4_exact", "e4_exact_2_pilot")
RAW_RECORDS = os.path.join(OUT_DIR, "pilot_raw_records.jsonl")


def load_records() -> list:
    recs = []
    with open(RAW_RECORDS, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            recs.append(json.loads(line))
    return recs


def main() -> int:
    recs = load_records()
    if not recs:
        sys.stderr.write("[FAIL] no pilot records found\n")
        return 1

    # 按 (n, regime) 分组聚合
    groups = {}
    for r in recs:
        key = (r["n"], r["regime"])
        groups.setdefault(key, []).append(r)

    runtime_rows = []
    completion_rows = []
    search_rows = []
    for (n, regime), items in sorted(groups.items()):
        totals = [r["total_oracle_runtime_ms"] or 0.0 for r in items]
        evals = [r["evaluator_runtime_ms"] or 0.0 for r in items]
        completed = [r for r in items if r["status"] == "COMPLETED"]
        accepted = [r for r in items if r.get("accepted_exact")]
        cert_pass = [r for r in items if r.get("certificate_pass")]
        timeouts = [r for r in items if r["status"] == "TIMEOUT"]
        errors = [r for r in items if r["status"] == "ERROR"]

        runtime_rows.append({
            "n": n, "regime": regime, "instances": len(items),
            "completed": len(completed),
            "mean_total_runtime_ms": round(sum(totals) / len(totals), 3) if totals else None,
            "max_total_runtime_ms": round(max(totals), 3) if totals else None,
            "min_total_runtime_ms": round(min(totals), 3) if totals else None,
            "mean_evaluator_runtime_ms": round(sum(evals) / len(evals), 3) if evals else None,
            "timeout_count": len(timeouts),
            "error_count": len(errors),
        })
        completion_rows.append({
            "n": n, "regime": regime, "instances": len(items),
            "accepted_exact_count": len(accepted),
            "accepted_exact_rate": round(len(accepted) / len(items), 4) if items else 0.0,
            "certificate_pass_count": len(cert_pass),
            "certificate_pass_rate": round(len(cert_pass) / len(items), 4) if items else 0.0,
            "timeout_count": len(timeouts),
            "error_count": len(errors),
            "oracle_statuses": sorted({r["oracle_status"] for r in items}),
        })
        search_rows.append({
            "n": n, "regime": regime,
            "total_discrete_states": max((r.get("total_discrete_states") or 0 for r in items), default=0),
            "mean_visited_states": round(
                sum(r.get("visited_states") or 0 for r in items) / len(items), 1) if items else None,
            "mean_safely_pruned_states": round(
                sum(r.get("safely_pruned_states") or 0 for r in items) / len(items), 1) if items else None,
            "mean_feasible_states": round(
                sum(r.get("feasible_states") or 0 for r in items) / len(items), 1) if items else None,
            "mean_infeasible_states": round(
                sum(r.get("infeasible_states") or 0 for r in items) / len(items), 1) if items else None,
        })

    def write_csv(path, rows, fields):
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)

    write_csv(os.path.join(OUT_DIR, "oracle_runtime_summary.csv"), runtime_rows,
              list(runtime_rows[0].keys()))
    write_csv(os.path.join(OUT_DIR, "exact_completion_summary.csv"), completion_rows,
              list(completion_rows[0].keys()))
    write_csv(os.path.join(OUT_DIR, "search_space_summary.csv"), search_rows,
              list(search_rows[0].keys()))

    aggregated = {
        "experiment": "e4_exact_2_pilot",
        "aggregation_version": "E4_EXACT_2_AGGREGATE_V1",
        "records_total": len(recs),
        "groups": {
            "%d_%s" % (n, regime): items
            for (n, regime), items in sorted(groups.items())
        },
        "runtime_summary": runtime_rows,
        "completion_summary": completion_rows,
        "search_summary": search_rows,
        "formal_seeds_accessed": False,
        "cars_performance_never_aggregated": True,
    }
    with open(os.path.join(OUT_DIR, "pilot_aggregated.json"), "w", encoding="utf-8") as fh:
        json.dump(aggregated, fh, ensure_ascii=False, indent=2)

    print("aggregated %d records into %d (n,regime) groups" % (len(recs), len(groups)))
    for row in completion_rows:
        print("  n=%d %-12s accepted=%d/%d timeouts=%d" %
              (row["n"], row["regime"], row["accepted_exact_count"], row["instances"],
               row["timeout_count"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
