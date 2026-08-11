# -*- coding: utf-8 -*-
"""清理 E4-EXACT-2 Pilot raw 中的 kill 伪影记录（基础设施中断，非 Oracle 失败）。

背景：旧 Pilot（timeout 3600s）被 kill 时，runner 捕获 worker 被 Ctrl+C 终止
（exit 3221225786 = STATUS_CONTROL_C_EXIT），将 N=6/LOW/3401 记为 SOLVER_ERROR。
该记录是基础设施中断伪影，不是 Oracle 状态。清理后需补跑该实例获取真实数据。

用法：python scripts/reproduce/e4_exact/cleanup_e4_exact_2_kill_artifacts.py
"""
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
RAW = os.path.join(ROOT, "results", "e4_exact", "e4_exact_2_pilot", "pilot_raw_records.jsonl")

ARTIFACT_KEYS = {(6, "LOW", 3401)}  # kill 伪影（旧 Pilot 中断）


def main() -> int:
    if not os.path.exists(RAW):
        sys.stderr.write("[FAIL] raw not found\n")
        return 1
    lines = [l for l in open(RAW, encoding="utf-8").read().splitlines() if l.strip()]
    kept = []
    removed = []
    for line in lines:
        rec = json.loads(line)
        key = (rec.get("n"), rec.get("regime"), rec.get("seed"))
        if key in ARTIFACT_KEYS and rec.get("status") == "ERROR" \
                and "3221225786" in str(rec.get("error_msg", "")):
            removed.append(key)
        else:
            kept.append(line)
    with open(RAW, "w", encoding="utf-8") as fh:
        fh.write("\n".join(kept) + ("\n" if kept else ""))
    print("removed %d kill-artifact records: %s" % (len(removed), removed))
    print("remaining records: %d" % len(kept))
    return 0


if __name__ == "__main__":
    sys.exit(main())
