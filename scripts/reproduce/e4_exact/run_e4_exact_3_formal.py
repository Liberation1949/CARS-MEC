# -*- coding: utf-8 -*-
"""E4-EXACT-3 Formal runner（正式确认性评估；方案 A：regime 绑定 20 runs）。

执行配置：configs/e4_exact/e4_exact_formal_protocol.yaml
（E4_EXACT_FORMAL_PROTOCOL_V1；authorized_to_execute=true；2026-08-10 用户授权方案 A）。

**授权守卫**：正式运行必须传 --authorize-formal-seeds（用户 2026-08-10 授权
formal seeds 3501-3510）。不传即 SystemExit（REFUSED），不访问任何 formal seed。

Formal matrix（方案 A，regime 绑定 N，延续 Pilot 语义）：
  (LOW, N=4, seeds 3501-3510) × 10
  + (TRANSITION, N=5, seeds 3501-3510) × 10
  + (TRANSITION, N=6, seeds 3501-3510) × 10
  = 30 runs。

每实例（worker _e4x3_single_instance.py，subprocess）：
  shared scenario → Exact Oracle（solve_exact）→ CARS（CARS_FROZEN_V4，30s timeout）
  → 统一 Evaluator → Tier-1/2/3 gap 与 match（EPS_CMP=1e-9）。

确定性：Oracle 确定性；结果按 matrix 顺序写 raw；resume 只跳过已完整落盘的实例
（不覆盖、不重跑后二选一）。

**禁止**：改 matrix/种子/超时/算法/Evaluator/指标；删不利结果；formal 后调参；
pilot/validation 数据混入；隐藏 timeout/infeasible/error。

输出：results/e4_exact/e4_exact_3_formal/
  - formal_manifest.json（matrix/授权/参数）
  - formal_raw_records.jsonl（20 条；确定性顺序）
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
PY = sys.executable
PROTOCOL_PATH = os.path.join(ROOT, "configs", "e4_exact", "e4_exact_formal_protocol.yaml")
OUT_DIR = os.path.join(ROOT, "results", "e4_exact", "e4_exact_3_formal")
RAW_RECORDS = os.path.join(OUT_DIR, "formal_raw_records.jsonl")
MANIFEST = os.path.join(OUT_DIR, "formal_manifest.json")
WORKER = os.path.join(ROOT, "scripts", "reproduce", "e4_exact", "_e4x3_single_instance.py")

FORMAL_SEEDS = [3501, 3502, 3503, 3504, 3505, 3506, 3507, 3508, 3509, 3510]
PILOT_SEEDS = [3401, 3402, 3403, 3404, 3405]


def load_protocol() -> dict:
    with open(PROTOCOL_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def build_matrix(proto: dict) -> list:
    """方案 A：regime 绑定 N（formal_matrix.cells）；返回 [{"n","m","regime","seed"}...]。"""
    m = int(proto["m"])
    cells = proto["formal_matrix"]["cells"]
    seeds = proto["formal_seeds"]["list"]
    matrix = []
    for cell in cells:
        for seed in seeds:
            matrix.append({"n": int(cell["n"]), "m": m, "regime": cell["regime"], "seed": int(seed)})
    return matrix


def completed_keys() -> set:
    keys = set()
    if os.path.exists(RAW_RECORDS):
        with open(RAW_RECORDS, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                keys.add((rec.get("n"), rec.get("regime"), rec.get("formal_seed")))
    return keys


def run_one(n: int, m: int, regime: str, seed: int, timeout_s: float) -> dict:
    """subprocess 运行单实例；超时 kill 并记录 TIMEOUT_UNCERTIFIED。"""
    env = dict(os.environ)
    env["E4X3_TIMEOUT_S"] = str(timeout_s)
    t_start = time.perf_counter()
    try:
        proc = subprocess.run(
            [PY, WORKER, str(n), str(m), regime, str(seed)],
            capture_output=True, text=True, encoding="utf-8",
            timeout=timeout_s, env=env, cwd=ROOT,
        )
        wall_ms = (time.perf_counter() - t_start) * 1000.0
        if proc.returncode != 0:
            return {
                "n": n, "m": m, "regime": regime, "formal_seed": seed,
                "status": "ERROR", "oracle_status": "SOLVER_ERROR",
                "accepted_exact": False, "certificate_pass": False,
                "metrics": None, "total_wall_runtime_ms": round(wall_ms, 3),
                "error_msg": "worker exit=%d stderr=%s" % (proc.returncode, (proc.stderr or "")[-500:]),
            }
        rec = json.loads(proc.stdout.strip().splitlines()[-1])
        rec["total_wall_runtime_ms"] = round(wall_ms, 3)
        return rec
    except subprocess.TimeoutExpired:
        wall_ms = (time.perf_counter() - t_start) * 1000.0
        return {
            "n": n, "m": m, "regime": regime, "formal_seed": seed,
            "status": "TIMEOUT", "oracle_status": "TIMEOUT_UNCERTIFIED",
            "accepted_exact": False, "certificate_pass": False,
            "metrics": None, "total_wall_runtime_ms": round(wall_ms, 3),
            "error_msg": "per-instance oracle timeout exceeded",
        }


def main() -> int:
    ap = argparse.ArgumentParser(description="E4-EXACT-3 Formal runner（方案 A，20 runs）")
    ap.add_argument("--authorize-formal-seeds", action="store_true",
                    help="显式授权运行 formal seeds 3501-3510（用户 2026-08-10 授权方案 A）")
    ap.add_argument("--workers", type=int, default=4, help="实例级并行 worker 数")
    ap.add_argument("--max-instances", type=int, default=None, help="限制运行数（调试/分片）")
    args = ap.parse_args()

    if not args.authorize_formal_seeds:
        raise SystemExit("REFUSED: formal seeds 3501-3510 require --authorize-formal-seeds "
                         "(E4-EXACT-3 须用户授权；2026-08-10 用户已授权方案 A)")

    proto = load_protocol()
    if proto.get("authorized_to_execute") is not True:
        raise SystemExit("REFUSED: formal protocol authorized_to_execute != true")

    matrix = build_matrix(proto)
    timeout_s = float(proto["oracle_timeout_seconds"])

    # 校验：seed 必须为 formal seed；不得混入 pilot seed
    for item in matrix:
        if int(item["seed"]) not in FORMAL_SEEDS:
            raise SystemExit("[FATAL] non-formal seed in formal matrix: %s" % item)
        if int(item["seed"]) in PILOT_SEEDS:
            raise SystemExit("[FATAL] pilot seed in formal matrix: %s" % item)

    os.makedirs(OUT_DIR, exist_ok=True)
    done = completed_keys()

    manifest = {
        "experiment": "e4_exact_3_formal",
        "protocol_path": PROTOCOL_PATH,
        "matrix_structure": "regime-bounded（方案 A；用户 2026-08-10）",
        "matrix_total": len(matrix),
        "formal_seeds_authorized": True,
        "formal_seeds_accessed": True,          # 本 runner 首次实际访问 formal seeds
        "authorization_record": "user 2026-08-10 confirmed 方案 A（20 runs）",
        "workers": args.workers,
        "oracle_timeout_s": timeout_s,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "records": [],
    }

    pending = []
    ran_limit = 0
    for item in matrix:
        n, regime, seed = item["n"], item["regime"], item["seed"]
        if (n, regime, seed) in done:
            manifest["records"].append({"n": n, "regime": regime, "formal_seed": seed,
                                        "action": "SKIPPED_RESUME"})
            continue
        if args.max_instances is not None and ran_limit >= args.max_instances:
            manifest["records"].append({"n": n, "regime": regime, "formal_seed": seed,
                                        "action": "PENDING"})
            continue
        pending.append((item, n, regime, seed))
        ran_limit += 1

    results = {}
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        fut_map = {
            ex.submit(run_one, item["n"], item["m"], regime, seed, timeout_s): (item, n, regime, seed)
            for (item, n, regime, seed) in pending
        }
        for fut in as_completed(fut_map):
            item, n, regime, seed = fut_map[fut]
            results[(n, regime, seed)] = fut.result()

    ran = 0
    with open(RAW_RECORDS, "a", encoding="utf-8") as fh:
        for item in matrix:
            n, regime, seed = item["n"], item["regime"], item["seed"]
            if (n, regime, seed) in done:
                continue
            if (n, regime, seed) not in results:
                continue
            rec = results[(n, regime, seed)]
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            manifest["records"].append({"n": n, "regime": regime, "formal_seed": seed,
                                        "action": "RUN", "status": rec["status"],
                                        "oracle_status": rec.get("oracle_status")})
            ran += 1

    manifest["runs_completed_this_invocation"] = ran
    manifest["runs_total"] = len(matrix)
    manifest["runs_remaining"] = len(matrix) - len(done) - ran
    with open(MANIFEST, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)

    print("formal matrix total:", len(matrix))
    print("runs completed this invocation:", ran)
    print("runs remaining:", manifest["runs_remaining"])
    print("manifest written:", MANIFEST)
    return 0


if __name__ == "__main__":
    sys.exit(main())
