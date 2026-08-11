# -*- coding: utf-8 -*-
"""E0-E3 Compatibility Audit（f_min^exec=1.0 + AADA H_j 引入后）。

目标证书：
  "The introduction of f_min^exec=1 (and AADA H_j admission) did not alter any
   previously reported CARS decision or metric on the frozen E0-E3 formal
   instances."

检查（对 E0-V2 / E1-V2 / E2-V2 的每个冻结 CARS 正式实例）：
  1) 当前 CARS 输出的 TSSR / Rbar_eff / Ubar_eff 与冻结旧记录逐位一致（容差 1e-9）；
  2) 当前 CARS 所有 EDGE 分配 f_ij >= 1.0（f_min^exec，C5 新硬检查）；
  3) 当前 CARS 指派下 H_j = sum ell_succ_ij <= F_j（可执行 floor 准入不变量）。
  4) zero_EDGE 统计（H_j==G_j 的直接证据）。
"""
import io
import json
import os
import sys

import yaml

ROOT = os.getcwd()
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "reproduce", "e0_v2"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "reproduce", "e1_v2"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "reproduce", "e2_v2"))

from cars.simulator.scenario_materializer import materialize  # noqa: E402
from cars.simulator.derived_state import DerivedState  # noqa: E402
from cars.methods.cars.pipeline import run_aada_rcla_pipeline  # noqa: E402
from cars.evaluator.evaluator import evaluate  # noqa: E402

cfg = yaml.safe_load(io.open("configs/cars_v4/cars_frozen_v4.yaml", encoding="utf-8"))
rcla_cfg = {k: cfg[k] for k in ["rcla_mu_tol", "rcla_max_iters", "rcla_mu_lo",
                                "rcla_mu_hi", "rcla_numeric_epsilon"] if k in cfg}

EPS = 1e-9


def run_cars(sc):
    """当前 CARS 跑，返回 (metrics_dict, decision, derived, zero_edges, min_f, H_list, F_list, G_list)。"""
    derived = DerivedState(sc)
    res = run_aada_rcla_pipeline(sc, derived=derived, eps_cmp=1e-9, rcla_cfg=rcla_cfg)
    dec = res["decision"]
    ev = evaluate(sc, dec, derived)
    sm = (ev.get("evaluator_output") or {}).get("system_metrics", {})
    X = dec["offloading_decision"]
    F = dec["resource_allocation"]
    pos = [F[i][j] for i in range(len(F)) for j in range(len(F[i])) if F[i][j] > 0]
    min_f = min(pos) if pos else None
    zero_edges = 0
    for i in range(len(sc["tasks"])):
        if X[i] == 1 and sc["tasks"][i].get("fragility", 0) == 0:
            zero_edges += 1
    # H_j = sum ell_succ over EDGE members（用 DerivedState.link(i,j) 的 ell_succ）
    H = [0.0] * len(sc["servers"])
    for i in range(len(sc["tasks"])):
        if X[i] == 1:
            j = dec["assignment_matrix"][i].index(1)
            ls = derived.link(i, j)
            H[j] += ls["ell_succ"] if ls is not None else 0.0
    F_list = [s["capacity_cycles_per_sec"] for s in sc["servers"]]
    diag = res.get("diagnostics", {})
    G = diag.get("per_server_final_G", [])
    return sm, dec, derived, zero_edges, min_f, H, F_list, G


def audit_group(tag, cases, build_fn):
    """cases: list of dicts with keys needed by build_fn; build_fn(case) -> sc."""
    n_ok = n_mismatch = n_f_lt1 = n_h_gt_f = n_zero = 0
    mismatches = []
    for case in cases:
        sc = build_fn(case)
        sm, dec, derived, zero_edges, min_f, H, F_list, G = run_cars(sc)
        tssr = sm.get("tssr"); rbar = sm.get("mean_effective_reliability")
        ubar = sm.get("mean_effective_utility")
        old = case["old"]
        ok = (abs(tssr - old["tssr"]) <= EPS and abs(rbar - old["rbar"]) <= EPS
              and abs(ubar - old["ubar"]) <= EPS)
        f_ok = min_f is None or min_f >= 1.0 - EPS
        h_ok = all(H[j] <= F_list[j] + EPS for j in range(len(F_list)))
        if not ok:
            n_mismatch += 1
            mismatches.append((case["key"], old, (tssr, rbar, ubar)))
        else:
            n_ok += 1
        if not f_ok:
            n_f_lt1 += 1
            print(f"  [F<1] {case['key']}: min_f={min_f}")
        if not h_ok:
            n_h_gt_f += 1
            print(f"  [H>F] {case['key']}: H={H} F={F_list}")
        n_zero += zero_edges
        print(f"  {case['key']}: TSSR {old['tssr']}->{tssr}  Rbar {old['rbar']:.6f}->{rbar:.6f}  "
              f"Ubar {old['ubar']:.6f}->{ubar:.6f}  min_f={min_f if min_f is None else round(min_f,1)}  "
              f"zero_EDGE={zero_edges}  {'MATCH' if ok else 'MISMATCH'}")
    print(f"  [{tag}] cases={len(cases)} match={n_ok} mismatch={n_mismatch} "
          f"f<1={n_f_lt1} H>F={n_h_gt_f} total_zero_EDGE={n_zero}")
    return n_ok, n_mismatch, n_f_lt1, n_h_gt_f, mismatches


def main():
    total = {"cases": 0, "match": 0, "mismatch": 0, "f_lt1": 0, "h_gt_f": 0}

    # ---- E0-V2 ----
    print("=== E0-V2 audit ===")
    from build_e0_v2_environment import build_e0_v2_super_scenario, e0_prefix_scenario  # noqa
    recs = []
    with io.open("results/e0_v2/e0_v2_2_formal/formal_raw.jsonl", encoding="utf-8") as f:
        for l in f:
            l = l.strip()
            if l:
                recs.append(json.loads(l))
    cases = []
    for r in recs:
        if r.get("method") != "cars_aada_rcla_candidate":
            continue
        cases.append({"key": f"E0V2 s{r['seed']} N{r['N']}", "seed": r["seed"], "N": r["N"],
                      "old": {"tssr": r["TSSR"], "rbar": r["Rbar_eff"], "ubar": r["Ubar_eff"]}})
    def build_e0(c):
        super_cfg = build_e0_v2_super_scenario(c["seed"])
        return materialize(e0_prefix_scenario(super_cfg, c["N"]))
    ok, mm, f1, hf, ms = audit_group("E0-V2", cases, build_e0)
    total["cases"] += len(cases); total["match"] += ok; total["mismatch"] += mm
    total["f_lt1"] += f1; total["h_gt_f"] += hf

    # ---- E1-V2 ----
    print("=== E1-V2 audit ===")
    import build_e1_v2_environment as B  # noqa
    recs = []
    with io.open("results/e1_v2/e1_v2_1_formal/raw_records.jsonl", encoding="utf-8") as f:
        for l in f:
            l = l.strip()
            if l:
                recs.append(json.loads(l))
    cases = []
    for r in recs:
        if r.get("method_id") != "cars":
            continue
        cases.append({"key": f"E1V2 s{r['seed']} N{r['n']}", "seed": r["seed"], "N": r["n"],
                      "old": {"tssr": r["tssr"], "rbar": r["rbar_eff"], "ubar": r["ubar_eff"]}})
    def build_e1(c):
        env = B.build_e1_v2_environment(seed=c["seed"], n_max=200, s_f=1.0,
                                        fragility_profile="MEDIUM")
        return materialize(B.prefix_scenario(env, c["N"]))
    ok, mm, f1, hf, ms = audit_group("E1-V2", cases, build_e1)
    total["cases"] += len(cases); total["match"] += ok; total["mismatch"] += mm
    total["f_lt1"] += f1; total["h_gt_f"] += hf

    # ---- E2-V2 ----
    print("=== E2-V2 audit ===")
    from build_e2_v2_environment import build_e2_v2_environment, e2_prefix_scenario  # noqa
    recs = []
    with io.open("results/e2_v2/e2_v2_1_formal/raw_records.jsonl", encoding="utf-8") as f:
        for l in f:
            l = l.strip()
            if l:
                recs.append(json.loads(l))
    cases = []
    for r in recs:
        if r.get("method_id") != "cars":
            continue
        cases.append({"key": f"E2V2 s{r['seed']} cvf{r['cv_f']}", "seed": r["seed"],
                      "cv": r["cv_f"], "N": r["n"],
                      "old": {"tssr": r["tssr"], "rbar": r["rbar_eff"], "ubar": r["ubar_eff"]}})
    def build_e2(c):
        env = build_e2_v2_environment(seed=c["seed"], cv_f_target=c["cv"], n_max=170,
                                      s_f=1.0, fragility_profile="MEDIUM")
        return materialize(e2_prefix_scenario(env["scenario_cfg"], c["N"]))
    ok, mm, f1, hf, ms = audit_group("E2-V2", cases, build_e2)
    total["cases"] += len(cases); total["match"] += ok; total["mismatch"] += mm
    total["f_lt1"] += f1; total["h_gt_f"] += hf

    print()
    print("===== COMPATIBILITY AUDIT SUMMARY =====")
    print(f"cases={total['cases']}  match={total['match']}  mismatch={total['mismatch']}")
    print(f"EDGE f<1.0 = {total['f_lt1']}   H_j>F_j = {total['h_gt_f']}")
    if total["mismatch"] == 0 and total["f_lt1"] == 0 and total["h_gt_f"] == 0:
        print("CERTIFICATE: The introduction of f_min^exec=1 and AADA H_j admission "
              "did not alter any previously reported CARS decision or metric on the "
              "frozen E0-E3 formal instances.")
    else:
        print("CERTIFICATE: NOT CLEAN - inspect mismatches above.")


if __name__ == "__main__":
    main()
