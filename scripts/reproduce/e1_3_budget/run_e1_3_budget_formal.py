# -*- coding: utf-8 -*-
"""E1-3 Stage 3：Baseline Budget-Sensitivity Formal runner（Confirmatory）。

严格依据 Stage-2 冻结配置 configs/e1_3_budget_formal_frozen.yaml：
  - 场景：E1-V2-1 formal 场景（seeds 1101-1110, N=200）；
  - 方法：bpso_rata_la / nfa_adapted × {0.5,1,2,4} + cars（固定参考）；
  - 每档配置：直接读取 frozen config budget_configs（Stage-2 冻结唯一权威）；
  - timeout：30s（共享）；
  - 统一 MethodRunner / Evaluator / runtime 口径。

流程：
  1. 生成 immutable Formal Manifest（expected run matrix + manifest hash）；
  2. 按 manifest 逐项运行，每完成一个 run 立即 append canonical raw record（JSONL）；
  3. 全部完成后审计 expected == observed（no duplicate / no missing / no unexpected）；
  4. 生成 summary（mean±std + paired Δ）+ integrity。

禁止：运行中修改 manifest；删除/隐藏 timeout/BUDGET_EXHAUSTED/error；
自动重跑失败 run（除非冻结 retry policy——本协议无）；使用 Pilot seeds。
输出：results/e1_3/budget_formal/{formal_manifest.json, formal_raw.jsonl,
formal_summary.json, formal_integrity.json}
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time

import yaml

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(_PROJECT, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cars.runner.runner import MethodRunner  # noqa: E402
from aggregate_e1_3_budget_formal import build_formal_summary  # noqa: E402

FROZEN_CONFIG = os.path.join(_PROJECT, "configs", "e1_3_budget", "e1_3_budget_formal_frozen.yaml")
OUT_DIR = os.path.join(_PROJECT, "results", "e1_3_budget", "budget_formal")
MANIFEST_PATH = os.path.join(OUT_DIR, "formal_manifest.json")
RAW_PATH = os.path.join(OUT_DIR, "formal_raw.jsonl")
SUMMARY_PATH = os.path.join(OUT_DIR, "formal_summary.json")
INTEGRITY_PATH = os.path.join(OUT_DIR, "formal_integrity.json")

TIMEOUT = 30.0


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def build_config_from_frozen(method: str, base_cfg: dict, budget_cfg: dict) -> dict:
    """从 frozen budget_configs 构造各档配置（只覆盖预算白名单键）。"""
    cfg = dict(base_cfg)
    if method == "bpso_rata_la":
        cfg["population_size_max"] = int(budget_cfg["population_size_max"])
        cfg["max_iterations_max"] = int(budget_cfg["max_iterations_max"])
        cfg["particle_evaluation_cap_max"] = int(budget_cfg["particle_evaluation_cap_max"])
    elif method == "nfa_adapted":
        cfg["population_size_max"] = int(budget_cfg["population_size_max"])
        cfg["max_generations_max"] = int(budget_cfg["max_generations_max"])
        cfg["objective_evaluation_cap_max"] = int(budget_cfg["objective_evaluation_cap_max"])
    else:
        raise ValueError("unknown method %r" % method)
    return cfg


def native_budget(method: str, cfg: dict) -> dict:
    if method == "bpso_rata_la":
        return {"population_size": int(cfg["population_size_max"]),
                "max_iterations": int(cfg["max_iterations_max"]),
                "cap": int(cfg["particle_evaluation_cap_max"])}
    if method == "nfa_adapted":
        return {"population_size": int(cfg["population_size_max"]),
                "max_generations": int(cfg["max_generations_max"]),
                "cap": int(cfg["objective_evaluation_cap_max"])}
    return None


def extract_diag(method: str, diag: dict, conf: dict) -> dict:
    if method == "bpso_rata_la":
        cap = conf["cap"]
        consumed = int(diag.get("particle_evaluations", 0))
        return {"actual_consumed_search_evaluations": consumed,
                "executed_iterations": int(diag.get("completed_iterations", 0)),
                "executed_search_steps": int(diag.get("completed_iterations", 0)),
                "population_size": int(diag.get("population_size", conf["population_size"])),
                "max_iterations": int(diag.get("max_iterations", conf["max_iterations"])),
                "actual_iterations": int(diag.get("completed_iterations", 0)),
                "fitness_evaluations": consumed,
                "cap_reached": bool(consumed >= cap),
                "soft_deadline_triggered": bool(diag.get("soft_deadline_triggered", False))}
    if method == "nfa_adapted":
        cap = conf["cap"]
        consumed = int(diag.get("objective_evaluations", 0))
        return {"actual_consumed_search_evaluations": consumed,
                "executed_iterations": int(diag.get("completed_generations", 0)),
                "executed_search_steps": int(diag.get("completed_pairwise_moves", 0)),
                "population_size": int(diag.get("population_size", conf["population_size"])),
                "max_generations": int(diag.get("max_generations", conf["max_generations"])),
                "actual_generations": int(diag.get("completed_generations", 0)),
                "pairwise_moves": int(diag.get("completed_pairwise_moves", 0)),
                "objective_evaluations": consumed,
                "cap_reached": bool(consumed >= cap),
                "soft_deadline_triggered": bool(diag.get("soft_deadline_triggered", False))}
    return {}


def build_manifest(frozen: dict) -> dict:
    """生成 immutable Formal Manifest（run matrix + hash）。"""
    runs = []
    seeds = frozen["seeds"]
    mults = frozen["methods"]["budget_multipliers"]
    for method in frozen["methods"]["scanned"]:
        for mult in mults:
            for seed in seeds:
                runs.append({"method": method, "budget_multiplier": mult, "seed": seed})
    for seed in seeds:  # CARS 固定参考
        runs.append({"method": "cars", "budget_multiplier": None, "seed": seed})
    manifest = {
        "experiment_id": "e1_3_budget_sensitivity",
        "stage": "Stage 3 Formal",
        "formal": True,
        "frozen_config_version": frozen["formal_config_version"],
        "scenario_n": frozen["scenario"]["n"],
        "scenario_m": frozen["scenario"]["m"],
        "scenario_files_template": frozen["scenario"]["scenario_files"],
        "seeds": seeds,
        "methods": frozen["methods"],
        "budget_multipliers": mults,
        "timeout_seconds": frozen["timeout"]["shared_timeout_seconds"],
        "expected_runs": len(runs),
        "runs": runs,
    }
    manifest["manifest_hash"] = hashlib.sha256(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return manifest


def run_row(runner: MethodRunner, frozen: dict, entry: dict, method_configs: dict) -> dict:
    seed = entry["seed"]
    scen_path = os.path.join(_PROJECT, frozen["scenario"]["scenario_files"].format(seed=seed))
    scenario_id = "%s_seed%d_n%d" % (frozen["scenario"]["scenario_id_prefix"], seed, frozen["scenario"]["n"])
    method = entry["method"]
    mult = entry["budget_multiplier"]

    if method == "cars":
        cfg = method_configs["cars"]
        conf_budget = None
    else:
        key = ("%g" % mult) if mult == int(mult) else str(mult)
        map_key = {0.5: "0.5", 1.0: "1.0", 2.0: "2.0", 4.0: "4.0"}[mult]
        cfg = build_config_from_frozen(method, method_configs[method + "_base"],
                                       frozen["budget_configs"][method][map_key])
        conf_budget = native_budget(method, cfg)

    rec = runner.run(
        method_id=method,
        scenario_cfg_path=scen_path,
        method_config=cfg,
        method_seed=cfg.get("method_seed", 1),
        hard_timeout_seconds=frozen["timeout"]["shared_timeout_seconds"],
    )
    diag = rec.get("method_diagnostics") or {}
    bd = extract_diag(method, diag, conf_budget) if conf_budget else {}
    ev = rec.get("evaluator_output") or {}
    sm = ev.get("system_metrics", {}) if ev else {}
    early_stop = bool(bd.get("cap_reached") or bd.get("soft_deadline_triggered"))
    row = {
        "experiment_id": "e1_3_budget_sensitivity",
        "stage": "Stage 3 Formal",
        "formal": True,
        "scenario_id": scenario_id,
        "seed": seed,
        "method": method,
        "budget_multiplier": mult,
        "configured_native_budget": conf_budget,
        "actual_consumed_search_evaluations": bd.get("actual_consumed_search_evaluations"),
        "executed_iterations": bd.get("executed_iterations"),
        "executed_search_steps": bd.get("executed_search_steps"),
        "early_stop": early_stop,
        "timeout": bool(rec.get("runtime_censored", False)),
        "result_status": rec.get("method_status"),
        "tssr": sm.get("tssr"),
        "rbar_eff": sm.get("mean_effective_reliability"),
        "ubar_eff": sm.get("mean_effective_utility"),
        "v_r": sm.get("reliability_violation_rate"),
        "t_alg_ms": rec.get("method_runtime_ms"),
        "total_wall_time_ms": rec.get("total_wall_time_ms"),
        "canonical_hash": (rec.get("reproducibility") or {}).get("canonical_hash"),
        "config_hash": rec.get("config_hash"),
        "method_status_detail": rec.get("method_status"),
        "evaluator_status": rec.get("evaluator_status"),
    }
    # 算法专属字段
    for k in ("population_size", "max_iterations", "actual_iterations", "fitness_evaluations",
              "max_generations", "actual_generations", "pairwise_moves", "objective_evaluations",
              "cap_reached", "soft_deadline_triggered"):
        if k in bd:
            row[k] = bd[k]
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description="E1-3 Stage 3 Formal runner")
    ap.add_argument("--authorize-formal-seeds", action="store_true",
                    help="显式确认运行 formal-test seeds 1101-1110（仅防误运行，非访问控制）")
    args = ap.parse_args()
    if not args.authorize_formal_seeds:
        raise SystemExit("REFUSED: formal seeds 1101-1110 require --authorize-formal-seeds "
                         "(E1-3 budget sensitivity formal run)")

    frozen = load_yaml(FROZEN_CONFIG)
    assert frozen["status"] == "FROZEN_ONLY / NOT_EXECUTED", "frozen config 状态异常"

    # 加载方法基配置
    base_cfgs = {
        "bpso_rata_la": load_yaml(os.path.join(_PROJECT, frozen["methods"]["baseline_1x_configs"]["bpso_rata_la"])),
        "nfa_adapted": load_yaml(os.path.join(_PROJECT, frozen["methods"]["baseline_1x_configs"]["nfa_adapted"])),
        "cars": load_yaml(os.path.join(_PROJECT, frozen["methods"]["cars_config"])),
    }
    method_configs = {
        "cars": base_cfgs["cars"],
        "bpso_rata_la_base": base_cfgs["bpso_rata_la"],
        "nfa_adapted_base": base_cfgs["nfa_adapted"],
    }

    os.makedirs(OUT_DIR, exist_ok=True)

    # ---- 1. 生成 immutable Manifest ----
    manifest = build_manifest(frozen)
    if os.path.exists(MANIFEST_PATH):
        existing = json.load(open(MANIFEST_PATH, encoding="utf-8"))
        assert existing["manifest_hash"] == manifest["manifest_hash"], \
            "已存在 manifest 与本配置不一致——不得覆盖"
        print("Manifest 已存在且一致（复用）")
    else:
        with open(MANIFEST_PATH, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=2, sort_keys=True)
        print("Manifest 已生成冻结: %d runs, hash=%s" % (
            manifest["expected_runs"], manifest["manifest_hash"][:16]))

    # ---- 2. 按 manifest 运行（JSONL append；跳过已记录 run 以支持断点续跑） ----
    done_keys = set()
    if os.path.exists(RAW_PATH):
        with open(RAW_PATH, encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                done_keys.add((r["method"], r["budget_multiplier"], r["seed"]))
        print("已有 raw 记录 %d 条（resume 用）" % len(done_keys))

    runner = MethodRunner()
    start = time.time()
    total = manifest["expected_runs"]
    done = len(done_keys)
    with open(RAW_PATH, "a", encoding="utf-8") as fh:
        for entry in manifest["runs"]:
            key = (entry["method"], entry["budget_multiplier"], entry["seed"])
            if key in done_keys:
                print("[%3d/%d] skip (already recorded) %s %s seed=%d" % (
                    done, total, entry["method"], entry["budget_multiplier"], entry["seed"]))
                continue
            row = run_row(runner, frozen, entry, method_configs)
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            fh.flush()
            done += 1
            print("[%3d/%d] %s %s× seed=%d -> %s consumed=%s t_alg=%.0fms" % (
                done, total, entry["method"], entry["budget_multiplier"], entry["seed"],
                row["result_status"], row["actual_consumed_search_evaluations"],
                row["t_alg_ms"] or 0.0))

    # ---- 3. 审计 expected == observed ----
    raw = [json.loads(line) for line in open(RAW_PATH, encoding="utf-8")]
    observed_keys = [(r["method"], r["budget_multiplier"], r["seed"]) for r in raw]
    expected_keys = [(r["method"], r["budget_multiplier"], r["seed"]) for r in manifest["runs"]]
    missing = [k for k in expected_keys if k not in set(observed_keys)]
    duplicate = [k for k in observed_keys if observed_keys.count(k) > 1]
    unexpected = [k for k in observed_keys if k not in set(expected_keys)]
    audit = {
        "expected_runs": len(expected_keys),
        "observed_runs": len(observed_keys),
        "missing": missing,
        "duplicate": sorted(set(duplicate)),
        "unexpected": unexpected,
        "complete": (not missing) and (not duplicate) and (not unexpected),
    }

    # ---- 4. 汇总（独立 aggregate 脚本；统计语义不变） ----
    summary = build_formal_summary(raw, frozen)
    with open(SUMMARY_PATH, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2, sort_keys=True)

    integrity = {
        "experiment_id": "e1_3_budget_sensitivity",
        "stage": "Stage 3 Formal",
        "stage_status": "FORMAL_COMPLETED",
        "formal_config_version": frozen["formal_config_version"],
        "frozen_config_sha256": hashlib.sha256(open(FROZEN_CONFIG, "rb").read()).hexdigest(),
        "manifest_hash": manifest["manifest_hash"],
        "manifest": MANIFEST_PATH,
        "raw": RAW_PATH,
        "summary": SUMMARY_PATH,
        "audit": audit,
        "timeout_count": sum(1 for r in raw if r["timeout"]),
        "budget_exhausted_count": sum(1 for r in raw if r["result_status"] == "BUDGET_EXHAUSTED"),
        "error_count": sum(1 for r in raw if r["result_status"] == "METHOD_ERROR"),
        "success_count": sum(1 for r in raw if r["result_status"] == "SUCCESS"),
        "elapsed_seconds": round(time.time() - start, 3),
    }
    with open(INTEGRITY_PATH, "w", encoding="utf-8") as fh:
        json.dump(integrity, fh, ensure_ascii=False, indent=2, sort_keys=True)

    print("\n=== Formal 完成: %d/%d runs, timeout=%d, exhausted=%d, error=%d ===" % (
        audit["observed_runs"], audit["expected_runs"], integrity["timeout_count"],
        integrity["budget_exhausted_count"], integrity["error_count"]))
    print("审计:", {k: v for k, v in audit.items() if k != "missing"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
