# -*- coding: utf-8 -*-
"""E1-3 Stage 2：Baseline Budget-Sensitivity Pilot runner（NOT_FORMAL）。

用途：验证 Stage-1 冻结预算协议的可执行性（不是小号 Formal）：
  - BPSO-RATA-LA / NFA 各 4 档（0.5×/1×/2×/4×）预算真实形成递增搜索量；
  - actual consumed budget 可准确记录（只读 instrumentation：从既有
    method_diagnostics 提取，不修改算法控制流）；
  - early-stop / timeout 完整记录；
  - N=200 场景可完成、4× 可运行性；
  - 供 Stage 2 冻结 Stage 3 Formal 配置。

设计要点（与 Stage-1 协议一致）：
  - 场景：复用 E1-V2-1 pilot 场景（seeds 201-203, N=200）——
    results/e1_v2/e1_v2_1_pilot/scenarios/scenario_seed{seed}_n200.yaml；
  - 方法：bpso_rata_la / nfa_adapted × 4 档 + cars（固定参考，不缩放）；
  - 配置：从 R6 frozen yaml 深拷贝，仅覆盖 Stage-1 白名单预算键
    （BPSO: population_size_max + particle_evaluation_cap_max；
     NFA: objective_evaluation_cap_max）；
  - 统一 MethodRunner（同一 Evaluator / timeout=30s / runtime 口径）；
  - consumed budget = 算法原生 search evaluations
    （BPSO: diagnostics.particle_evaluations；NFA: diagnostics.objective_evaluations），
    不可跨算法直接比较（native unit 不同）——如实记录，不强行统一。

禁止：使用 formal seeds 1101-1110；根据 Pilot 结果调性能；生成正式结论。
输出：results/e1_3/budget_pilot/{pilot_raw.jsonl, pilot_summary.json, pilot_integrity.json}
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time

import yaml

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(_PROJECT, "src"))

from cars.runner.runner import MethodRunner  # noqa: E402

STAGE1_PROTOCOL = os.path.join(_PROJECT, "configs", "e1_3_budget", "e1_3_budget_sensitivity_protocol.yaml")
PILOT_CONFIG = os.path.join(_PROJECT, "configs", "e1_3_budget", "e1_3_budget_pilot.yaml")
OUT_DIR = os.path.join(_PROJECT, "results", "e1_3_budget", "budget_pilot")

FROZEN = {
    "bpso_rata_la": os.path.join(_PROJECT, "configs", "r6", "frozen_method_configs", "bpso_frozen.yaml"),
    "nfa_adapted": os.path.join(_PROJECT, "configs", "r6", "frozen_method_configs", "nfa_frozen.yaml"),
    "cars": os.path.join(_PROJECT, "configs", "cars_v4", "cars_frozen_v4.yaml"),
}

TIMEOUT = 30.0


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def build_scaled_config(method: str, base_cfg: dict, multiplier: float, mapping: dict) -> dict:
    """按 Stage-1 协议 multiplier_map 覆盖预算键（其余字段原样保留）。"""
    cfg = dict(base_cfg)
    mcfg = mapping[multiplier]
    if method == "bpso_rata_la":
        cfg["population_size_max"] = int(mcfg["population_size_max"])
        cfg["max_iterations_max"] = int(mcfg["max_iterations_max"])
        cfg["particle_evaluation_cap_max"] = int(mcfg["particle_evaluation_cap_max"])
    elif method == "nfa_adapted":
        cfg["population_size_max"] = int(mcfg["population_size_max"])
        cfg["max_generations_max"] = int(mcfg["max_generations_max"])
        cfg["objective_evaluation_cap_max"] = int(mcfg["objective_evaluation_cap_max"])
    else:
        raise ValueError("unknown scanned method %r" % method)
    return cfg


def configured_native_budget(method: str, cfg: dict) -> dict:
    """记录各档位配置的原生预算（供 Gate A / 汇总）。"""
    if method == "bpso_rata_la":
        return {
            "population_size": int(cfg["population_size_max"]),
            "max_iterations": int(cfg["max_iterations_max"]),
            "cap": int(cfg["particle_evaluation_cap_max"]),
        }
    if method == "nfa_adapted":
        return {
            "population_size": int(cfg["population_size_max"]),
            "max_generations": int(cfg["max_generations_max"]),
            "cap": int(cfg["objective_evaluation_cap_max"]),
        }
    return None  # cars：无预算参数


def extract_budget_diagnostics(method: str, diag: dict, configured: dict) -> dict:
    """只读 instrumentation：从 method_diagnostics 提取 consumed budget 字段。

    不修改算法控制流；仅读取既有诊断字段（BPSO particle_evaluations /
    NFA objective_evaluations）。
    """
    if method == "bpso_rata_la":
        cap = configured["cap"]
        consumed = int(diag.get("particle_evaluations", 0))
        return {
            "actual_consumed_search_evaluations": consumed,
            "executed_iterations": int(diag.get("completed_iterations", 0)),
            "executed_search_steps": int(diag.get("completed_iterations", 0)),
            "population_size": int(diag.get("population_size", configured["population_size"])),
            "max_iterations": int(diag.get("max_iterations", configured["max_iterations"])),
            "actual_iterations": int(diag.get("completed_iterations", 0)),
            "fitness_evaluations": consumed,
            "cap_reached": bool(consumed >= cap),
            "soft_deadline_triggered": bool(diag.get("soft_deadline_triggered", False)),
        }
    if method == "nfa_adapted":
        cap = configured["cap"]
        consumed = int(diag.get("objective_evaluations", 0))
        return {
            "actual_consumed_search_evaluations": consumed,
            "executed_iterations": int(diag.get("completed_generations", 0)),
            "executed_search_steps": int(diag.get("completed_pairwise_moves", 0)),
            "population_size": int(diag.get("population_size", configured["population_size"])),
            "max_generations": int(diag.get("max_generations", configured["max_generations"])),
            "actual_generations": int(diag.get("completed_generations", 0)),
            "pairwise_moves": int(diag.get("completed_pairwise_moves", 0)),
            "objective_evaluations": consumed,
            "cap_reached": bool(consumed >= cap),
            "soft_deadline_triggered": bool(diag.get("soft_deadline_triggered", False)),
        }
    return {"actual_consumed_search_evaluations": None, "note": "CARS：无搜索预算"}


def main() -> int:
    stage1 = load_yaml(STAGE1_PROTOCOL)
    pilot = load_yaml(PILOT_CONFIG)

    pcfg = pilot["pilot"]
    seeds = pcfg["seeds"]
    multipliers = pcfg["budget_multipliers"]
    scanned = pcfg["methods"]["scanned"]
    formal_seeds = stage1["seeds"]
    assert not (set(seeds) & set(formal_seeds)), "pilot seeds 与 formal seeds 有交集——停止"

    # Stage-1 协议 multiplier_map（budget 映射唯一权威）
    maps = {
        "bpso_rata_la": stage1["budget_parameter_mapping"]["bpso_rata_la"]["multiplier_map"],
        "nfa_adapted": stage1["budget_parameter_mapping"]["nfa_adapted"]["multiplier_map"],
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    runner = MethodRunner()
    raw_records = []
    start = time.time()
    total = (len(scanned) * len(multipliers) + len(pcfg["methods"]["reference"])) * len(seeds)
    done = 0

    for seed in seeds:
        scen_path = os.path.join(
            _PROJECT, "results", "e1_3_budget", "scenarios",
            "scenario_seed%d_n200.yaml" % seed,
        )
        if not os.path.exists(scen_path):
            raise RuntimeError("pilot 场景缺失: %s" % scen_path)
        scenario_id = "e1_v2_1_pilot_seed%d_n200" % seed

        for method in scanned:
            base_cfg = load_yaml(FROZEN[method])
            for mult in multipliers:
                # multiplier_map 键为字符串（"0.5"/"1.0"/"2.0"/"4.0"）
                map_key = {0.5: "0.5", 1.0: "1.0", 2.0: "2.0", 4.0: "4.0"}[mult]
                cfg = build_scaled_config(method, base_cfg, map_key, maps[method])
                conf_budget = configured_native_budget(method, cfg)
                rec = runner.run(
                    method_id=method,
                    scenario_cfg_path=scen_path,
                    method_config=cfg,
                    method_seed=cfg["method_seed"],
                    hard_timeout_seconds=TIMEOUT,
                )
                done += 1
                diag = rec.get("method_diagnostics") or {}
                bd = extract_budget_diagnostics(method, diag, conf_budget)
                ev = rec.get("evaluator_output") or {}
                sm = ev.get("system_metrics", {}) if ev else {}
                early_stop = bool(bd.get("cap_reached") or bd.get("soft_deadline_triggered"))
                row = {
                    "method": method,
                    "seed": seed,
                    "scenario_id": scenario_id,
                    "budget_multiplier": mult,
                    "configured_native_budget": conf_budget,
                    "actual_consumed_search_evaluations": bd["actual_consumed_search_evaluations"],
                    "executed_iterations": bd.get("executed_iterations"),
                    "executed_search_steps": bd.get("executed_search_steps"),
                    "early_stop": early_stop,
                    "cap_reached": bd.get("cap_reached", False),
                    "soft_deadline_triggered": bd.get("soft_deadline_triggered", False),
                    "timeout": bool(rec.get("runtime_censored", False)),
                    "runtime_ms": rec.get("method_runtime_ms"),
                    "total_wall_time_ms": rec.get("total_wall_time_ms"),
                    "result_status": rec.get("method_status"),
                    "canonical_hash": (rec.get("reproducibility") or {}).get("canonical_hash"),
                    "tssr": sm.get("tssr"),
                    "rbar_eff": sm.get("mean_effective_reliability"),
                    "ubar_eff": sm.get("mean_effective_utility"),
                    "v_r": sm.get("reliability_violation_rate"),
                    "_budget_detail": bd,
                }
                raw_records.append(row)
                print("[%3d/%d] seed=%d %s %s× -> %s consumed=%s rt=%.1fms" % (
                    done, total, seed, method, mult, row["result_status"],
                    row["actual_consumed_search_evaluations"],
                    row["runtime_ms"] or 0.0))

        # CARS 固定参考（不缩放预算）
        cars_cfg = load_yaml(FROZEN["cars"])
        rec = runner.run(
            method_id="cars",
            scenario_cfg_path=scen_path,
            method_config=cars_cfg,
            method_seed=cars_cfg.get("method_seed", 1),
            hard_timeout_seconds=TIMEOUT,
        )
        done += 1
        diag = rec.get("method_diagnostics") or {}
        ev = rec.get("evaluator_output") or {}
        sm = ev.get("system_metrics", {}) if ev else {}
        row = {
            "method": "cars",
            "seed": seed,
            "scenario_id": scenario_id,
            "budget_multiplier": None,           # 固定参考：不进行 budget scaling
            "configured_native_budget": None,
            "actual_consumed_search_evaluations": None,
            "executed_iterations": None,
            "executed_search_steps": None,
            "early_stop": False,
            "cap_reached": False,
            "soft_deadline_triggered": False,
            "timeout": bool(rec.get("runtime_censored", False)),
            "runtime_ms": rec.get("method_runtime_ms"),
            "total_wall_time_ms": rec.get("total_wall_time_ms"),
            "result_status": rec.get("method_status"),
            "canonical_hash": (rec.get("reproducibility") or {}).get("canonical_hash"),
            "tssr": sm.get("tssr"),
            "rbar_eff": sm.get("mean_effective_reliability"),
            "ubar_eff": sm.get("mean_effective_utility"),
            "v_r": sm.get("reliability_violation_rate"),
            "_budget_detail": {"note": "CARS：无搜索预算参数（固定参考）"},
        }
        raw_records.append(row)
        print("[%3d/%d] seed=%d cars (reference) -> %s rt=%.1fms" % (
            done, total, seed, row["result_status"], row["runtime_ms"] or 0.0))

    # ---- 保存 raw ----
    raw_path = os.path.join(OUT_DIR, "pilot_raw.jsonl")
    with open(raw_path, "w", encoding="utf-8") as fh:
        for r in raw_records:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

    # ---- 汇总 ----
    summary = _build_summary(raw_records, scanned, multipliers, seeds)
    summary_path = os.path.join(OUT_DIR, "pilot_summary.json")
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2, sort_keys=True)

    # ---- 完整性 ----
    integrity = {
        "stage": "Stage 2：Pilot 校准",
        "stage_status": "PILOT",
        "pilot_runs": len(raw_records),
        "expected_runs": total,
        "timeout_count": sum(1 for r in raw_records if r["timeout"]),
        "error_count": sum(1 for r in raw_records if r["result_status"] == "METHOD_ERROR"),
        "budget_multipliers": multipliers,
        "pilot_seeds": seeds,
        "formal_seeds_forbidden": formal_seeds,
        "seed_disjoint": bool(not (set(seeds) & set(formal_seeds))),
        "gates": {g: summary["gates"].get(g) for g in ["A", "B", "C", "D"]},
        "raw_records": raw_path,
        "summary": summary_path,
        "elapsed_seconds": round(time.time() - start, 3),
    }
    integrity_path = os.path.join(OUT_DIR, "pilot_integrity.json")
    with open(integrity_path, "w", encoding="utf-8") as fh:
        json.dump(integrity, fh, ensure_ascii=False, indent=2, sort_keys=True)

    print("\n=== Pilot 完成: %d runs, timeout=%d, error=%d ===" % (
        len(raw_records), integrity["timeout_count"], integrity["error_count"]))
    print("Gate 结果:", {g: summary["gates"].get(g) for g in ["A", "B", "C", "D"]})
    return 0


def _build_summary(raw_records, scanned, multipliers, seeds):
    """汇总各方法×档位的 consumed budget / runtime / status + Gate A-D 检查。"""
    summary = {"per_method_per_multiplier": {}, "gates": {}}
    for method in scanned:
        summary["per_method_per_multiplier"][method] = {}
        for mult in multipliers:
            rows = [r for r in raw_records
                    if r["method"] == method and r["budget_multiplier"] == mult]
            summary["per_method_per_multiplier"][method][str(mult)] = {
                "n": len(rows),
                "configured_native_budget": rows[0]["configured_native_budget"] if rows else None,
                "consumed_mean": _mean([r["actual_consumed_search_evaluations"] for r in rows]),
                "consumed_list": [r["actual_consumed_search_evaluations"] for r in rows],
                "runtime_ms_mean": _mean([r["runtime_ms"] for r in rows]),
                "runtime_ms_list": [r["runtime_ms"] for r in rows],
                "status": sorted({r["result_status"] for r in rows}),
                "early_stop_count": sum(1 for r in rows if r["early_stop"]),
                "timeout_count": sum(1 for r in rows if r["timeout"]),
            }
    cars_rows = [r for r in raw_records if r["method"] == "cars"]
    summary["cars_reference"] = {
        "n": len(cars_rows),
        "status": sorted({r["result_status"] for r in cars_rows}),
        "runtime_ms_mean": _mean([r["runtime_ms"] for r in cars_rows]),
        "timeout_count": sum(1 for r in cars_rows if r["timeout"]),
    }

    # ---- Gate A：配置预算单调性 ----
    gate_a = {}
    for method in scanned:
        confs = []
        for mult in multipliers:
            c = summary["per_method_per_multiplier"][method][str(mult)]["configured_native_budget"]
            confs.append(c["cap"] if c else None)
        gate_a[method] = {
            "configured_caps": confs,
            "strictly_increasing": bool(confs == sorted(confs) and len(set(confs)) == len(confs)),
            "note": "配置 cap 单调（0.5<1<2<4）；整数粒度无相等",
        }
    summary["gates"]["A"] = gate_a

    # ---- Gate B：真实消耗预算有效性（未 early-stop/timeout 时总体非递减） ----
    gate_b = {}
    for method in scanned:
        means = [summary["per_method_per_multiplier"][method][str(mult)]["consumed_mean"]
                 for mult in multipliers]
        gate_b[method] = {
            "consumed_mean_by_mult": means,
            "non_decreasing": bool(means == sorted(means)),
            "note": "总体非递减即可；不要求每实例线性（允许 early stop）",
        }
    summary["gates"]["B"] = gate_b

    # ---- Gate C：runtime 可辨识性 ----
    gate_c = {}
    for method in scanned:
        rt = [summary["per_method_per_multiplier"][method][str(mult)]["runtime_ms_mean"]
              for mult in multipliers]
        gate_c[method] = {
            "runtime_mean_by_mult": rt,
            "monotone_or_flat": "flat" if all(abs(r - rt[0]) < 1e-6 for r in rt) else "observable",
            "note": "flat 须检查预算是否进入搜索循环；不要求 T_4x=4*T_1x",
        }
    summary["gates"]["C"] = gate_c

    # ---- Gate D：可运行性 ----
    all_status = {r["result_status"] for r in raw_records}
    gate_d = {
        "crash_or_error": "METHOD_ERROR" in all_status,
        "timeout_count_total": sum(1 for r in raw_records if r["timeout"]),
        "invalid_result": any(r["result_status"] not in
                              ("SUCCESS", "BUDGET_EXHAUSTED", "TIMEOUT", "METHOD_ERROR")
                              for r in raw_records),
        "note": "个别 timeout 正常记录；仅当 4× 几乎全部 timeout 才进入 timeout policy review",
    }
    summary["gates"]["D"] = gate_d
    return summary


def _mean(xs):
    vals = [x for x in xs if x is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


if __name__ == "__main__":
    raise SystemExit(main())
