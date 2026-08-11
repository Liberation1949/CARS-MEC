# -*- coding: utf-8 -*-
"""E0-V2-1 Pilot runner 骨架（E0-V2-0 冻结；本阶段只提供工具，不运行正式 Pilot）。

阶段合同（configs/e0_v2/e0_v2_protocol.yaml）：
- Pilot 网格 N={20,40,60,80,100,120,150,180,220,260} × seeds [201..205]（NOT_FORMAL）；
- 主方法：reliability_only / bpso_rata_la / cars_aada_rcla_candidate；
  诊断控制：local_only（不入主图）；
- 嵌套任务：每 seed 生成一次 N_max=260 超场景，prefix 到各 N（Gamma 前缀链）；
- 统一 Evaluator 唯一正式评价（所有方法同源）；shared timeout=30s；
- 指标：正文核心（TSSR/Rbar_eff/Ubar_eff/V_R）+ 机制诊断
  （V_F / median(f/ell^R) / max_G_over_F / LI_dem / edge_ratio）；
- 旧语义字段（V_D/deadline/gamma/Q/Z/lambda_eff）全部禁用；
- 禁止固定 collapse threshold；Pilot 只可调整 N 覆盖范围一次。

运行方式：
- baseline（reliability_only/bpso_rata_la/local_only）：统一 MethodRunner
  （R5 公平边界：子进程隔离 + 硬超时 + 统一 Evaluator + 失败计分）；
- 候选（cars_aada_rcla_candidate）：阶段 runner 直接实例化
  （候选不在正式 Registry；统一 Evaluator 唯一正式评价，与 baseline 同源）。

用法（正式 Pilot 在 E0-V2-1 运行；本阶段仅冒烟）：
  python scripts/reproduce/e0_v2/run_e0_v2_pilot.py --smoke   # 微型冒烟（工具验证）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
import time

import yaml

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(_PROJECT, "src"))
sys.path.insert(0, os.path.join(_PROJECT, "scripts", "reproduce", "e0_v2"))

from build_e0_v2_environment import (  # noqa: E402
    E0_FORMAL_SEEDS,
    E0_N_MAX,
    E0_PILOT_N_GRID,
    E0_PILOT_SEEDS,
    build_e0_v2_super_scenario,
    e0_prefix_scenario,
)
from cars.evaluator import evaluator as ev  # noqa: E402
from cars.runner.runner import MethodRunner  # noqa: E402
from cars.simulator.derived_state import DerivedState  # noqa: E402
from cars.simulator.scenario_materializer import materialize  # noqa: E402

# ---------------------------------------------------------------------------
# 冻结规格（与 configs/e0_v2/e0_v2_protocol.yaml 一致）
# ---------------------------------------------------------------------------
EPS = 1.0e-9
TIMEOUT = 30.0                      # R6 冻结 shared timeout
METHOD_SEED = 1
MAIN_METHODS = ["reliability_only", "bpso_rata_la", "cars_aada_rcla_candidate"]
DIAGNOSTIC_METHODS = ["local_only"]
ALL_METHODS = MAIN_METHODS + DIAGNOSTIC_METHODS
CANDIDATE_ID = "cars_aada_rcla_candidate"

METHOD_CONFIG_PATHS = {
    "reliability_only": "configs/r6/frozen_method_configs/reliability_only_frozen.yaml",
    "bpso_rata_la": "configs/r6/frozen_method_configs/bpso_frozen.yaml",
    "local_only": "configs/r6/frozen_method_configs/local_only_frozen.yaml",
}
CANDIDATE_CONFIG_PATH = "configs/cr_algorithm_redesign/candidate_v1.yaml"


def _load_yaml(rel: str) -> dict:
    with open(os.path.join(_PROJECT, rel), "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _hash(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


# ---------------------------------------------------------------------------
# E0 机制指标（对任意方法的 decision + 公共 DerivedState；Oracle 可由测试独立复算）
# ---------------------------------------------------------------------------
def compute_e0_mechanism_metrics(scen: dict, derived: DerivedState, decision: dict) -> dict:
    """计算 E0 机制诊断指标（正文 III-E.5 + 用户 2026-08-09 设计）。

    - V_F（resource-underfloor ratio）：|{i in Gamma_edge: f_ij < ell_R_ij}| / |Gamma_edge|
    - chi_ij = f_ij / ell_R_ij（对卸载任务）
    - median(f/ell^R)：卸载任务 chi 中位数
    - max_G_over_F = max_j (sum_{i in Gamma_j} ell_R_ij) / F_j
    - LI_dem：正文 III-E.5（rho_j^dem = sum_i a_ij * f_i^loc / F_j）
    - edge_ratio = |Gamma_edge| / N
    """
    x = decision["offloading_decision"]
    a = decision["assignment_matrix"]
    f = decision["resource_allocation"]
    n = len(x)
    m = len(a[0]) if a else 0

    device_by_id = {d["device_id"]: d for d in scen["devices"]}
    task_device = {t["task_id"]: t["device_id"] for t in scen["tasks"]}
    f_loc = []
    for i, t in enumerate(scen["tasks"]):
        d = device_by_id.get(task_device[t["task_id"]])
        f_loc.append(float(d["local_cpu_rate"]) if d is not None else 0.0)
    F_j = [float(s["capacity_cycles_per_sec"]) for s in scen["servers"]]

    edge_tasks = [i for i in range(n) if x[i] == 1]
    edge_ratio = len(edge_tasks) / n if n else 0.0

    underfloor = 0
    chis = []
    G = [0.0] * m
    for i in edge_tasks:
        j = max(range(m), key=lambda jj: a[i][jj]) if m else -1
        if j < 0:
            continue
        ls = derived.link(i, j)
        ellR = ls["ell_R"] if ls is not None else 0.0
        fij = float(f[i][j])
        if ellR > 0.0:
            chi = fij / ellR
            chis.append(chi)
            if fij < ellR - EPS:
                underfloor += 1
        G[j] += ellR

    max_gf = max((G[j] / F_j[j] for j in range(m)), default=0.0) if m else 0.0

    rho_dem = []
    for j in range(m):
        if F_j[j] <= 0.0:
            rho_dem.append(0.0)
            continue
        s = sum(f_loc[i] for i in range(n) if a[i][j] == 1)
        rho_dem.append(s / F_j[j])
    rho_bar = sum(rho_dem) / m if m else 0.0
    li_dem = float(sum((r - rho_bar) ** 2 for r in rho_dem) / m) if m else 0.0

    return {
        "edge_task_count": len(edge_tasks),
        "edge_ratio": round(edge_ratio, 6),
        "V_F": round(underfloor / len(edge_tasks), 6) if edge_tasks else 0.0,
        "V_F_underfloor_count": underfloor,
        "median_f_over_ellR": round(statistics.median(chis), 6) if chis else None,
        "chi_count": len(chis),
        "max_G_over_F": round(max_gf, 6),
        "LI_dem": round(li_dem, 6),
    }


def _run_candidate(scen, derived):
    """候选 AADA-RCLA：直接实例化 + 统一 Evaluator（与 baseline 同源评价）。"""
    from cars.methods.cars.method import CarsMethod
    from cars.methods.protocol import MethodContext

    cfg = _load_yaml(CANDIDATE_CONFIG_PATH)
    m = CarsMethod(cfg)
    ctx = MethodContext(
        scenario=scen,
        derived=derived,
        config=cfg,
        method_seed=METHOD_SEED,
        soft_deadline_seconds=TIMEOUT - max(1.0, 0.1 * TIMEOUT),
        hard_timeout_seconds=TIMEOUT,
    )
    t0 = time.monotonic()
    prop = m.run(ctx)
    runtime_ms = (time.monotonic() - t0) * 1000.0
    if prop.decision is None:
        return {
            "method": CANDIDATE_ID, "method_status": prop.method_status,
            "timed_out": bool(prop.timed_out), "method_runtime_ms": round(runtime_ms, 3),
            "TSSR": None, "Rbar_eff": None, "Ubar_eff": None, "V_R": None,
            "mechanism": None, "evaluator_status": None,
        }
    out = ev.evaluate(scen, prop.decision, derived)
    sm = (out.get("evaluator_output") or {}).get("system_metrics") or {}
    return {
        "method": CANDIDATE_ID,
        "method_status": prop.method_status,
        "timed_out": bool(prop.timed_out),
        "method_runtime_ms": round(runtime_ms, 3),
        "TSSR": sm.get("tssr"),
        "Rbar_eff": sm.get("mean_effective_reliability"),
        "Ubar_eff": sm.get("mean_effective_utility"),
        "V_R": sm.get("reliability_violation_rate"),
        "evaluator_status": out["evaluator_status"].value,
        "mechanism": compute_e0_mechanism_metrics(scen, derived, prop.decision),
    }


def _run_baseline(runner, method_id: str, scen_path: str, scen, derived):
    """统一 MethodRunner 运行 baseline（R5 公平边界 + 统一 Evaluator）。

    MethodRunner record 不含 scenario/derived 对象；机制指标用 runner 侧
    同一 materialize 出的 scen/derived 计算（与候选同源；确定性）。
    """
    cfg = _load_yaml(METHOD_CONFIG_PATHS[method_id])
    record = runner.run(
        method_id=method_id,
        scenario_cfg_path=scen_path,
        method_config=cfg,
        method_seed=METHOD_SEED,
        hard_timeout_seconds=TIMEOUT,
    )
    sm = (record.get("evaluator_output") or {}).get("system_metrics") or {}
    dec = record.get("decision")
    mech = compute_e0_mechanism_metrics(scen, derived, dec) if dec else None
    return {
        "method": method_id,
        "method_status": record.get("method_status"),
        "timed_out": bool(record.get("timed_out")),
        "method_runtime_ms": round(float(record.get("method_runtime_ms") or 0.0), 3),
        "TSSR": sm.get("tssr"),
        "Rbar_eff": sm.get("mean_effective_reliability"),
        "Ubar_eff": sm.get("mean_effective_utility"),
        "V_R": sm.get("reliability_violation_rate"),
        "evaluator_status": record.get("evaluator_status"),
        "mechanism": mech,
    }


def run_pilot(seeds, n_grid, out_dir, smoke: bool = False) -> int:
    """执行 Pilot 网格（冒烟模式写 tooling_smoke；正式 Pilot 在 E0-V2-1）。"""
    os.makedirs(out_dir, exist_ok=True)
    scen_dir = os.path.join(out_dir, "scenarios")
    os.makedirs(scen_dir, exist_ok=True)
    raw_path = os.path.join(out_dir, "pilot_raw.jsonl")
    summary_path = os.path.join(out_dir, "pilot_summary.json")

    runner = MethodRunner()
    records = []
    n_runs = 0
    t_start = time.monotonic()
    for seed in seeds:
        super_cfg = build_e0_v2_super_scenario(seed=seed, n_max=E0_N_MAX)
        for n in n_grid:
            cfg = e0_prefix_scenario(super_cfg, n)
            scen = materialize(cfg)
            derived = DerivedState(scen)
            scen_path = os.path.join(scen_dir, "scenario_seed%d_n%d.yaml" % (seed, n))
            with open(scen_path, "w", encoding="utf-8") as fh:
                yaml.safe_dump(cfg, fh, allow_unicode=True, sort_keys=False)
            with open(scen_path, "rb") as fh:
                scen_hash = hashlib.sha256(fh.read()).hexdigest()

            for method in ALL_METHODS:
                if method == CANDIDATE_ID:
                    rec = _run_candidate(scen, derived)
                else:
                    rec = _run_baseline(runner, method, scen_path, scen, derived)
                record = {
                    "seed": seed,
                    "N": n,
                    "scenario_id": cfg.get("scenario_id"),
                    "scenario_hash16": scen_hash[:16],
                    "scenario_hash": scen_hash,
                    "paired_scenario_shared": True,
                    "formal_seed_used": False,
                    "pilot_seed_used": True,
                    **rec,
                }
                records.append(record)
                n_runs += 1
                if smoke:
                    print("  [smoke] seed=%d N=%d %s status=%s TSSR=%s" % (
                        seed, n, record["method"], record["method_status"], record["TSSR"]))

    elapsed_s = time.monotonic() - t_start
    with open(raw_path, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    # 汇总（跨 seed 按 N x method 均值）
    summary = {
        "grid": n_grid,
        "seeds": seeds,
        "methods": ALL_METHODS,
        "n_runs": n_runs,
        "elapsed_seconds": round(elapsed_s, 2),
        "status_counts": _status_counts(records),
        "per_cell": _per_cell_summary(records),
        "smoke": smoke,
        "note": "pilot NOT_FORMAL；不进入正式统计",
    }
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    print("written:", raw_path)
    print("written:", summary_path)
    print("n_runs:", n_runs, "| elapsed_s:", round(elapsed_s, 2))
    return 0


def _status_counts(records) -> dict:
    from collections import Counter
    return dict(Counter(r["method_status"] for r in records))


def _per_cell_summary(records) -> dict:
    cells = {}
    for r in records:
        key = "%s|%s" % (r["N"], r["method"])
        cells.setdefault(key, []).append(r)
    out = {}
    for key, rs in cells.items():
        tssr_vals = [r["TSSR"] for r in rs if r["TSSR"] is not None]
        out[key] = {
            "TSSR_mean": round(statistics.mean(tssr_vals), 6) if tssr_vals else None,
            "TSSR_std": round(statistics.pstdev(tssr_vals), 6) if len(tssr_vals) > 1 else None,
            "n": len(rs),
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="E0-V2-1 Pilot runner（E0-V2-0 工具骨架）")
    ap.add_argument("--smoke", action="store_true", help="微型冒烟（工具验证；写 tooling_smoke）")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--n-grid", default=None, help="逗号分隔 N 列表（覆盖默认；仅冒烟/调试）")
    ap.add_argument("--seeds", default=None, help="逗号分隔 seeds（覆盖默认；仅冒烟/调试）")
    args = ap.parse_args()

    if args.smoke:
        seeds = [201]
        n_grid = [20, 40]
        out_dir = args.out_dir or os.path.join(_PROJECT, "results", "e0_v2", "tooling_smoke")
        return run_pilot(seeds=seeds, n_grid=n_grid, out_dir=out_dir, smoke=True)
    # 正式 Pilot 路径（E0-V2-1 授权后使用；本阶段禁止运行）
    seeds = [int(s) for s in args.seeds.split(",")] if args.seeds else E0_PILOT_SEEDS
    n_grid = [int(s) for s in args.n_grid.split(",")] if args.n_grid else E0_PILOT_N_GRID
    if any(s in E0_FORMAL_SEEDS for s in seeds):
        print("error: formal seeds forbidden in pilot")
        return 2
    out_dir = args.out_dir or os.path.join(_PROJECT, "results", "e0_v2", "e0_v2_1_pilot")
    return run_pilot(seeds=seeds, n_grid=n_grid, out_dir=out_dir, smoke=False)


if __name__ == "__main__":
    sys.exit(main())
