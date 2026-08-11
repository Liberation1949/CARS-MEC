# -*- coding: utf-8 -*-
"""E4-EXACT-2 完整性检查（Pilot 后运行；结果写入 integrity.json）。

依据：E4-EXACT-2 阶段合同 §二十一（Post-state）。

检查：
# - 保护对象 pre/post hash 一致（III_VII 用户外部修改为已登记例外 W-E4X2-01/02）
- Pilot raw records 完整性（无缺失/重复；timeout/error 如实保留）；
- formal seeds 零访问；
- selection 产物存在且与 raw 一致。

用法：
  python scripts/reproduce/e4_exact/check_e4_exact_2_integrity.py
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
OUT_DIR = os.path.join(ROOT, "results", "e4_exact", "e4_exact_2_pilot")
INTEGRITY = os.path.join(OUT_DIR, "integrity.json")


def f16(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]


def dsha(root):
    h = hashlib.sha256()
    files = []
    for dp, _dn, fn in os.walk(root):
        if "__pycache__" in dp:
            continue
        for f in fn:
            files.append(os.path.join(dp, f))
    for f in sorted(files):
        rel = os.path.relpath(f, ROOT)
        raw = open(f, "rb").read()
        h.update(rel.encode("utf-8")); h.update(b"\x00"); h.update(raw); h.update(b"\x00")
    return h.hexdigest()


def main() -> int:
    checks = {}
    ok = True

    # 1. 保护对象 pre/post（Pre-state 记录；III_VII 用户外部修改为已登记例外
    #    W-E4X2-01/06/07，活跃编辑中，仅记录不判 FAIL——本检查聚焦工作流保护对象未变）
    protected = {
        "experiment_docs/III_VII.md": ("5e50eb192cc81ec6", "external_change_registered"),
        "reports/contracts/CARS_EXECUTABLE_THEORY_CONTRACT_V4.md": ("79227f233c13bf92", "unchanged"),
        "schemas/CARS_ACTIVE_SCHEMA_V4_dir": ("3b2bcc04a1e0e3e7", "unchanged"),
        "src/cars/evaluator_dir": ("64d528993fbbe203", "unchanged"),
        "src/cars/methods_dir": ("711e4a74162febfb", "unchanged"),
        "configs/cars_v4/cars_frozen_v4.yaml": ("58605c900ea08dff", "unchanged"),
        "src/cars/exact_oracle_dir": ("4077f0b199ef83eb", "unchanged"),
    }
    for name, (expect, mode) in protected.items():
        if name.endswith("_dir"):
            cur = dsha(os.path.join(ROOT, name[:-4]))
        else:
            cur = f16(os.path.join(ROOT, name))
        match = cur.startswith(expect)
        if not match and mode != "external_change_registered":
            ok = False
        checks[name] = {"expected_prefix": expect, "current": cur[:16], "match": match,
                        "mode": mode}

    # 2. Pilot raw records
    raw_path = os.path.join(OUT_DIR, "pilot_raw_records.jsonl")
    recs = []
    if os.path.exists(raw_path):
        seen = set()
        for line in open(raw_path, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            recs.append(rec)
            key = (rec["n"], rec["regime"], rec["seed"])
            if key in seen:
                checks["pilot_no_duplicate_records"] = False
                ok = False
            seen.add(key)
        checks["pilot_records_total"] = len(recs)
        checks["pilot_no_duplicate_records"] = True
        statuses = sorted({r["status"] for r in recs})
        checks["pilot_statuses"] = statuses
        timeouts = sum(1 for r in recs if r["status"] == "TIMEOUT")
        errors = sum(1 for r in recs if r["status"] == "ERROR")
        completed = sum(1 for r in recs if r["status"] == "COMPLETED")
        checks["pilot_timeout_kept"] = timeouts
        checks["pilot_error_kept"] = errors
        checks["pilot_completed"] = completed
    else:
        checks["pilot_records_total"] = 0
        ok = False

    # 3. Formal seeds 零访问
    checks["formal_seeds_accessed"] = False
    seeds_used = {r["seed"] for r in recs}
    if seeds_used & set(range(3501, 3511)):
        checks["formal_seeds_accessed"] = True
        ok = False

    # 4. Selection 产物
    sel_path = os.path.join(OUT_DIR, "formal_scale_selection.json")
    if os.path.exists(sel_path):
        sel = json.load(open(sel_path, encoding="utf-8"))
        checks["selection_exists"] = True
        checks["selection_status"] = sel["status"]
        checks["selection_cars_fields_never_read"] = sel["inputs_only"][
            "cars_performance_fields_never_read"]
    else:
        checks["selection_exists"] = False
        ok = False

    checks["overall"] = "PASS" if ok else "FAIL"

    result = {
        "experiment": "e4_exact_2_pilot",
        "integrity_version": "E4_EXACT_2_INTEGRITY_V1",
        "checks": checks,
        "formal_seeds_accessed": checks["formal_seeds_accessed"],
        "overall": checks["overall"],
    }
    with open(INTEGRITY, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print("integrity overall:", checks["overall"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
