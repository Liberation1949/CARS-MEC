# -*- coding: utf-8 -*-
"""E4-EXACT-2 Exact-Oracle Pilot runner（可计算性校准；正式配置冻结前）。

依据：E4-EXACT-2 阶段合同 §七/§十/§十五（Pilot 协议、runtime 指标、mandatory 产物）；
configs/e4_exact/e4_exact_2_pilot_protocol.yaml（Pilot matrix / timeout / budget）。

职责与铁律：
- pilot seed whitelist：仅允许 protocol 登记的 Pilot seeds（3401-3405 范围内选定）；
- formal seed hard reject：出现 formal seeds（3501-3510）立即 FATAL 退出；
- deterministic resume：已完成 (N, regime, seed) 直接跳过（不覆盖、不重跑）；
- 不覆盖既有结果：raw records 追加式写入；
- 真实 per-instance 超时：每个实例子进程，超时 kill 并记录 TIMEOUT_UNCERTIFIED；
- exact status 强校验：oracle_status / certificate 完整记录；绝不删除慢/失败/超时实例；
- CARS 仅做 pipeline sanity（pipeline_valid / cars_runtime_ms），不得进入 selection；
- 墙上时钟 runtime 只记录，不进入 canonical 字段。

用法：
  python scripts/reproduce/e4_exact/run_e4_exact_2_pilot.py [--max-instances N] [--workers W]

实例级并行（CR_E4_EXACT_SCALE_REDUCTION_OPTIMIZATION_V1 授权）：
- 多个 (N, regime, seed) 实例用 ThreadPoolExecutor 并行调度（每个线程一个 subprocess worker，
  真正 CPU 并行）；Oracle 求解器本身零改动（每个实例内部仍为确定性串行）；
- 结果按 matrix 顺序写 raw records（与串行一致的确定性记录顺序）。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------------------------------------------------------------------------
# formal seed hard reject（合同：FORMAL_SEEDS_ACCESSED = NO）
# ---------------------------------------------------------------------------
if "--authorize-formal-seeds" in sys.argv:
    sys.stderr.write("[FATAL] formal seeds authorization forbidden in E4-EXACT-2\n")
    sys.exit(2)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

import yaml  # noqa: E402

PROTOCOL_PATH = os.path.join(ROOT, "configs", "e4_exact", "e4_exact_2_pilot_protocol.yaml")
OUT_DIR = os.path.join(ROOT, "results", "e4_exact", "e4_exact_2_pilot")
RAW_RECORDS = os.path.join(OUT_DIR, "pilot_raw_records.jsonl")
MANIFEST = os.path.join(OUT_DIR, "pilot_manifest.json")
WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_e4x2_single_instance.py")

FORMAL_SEEDS = [3501, 3502, 3503, 3504, 3505, 3506, 3507, 3508, 3509, 3510]
PY = sys.executable


def load_protocol() -> dict:
    with open(PROTOCOL_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


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
                keys.add((rec.get("n"), rec.get("regime"), rec.get("seed")))
    return keys


def run_one(n: int, m: int, regime: str, seed: int, timeout_s: float) -> dict:
    """subprocess 运行单实例；超时 kill 并记录 TIMEOUT_UNCERTIFIED。"""
    env = dict(os.environ)
    env["E4X2_TIMEOUT_S"] = str(timeout_s)
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
                "experiment": "e4_exact_2_pilot", "n": n, "m": m, "regime": regime,
                "seed": seed, "status": "ERROR", "oracle_status": "SOLVER_ERROR",
                "accepted_exact": False, "certificate_pass": False,
                "objective_tuple": None, "total_oracle_runtime_ms": round(wall_ms, 3),
                "evaluator_runtime_ms": None, "evaluator_calls": 0,
                "enumeration_runtime_ms": None, "continuous_solver_runtime_ms": None,
                "timeout_s": timeout_s,
                "error_msg": "worker exit=%d stderr=%s"
                             % (proc.returncode, (proc.stderr or "")[-500:]),
            }
        rec = json.loads(proc.stdout.strip().splitlines()[-1])
        rec["total_oracle_runtime_ms"] = round(wall_ms, 3)
        return rec
    except subprocess.TimeoutExpired:
        wall_ms = (time.perf_counter() - t_start) * 1000.0
        return {
            "experiment": "e4_exact_2_pilot", "n": n, "m": m, "regime": regime,
            "seed": seed, "status": "TIMEOUT", "oracle_status": "TIMEOUT_UNCERTIFIED",
            "accepted_exact": False, "certificate_pass": False,
            "objective_tuple": None, "total_oracle_runtime_ms": round(wall_ms, 3),
            "evaluator_runtime_ms": None, "evaluator_calls": 0,
            "enumeration_runtime_ms": None, "continuous_solver_runtime_ms": None,
            "timeout_s": timeout_s,
            "error_msg": "per-instance timeout exceeded",
        }


def main() -> int:
    ap = argparse.ArgumentParser(description="E4-EXACT-2 Pilot runner")
    ap.add_argument("--max-instances", type=int, default=None)
    ap.add_argument("--workers", type=int, default=4,
                    help="并行实例数（实例级并行；Oracle 零改动）")
    args = ap.parse_args()

    proto = load_protocol()
    matrix = proto["pilot_matrix"]
    pilot_whitelist = set(proto["seed_whitelist"]["pilot_seeds"])
    formal_whitelist = set(proto["seed_whitelist"]["formal_seeds"])
    timeout_s = float(proto["timeout"]["per_instance_oracle_timeout_seconds"])
    m = int(proto["scale"]["m"])

    for item in matrix:
        seed = int(item["seed"])
        if seed in FORMAL_SEEDS or seed in formal_whitelist:
            sys.stderr.write("[FATAL] formal seed in pilot matrix: %s\n" % item)
            return 2
        if seed not in pilot_whitelist:
            sys.stderr.write("[FATAL] seed not in pilot whitelist: %s\n" % item)
            return 2

    os.makedirs(OUT_DIR, exist_ok=True)
    done = completed_keys()

    manifest = {
        "experiment": "e4_exact_2_pilot",
        "protocol_path": PROTOCOL_PATH,
        "matrix_total": len(matrix),
        "pilot_seeds_whitelist": sorted(pilot_whitelist),
        "formal_seeds_registered_not_accessed": sorted(FORMAL_SEEDS),
        "formal_seeds_accessed": False,
        "workers": args.workers,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "records": [],
    }

    # 收集待运行实例（跳过已完成；受 max-instances 限制）
    pending = []
    ran_limit = 0
    for item in matrix:
        n, regime, seed = int(item["n"]), item["regime"], int(item["seed"])
        if (n, regime, seed) in done:
            manifest["records"].append({"n": n, "regime": regime, "seed": seed,
                                        "action": "SKIPPED_RESUME"})
            continue
        if args.max_instances is not None and ran_limit >= args.max_instances:
            manifest["records"].append({"n": n, "regime": regime, "seed": seed,
                                        "action": "PENDING"})
            continue
        pending.append((item, n, regime, seed))
        ran_limit += 1

    # 实例级并行（每个线程一个 subprocess worker；Oracle 零改动）
    results = {}
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        fut_map = {
            ex.submit(run_one, n, m, regime, seed, timeout_s): (item, n, regime, seed)
            for (item, n, regime, seed) in pending
        }
        for fut in as_completed(fut_map):
            item, n, regime, seed = fut_map[fut]
            results[(n, regime, seed)] = fut.result()

    # 按 matrix 顺序写 raw records（确定性记录顺序）
    ran = 0
    with open(RAW_RECORDS, "a", encoding="utf-8") as fh:
        for item in matrix:
            n, regime, seed = int(item["n"]), item["regime"], int(item["seed"])
            if (n, regime, seed) in done:
                continue
            if (n, regime, seed) not in results:
                continue
            rec = results[(n, regime, seed)]
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            manifest["records"].append({"n": n, "regime": regime, "seed": seed,
                                        "action": "RUN", "status": rec["status"],
                                        "oracle_status": rec["oracle_status"]})
            ran += 1
            print("[%s] n=%d regime=%s seed=%d status=%s oracle=%s %.1fs"
                  % (time.strftime("%H:%M:%S"), n, regime, seed, rec["status"],
                     rec["oracle_status"],
                     (rec["total_oracle_runtime_ms"] or 0) / 1000.0),
                  flush=True)

    manifest["ran_this_invocation"] = ran
    manifest["formal_seeds_accessed"] = False
    with open(MANIFEST, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    print("manifest written:", MANIFEST)
    return 0


if __name__ == "__main__":
    sys.exit(main())
