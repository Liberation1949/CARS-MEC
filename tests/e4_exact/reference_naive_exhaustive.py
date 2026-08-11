# -*- coding: utf-8 -*-
"""独立 naive exhaustive 验证器（E4-EXACT-1；E4_EXACT_ORACLE_CONTRACT_V1 §8-F）。

要求（合同）：
- 尽可能简单；对 N<=3、M<=2 进行完整 naive enumeration；
- 不调用 production pruning（feasibility/doomed）与 production branch ordering；
- 连续子问题用独立实现的枚举 + 二分（不 import exact_oracle.continuous_solver）；
- 与 production Oracle 独立比较（objective tuple 一致）。

只共用公共底座：Scenario/DerivedState/物理模型/统一 Evaluator（这些是 P0 定义的一部分，
不是 Oracle 实现）。comparator 独立实现（三层字典序）。
"""

from __future__ import annotations

import itertools
import math
from typing import Callable, Dict, List, Optional, Tuple

from cars.evaluator.evaluator import evaluate as _evaluate
from cars.evaluator.status_codes import EvaluatorStatus
from cars.simulator.derived_state import DerivedState

EPS = 1.0e-9


# ---------------------------------------------------------------------------
# 独立字典序 comparator
# ---------------------------------------------------------------------------
def naive_lex_compare(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> int:
    for x, y in zip(a, b):
        if abs(x - y) > EPS:
            return 1 if x > y else -1
    return 0


# ---------------------------------------------------------------------------
# 独立连续求解：每服务器固定成功集 S，枚举 active set + 二分（独立编码）
# ---------------------------------------------------------------------------
def _rval(rtx, a, f):
    return rtx * math.exp(-a / f)


def _rprime(rtx, a, f):
    return rtx * a * math.exp(-a / f) / (f * f)


def _f_from_mu(rtx, a, ell, mu, it=200):
    if mu <= 0.0:
        return None
    rp_ell = _rprime(rtx, a, ell)
    if mu > rp_ell:
        return None
    if abs(mu - rp_ell) <= 1.0e-15 * max(1.0, rp_ell):
        return ell
    lo, hi = ell, max(ell * 2.0, 1.0)
    while _rprime(rtx, a, hi) > mu:
        hi *= 2.0
    for _ in range(it):
        mid = 0.5 * (lo + hi)
        if _rprime(rtx, a, mid) > mu:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def naive_server_solve(tasks: List[Dict], F_j: float, it: int = 200) -> Optional[Dict]:
    """独立 KKT：固定成功集 tasks（{index, ell_R, R_tx, a, A_u, K_u}）求 Tier-2 最优 F。"""
    pos = [t for t in tasks if t["a"] > 0.0]
    zero = [t for t in tasks if t["a"] == 0.0]
    F_avail = F_j - len(zero) * 1.0e-9
    if F_avail < -EPS:
        return None
    best = None
    k = len(pos)
    for mask in range(1 << k):
        active = [pos[t] for t in range(k) if (mask >> t) & 1]
        free = [pos[t] for t in range(k) if not ((mask >> t) & 1)]
        floor_sum = sum(t["ell_R"] for t in active)
        C = F_avail - floor_sum
        if C < -EPS:
            continue
        f = {t["index"]: t["ell_R"] for t in active}
        if free:
            if C < sum(t["ell_R"] for t in free) - EPS:
                continue
            mu_ub = min(_rprime(t["R_tx"], t["a"], t["ell_R"]) for t in free)

            def _tot(m):
                s = 0.0
                for t in free:
                    fv = _f_from_mu(t["R_tx"], t["a"], t["ell_R"], m, it)
                    if fv is None:
                        return math.inf
                    s += fv
                return s

            lo_m, hi_m = 0.0, mu_ub
            for _ in range(it):
                mid = 0.5 * (lo_m + hi_m)
                if _tot(mid) > C:
                    lo_m = mid
                else:
                    hi_m = mid
            mu = 0.5 * (lo_m + hi_m)
            ok = True
            for t in active:
                if _rprime(t["R_tx"], t["a"], t["ell_R"]) > mu + EPS:
                    ok = False
                    break
            if not ok:
                continue
            for t in free:
                fv = _f_from_mu(t["R_tx"], t["a"], t["ell_R"], mu, it)
                if fv is None:
                    ok = False
                    break
                f[t["index"]] = fv
            if not ok:
                continue
            # 数值防护：sum f 略超容量时缩放 free 部分（与 production 一致）
            tot = sum(f.values())
            if tot > F_j + EPS:
                free_tot = sum(f[t["index"]] for t in free)
                if free_tot > EPS:
                    scale = (free_tot - (tot - F_j)) / free_tot
                    scale = max(0.0, scale)
                    for t in free:
                        f[t["index"]] = f[t["index"]] * scale
        R2 = sum(_rval(t["R_tx"], t["a"], f[t["index"]]) for t in pos)
        if best is None or R2 > best[0] + EPS:
            best = (R2, dict(f))
    if best is None:
        return None
    fmap = best[1]
    for t in zero:
        fmap[t["index"]] = 1.0e-9
    R2 = best[0] + sum(t["R_tx"] for t in zero)
    U3 = sum(t["K_u"] - t["A_u"] / fmap[t["index"]] for t in tasks)
    return {"f": fmap, "R2": R2, "U3": U3}


# ---------------------------------------------------------------------------
# 独立完整枚举
# ---------------------------------------------------------------------------
def naive_exhaustive(
    scenario: Dict,
    derived: Optional[DerivedState] = None,
    evaluator: Optional[Callable] = None,
    max_n: int = 3,
    max_m: int = 2,
) -> Dict:
    """对 N<=3, M<=2 实例做完整 naive 枚举，返回 P0 lexicographic optimum。"""
    derived = derived if derived is not None else DerivedState(scenario)
    ev = evaluator if evaluator is not None else _evaluate
    n = len(scenario["tasks"])
    m = len(scenario["servers"])
    if n > max_n or m > max_m:
        raise ValueError("naive validator 仅支持 N<=%d, M<=%d" % (max_n, max_m))

    edge_servers = [[] for _ in range(n)]
    for i in range(n):
        for j in range(m):
            ls = derived.link(i, j)
            if ls is not None and ls["e_phy"] == 1:
                edge_servers[i].append(j)

    best = None  # (tup, decision)
    for combo in itertools.product(*[[None] + sorted(edge_servers[i]) for i in range(n)]):
        X = [0] * n
        A = [[0] * m for _ in range(n)]
        for i, act in enumerate(combo):
            if act is not None:
                X[i] = 1
                A[i][int(act)] = 1
        groups: Dict[int, List[int]] = {}
        for i in range(n):
            for j in range(m):
                if A[i][j] == 1:
                    groups.setdefault(j, []).append(i)
        per_server = []
        for j in range(m):
            g = groups.get(j, [])
            per_server.append(
                [list(c) for r in range(len(g) + 1) for c in itertools.combinations(g, r)]
            )
        for scombo in itertools.product(*per_server):
            fmap_all = {}
            feasible = True
            for j in range(m):
                S_j = scombo[j]
                tasks = []
                for i in S_j:
                    ls = derived.link(i, j)
                    server = derived.server_state[j]
                    task = scenario["tasks"][i]
                    loc = derived.task_local[i]
                    a = server["lambda_j"] * task["fragility"] * task["cpu_cycles"]
                    alpha = task["delay_weight"]
                    beta = task["energy_weight"]
                    c = task["cpu_cycles"]
                    T_loc = loc["T_loc"]
                    E_loc = loc["E_loc"]
                    T_tx = ls["T_tx"]
                    E_tx = ls["E_tx"]
                    A_u = alpha * c / T_loc
                    K_u = alpha * (T_loc - T_tx) / T_loc + beta * (E_loc - E_tx) / E_loc
                    tasks.append(
                        {
                            "index": i,
                            "ell_R": ls["ell_R"],
                            "R_tx": ls["R_tx"],
                            "a": a,
                            "A_u": A_u,
                            "K_u": K_u,
                        }
                    )
                sol = naive_server_solve(tasks, derived.server_state[j]["F_j"])
                if sol is None:
                    feasible = False
                    break
                for i, fval in sol["f"].items():
                    fmap_all[i] = (j, fval)
            if not feasible:
                continue
            F = [[0.0] * m for _ in range(n)]
            for i, (j, fval) in fmap_all.items():
                F[i][j] = fval
            decision = {
                "schema_version": "CARS_ACTIVE_SCHEMA_V4",
                "offloading_decision": list(X),
                "assignment_matrix": [list(r) for r in A],
                "resource_allocation": [list(r) for r in F],
            }
            ev_out = ev(scenario, decision, derived)
            if ev_out["evaluator_status"] != EvaluatorStatus.VALID:
                continue
            sm = ev_out["evaluator_output"]["system_metrics"]
            tup = (sm["tssr"], sm["mean_effective_reliability"], sm["mean_effective_utility"])
            if best is None or naive_lex_compare(tup, best[0]) > 0:
                best = (tup, decision)
    if best is None:
        return {"found": False, "objective_tuple": None, "decision": None}
    return {"found": True, "objective_tuple": list(best[0]), "decision": best[1]}
