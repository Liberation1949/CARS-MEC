# -*- coding: utf-8 -*-
"""E4-EXACT-2 可计算性诊断（输出到文件；带 per-instance timeout）。

测量 E1-V2 缩小场景（M=4, s_f=1.0, MEDIUM）下 Oracle 随 N 的可计算性边界。
输出：results/e4_exact/e4_exact_2_pilot/runtime_diagnostic.jsonl
"""
import json
import os
import subprocess
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
OUT = os.path.join(ROOT, "results", "e4_exact", "e4_exact_2_pilot", "runtime_diagnostic.jsonl")
PY = sys.executable
WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_e4x2_single_instance.py")

os.makedirs(os.path.dirname(OUT), exist_ok=True)

CASES = [
    # (n, m, regime, seed, timeout_s)
    (4, 4, "LOW_REF", 3401, 600.0),
    (5, 4, "LOW", 3401, 600.0),
]

with open(OUT, "w", encoding="utf-8") as fh:
    for n, m, regime, seed, timeout_s in CASES:
        t0 = time.perf_counter()
        try:
            proc = subprocess.run(
                [PY, WORKER, str(n), str(m), regime, str(seed)],
                capture_output=True, text=True, encoding="utf-8",
                timeout=timeout_s, cwd=ROOT,
            )
            wall = time.perf_counter() - t0
            if proc.returncode != 0:
                rec = {"n": n, "m": m, "regime": regime, "seed": seed,
                       "status": "ERROR", "wall_s": round(wall, 2),
                       "error": (proc.stderr or "")[-300:]}
            else:
                rec = json.loads(proc.stdout.strip().splitlines()[-1])
                rec["wall_s"] = round(wall, 2)
        except subprocess.TimeoutExpired:
            wall = time.perf_counter() - t0
            rec = {"n": n, "m": m, "regime": regime, "seed": seed,
                   "status": "TIMEOUT", "wall_s": round(wall, 2),
                   "timeout_s": timeout_s}
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fh.flush()
        print("n=%d status=%s wall=%.1fs" % (n, rec.get("status"), rec.get("wall_s", -1)),
              flush=True)

print("written:", OUT)
