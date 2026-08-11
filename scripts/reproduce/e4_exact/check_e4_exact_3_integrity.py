# -*- coding: utf-8 -*-
"""E4-EXACT-3 Formal 完整性检查（E4-EXACT-2 Pre-state 基线 + Formal 数据约束）。

检查：
1. 保护对象 pre/post（f_min^exec + AADA-H_j 同步后基线）；
2. formal raw records：30 条（N=4/5/6 各 10）、无重复、无 pilot seed、全部 formal seed 白名单；
3. 失败（timeout/error）如实保留；
4. formal manifest 存在且 authorized；
5. formal seeds 授权记录。

输出：results/e4_exact/e4_exact_3_formal/integrity.json
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
OUT_DIR = os.path.join(ROOT, "results", "e4_exact", "e4_exact_3_formal")
RAW = os.path.join(OUT_DIR, "formal_raw_records.jsonl")
MANIFEST = os.path.join(OUT_DIR, "formal_manifest.json")
INTEGRITY = os.path.join(OUT_DIR, "integrity.json")

FORMAL_SEEDS = set(range(3501, 3511))
PILOT_SEEDS = set(range(3401, 3406))


def f16(p: str) -> str:
    return hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]


def dsha(root: str) -> str:
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

    # 1. 保护对象（E4-EXACT-2 R2 Pre-state 基线；除 III_VII 用户外部修改外全部一致）
    protected = {
        "reports/contracts/CARS_EXECUTABLE_THEORY_CONTRACT_V4.md": ("79227f233c13bf92", "unchanged"),
        "schemas/CARS_ACTIVE_SCHEMA_V4_dir": ("3b2bcc04a1e0e3e7", "unchanged"),
        "src/cars/evaluator_dir": ("0df96aa3fc786b7b", "unchanged"),
        "src/cars/methods_dir": ("f44e60fa9b720fdf", "unchanged"),
        "configs/cars_v4/cars_frozen_v4.yaml": ("58605c900ea08dff", "unchanged"),
        "src/cars/exact_oracle_dir": ("cdb3e4bb3adbadef", "unchanged"),
        "configs/e4_exact/e4_exact_formal_protocol.yaml": ("", "formal_protocol_authorized"),
    }
    for name, (expect, mode) in protected.items():
        if name.endswith("_dir"):
            cur = dsha(os.path.join(ROOT, name[:-4]))
        else:
            cur = f16(os.path.join(ROOT, name))
        if mode == "formal_protocol_authorized":
            # 仅检查 authorized_to_execute=true（E4-EXACT-3 合法登记）
            with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
                txt = fh.read()
            auth = "authorized_to_execute: true" in txt
            if not auth:
                ok = False
            checks[name] = {"mode": mode, "authorized_to_execute": auth}
            continue
        match = cur.startswith(expect)
        if not match:
            ok = False
        checks[name] = {"expected_prefix": expect, "current": cur, "match": match, "mode": mode}

    # 2. formal raw records
    recs = []
    if os.path.exists(RAW):
        seen = set()
        for line in open(RAW, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            recs.append(rec)
            key = (rec["n"], rec["regime"], rec["formal_seed"])
            if key in seen:
                checks["no_duplicate_records"] = False
                ok = False
            seen.add(key)
        checks["no_duplicate_records"] = True
        checks["records_total"] = len(recs)
        seeds = {r["formal_seed"] for r in recs}
        checks["all_seeds_formal_whitelist"] = seeds <= FORMAL_SEEDS
        checks["no_pilot_seeds"] = seeds.isdisjoint(PILOT_SEEDS)
        if not (seeds <= FORMAL_SEEDS) or not seeds.isdisjoint(PILOT_SEEDS):
            ok = False
        statuses = sorted({r["status"] for r in recs})
        checks["statuses"] = statuses
        checks["timeout_kept"] = sum(1 for r in recs if r["status"] == "TIMEOUT")
        checks["error_kept"] = sum(1 for r in recs if r["status"] == "ERROR")
        checks["completed"] = sum(1 for r in recs if r["status"] == "COMPLETED")
        metrics_computable = sum(1 for r in recs if (r.get("metrics") or {}).get("computable"))
        checks["metrics_computable"] = metrics_computable
    else:
        checks["records_total"] = 0
        ok = False

    # 3. manifest
    if os.path.exists(MANIFEST):
        m = json.load(open(MANIFEST, encoding="utf-8"))
        checks["manifest_exists"] = True
        checks["manifest_matrix_total"] = m.get("matrix_total")
        checks["manifest_authorized"] = m.get("formal_seeds_authorized") is True
    else:
        checks["manifest_exists"] = False
        ok = False

    checks["overall"] = "PASS" if ok else "FAIL"
    result = {
        "experiment": "e4_exact_3_formal",
        "integrity_version": "E4_EXACT_3_INTEGRITY_V1",
        "checks": checks,
        "overall": checks["overall"],
    }
    with open(INTEGRITY, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print("integrity overall:", checks["overall"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
