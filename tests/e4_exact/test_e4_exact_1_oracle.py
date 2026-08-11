# -*- coding: utf-8 -*-
"""E4-EXACT-1 冻结测试（T1-T44）：Exact Oracle 实现与正确性验证。

依据：E4-EXACT-0 合同（E4_EXACT_ORACLE_CONTRACT_V1）、E4-EXACT-1 阶段合同 §八（测试组 A-G）、
experiment_docs/III_VII.md IV 章（P0）、Contract V4、Schema V4、统一 Evaluator。

分组：
  A. Comparator（T1-T6）；B. Enumeration（T7-T12）；C. Safe pruning（T13-T16）；
  D. Continuous solver（T17-T24）；E. End-to-end Oracle（T25-T34）；
  F. Independence cross-check（production == naive）；G. Contract/integrity（T35-T44）。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from e4_exact import _scenario_factory as sf
from e4_exact.reference_naive_exhaustive import naive_exhaustive
from cars.evaluator.evaluator import evaluate as evaluator_evaluate
from cars.exact_oracle import continuous_solver
from cars.exact_oracle import discrete_enumerator
from cars.exact_oracle import feasibility
from cars.exact_oracle.certificate import CERTIFIED_NUMERICAL_EXACT, EXACT_OPTIMAL
from cars.exact_oracle.lexicographic import EPS_CMP, lex_compare, objective_tuple
from cars.exact_oracle.oracle import solve_exact
from cars.simulator.derived_state import DerivedState

# ---------------------------------------------------------------------------
# 路径与 Pre-state 基线（E4-EXACT-1 开始时刻）
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_TESTS = os.path.dirname(_HERE)
ROOT = os.path.dirname(_TESTS)

PRESTATE = {
    # MATH-FMIN-CR-R2 + AADA-H_j 同步（2026-08-11）：rcla/aada/state/__init__ 引入
    # f_min^exec 下限与 H_j 可执行 floor 准入 -> methods_dir hash 更新
    "src/cars/methods_dir": "f44e60fa9b720fdfbe69ac27ba53d8fcf311db4c2a91f7571ff529f5f4e24331",
    # MATH-FMIN-CR-R2：constraints.py C5 引入 f_min^exec 硬检查 -> evaluator_dir hash 更新
    "src/cars/evaluator_dir": "0df96aa3fc786b7b77893019c545ecdc6660697d4a070d87d3ae88ed0814d8e3",
    "reports/contracts/CARS_EXECUTABLE_THEORY_CONTRACT_V4.md": "79227f233c13bf92",
    "schemas/CARS_ACTIVE_SCHEMA_V4_dir": "3b2bcc04a1e0e3e7b80f5d4653904a8065cb16cd140558bc45e58924f276def8",
    # NOTE(2026-08-09 22:00)：experiment_docs/III_VII.md 在 E4-EXACT-1 阶段内被外部修改
    # （hash 6248e905 -> 490b4ca5，mtime 22:00:00；E4-EXACT-1 无任何写 experiment_docs 的代码；
    #  详见 E4-EXACT-1 报告 W-E4X1-XX）。T41 基线以外部修改后快照为准，检查 E4-EXACT-1 后续不再变化。
    "experiment_docs/III_VII.md": "490b4ca59c21ae13",
    "configs/e4_v2_dir": "463d984474914b889ccf24d5319cacd8a10975d89f6d91441f9a11e60810bb83",
    "data_files": 77,
    "data_bytes": 65721295433,
}


def _dir_sha256(root):
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
        h.update(rel.encode("utf-8"))
        h.update(b"\x00")
        h.update(raw)
        h.update(b"\x00")
    return h.hexdigest()


def _file_sha16(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# 任务参数模板（确定性；构造可控的本地成功/失败）
# ---------------------------------------------------------------------------
def _task(local_cpu_rate, local_failure_rate, fragility, cpu_cycles,
          min_rel=0.9, delay_weight=0.5, energy_weight=0.5):
    return {
        "local_cpu_rate": local_cpu_rate,
        "local_failure_rate": local_failure_rate,
        "switch_capacitance": 1.0e-27,
        "tx_power_watts": 0.1,
        "data_bits": 1.0e6,
        "cpu_cycles": cpu_cycles,
        "fragility": fragility,
        "delay_weight": delay_weight,
        "energy_weight": energy_weight,
        "min_reliability": min_rel,
        "deadline_seconds": 100.0,
    }


def task_local_ok():
    """本地成功任务：R_loc = exp(-5e-9*1e-9*1) ~ 1.0 >= 0.9。"""
    return _task(1.0e9, 5.0e-9, 1.0e-9, 1.0e9)


def task_local_fail():
    """本地失败任务：R_loc = exp(-0.6*0.001*200) = 0.887 < 0.9；卸载可达。"""
    return _task(1.0e9, 0.6, 0.001, 2.0e11)


def server_default(capacity=1.0e10, lambda_j=1.0e-9):
    return {"capacity_cycles_per_sec": capacity, "nominal_failure_rate": lambda_j}


def full_links(n, m):
    """全连接链路（R_tx=0.99）。"""
    return {(i, j): sf.default_link_spec() for i in range(n) for j in range(m)}


def run_prod(scenario, mode=discrete_enumerator.EXACT_PRUNED, **cfg):
    return solve_exact(scenario, solver_cfg={"eps_cmp": EPS_CMP, **cfg}, mode=mode)


# ===========================================================================
# A. Comparator tests（T1-T6）
# ===========================================================================
def test_t1_tier1_priority():
    assert lex_compare((0.95, 0.1, 0.1), (0.90, 0.99, 0.99)) == 1
    assert lex_compare((0.90, 0.99, 0.99), (0.95, 0.1, 0.1)) == -1


def test_t2_tier2_conditional():
    assert lex_compare((0.90, 0.82, 0.1), (0.90, 0.79, 0.99)) == 1
    assert lex_compare((0.90, 0.79, 0.99), (0.90, 0.82, 0.1)) == -1


def test_t3_tier3_conditional():
    assert lex_compare((0.90, 0.80, 0.60), (0.90, 0.80, 0.50)) == 1
    assert lex_compare((0.90, 0.80, 0.50), (0.90, 0.80, 0.60)) == -1


def test_t4_full_objective_tie():
    assert lex_compare((0.9, 0.8, 0.6), (0.9, 0.8, 0.6)) == 0
    assert lex_compare((0.9, 0.8, 0.6), (0.9 + 1e-12, 0.8, 0.6)) == 0


def test_t5_deterministic_tie_break():
    # 等价时保持先遇到的候选（确定性 canonical tie-break；不改变 P0 最优值）
    from cars.exact_oracle.lexicographic import deterministic_tie_break_chosen
    assert deterministic_tie_break_chosen((0.9, 0.8, 0.6), (0.9, 0.8, 0.6)) is True
    assert deterministic_tie_break_chosen((0.9, 0.8, 0.6), (0.9, 0.8, 0.7)) is False


def test_t6_not_weighted_sum():
    # 加权和与字典序判定相反的例子（证明 comparator 不是加权和）
    def wsum(t):
        return 0.4 * t[0] + 0.3 * t[1] + 0.3 * t[2]
    a = (0.90, 0.80, 0.40)
    b = (0.85, 0.85, 0.85)
    assert lex_compare(a, b) == 1
    assert wsum(a) < wsum(b)


# ===========================================================================
# B. Enumeration completeness（T7-T12）
# ===========================================================================
def _model(n, m, task_fn=task_local_ok):
    sc = sf.make_scenario("enum", [task_fn() for _ in range(n)],
                          [server_default() for _ in range(m)], full_links(n, m))
    return sc, OracleModelProxy(sc)


class OracleModelProxy:
    """轻量代理：直接用 OracleModel（惰性导入避免循环）。"""

    def __init__(self, scenario):
        from cars.exact_oracle.model import OracleModel
        self.model = OracleModel(scenario)


def test_t7_theoretical_states_n1m1():
    sc = sf.make_scenario("s", [task_local_ok()], [server_default()], full_links(1, 1))
    from cars.exact_oracle.model import OracleModel
    model = OracleModel(sc)
    assert discrete_enumerator.theoretical_state_bound(model) == 2  # LOCAL + 1 EDGE


def test_t8_theoretical_states_n2m2():
    sc = sf.make_scenario("s", [task_local_ok(), task_local_ok()],
                          [server_default(), server_default()], full_links(2, 2))
    from cars.exact_oracle.model import OracleModel
    model = OracleModel(sc)
    assert discrete_enumerator.theoretical_state_bound(model) == 9  # 3^2


def test_t9_naive_no_missing_states():
    sc = sf.make_scenario("s", [task_local_ok(), task_local_ok()],
                          [server_default(), server_default()], full_links(2, 2))
    from cars.exact_oracle.model import OracleModel
    model = OracleModel(sc)
    states = list(discrete_enumerator.enumerate_xa(model, mode="NAIVE_EXHAUSTIVE"))
    assert len(states) == 9
    assert len(set((json.dumps(x), json.dumps(a)) for x, a in states)) == 9


def test_t10_deterministic_order():
    sc = sf.make_scenario("s", [task_local_ok(), task_local_ok()],
                          [server_default(), server_default()], full_links(2, 2))
    from cars.exact_oracle.model import OracleModel
    model = OracleModel(sc)
    s1 = [(json.dumps(x), json.dumps(a)) for x, a in
          discrete_enumerator.enumerate_xa(model, mode="NAIVE_EXHAUSTIVE")]
    s2 = [(json.dumps(x), json.dumps(a)) for x, a in
          discrete_enumerator.enumerate_xa(model, mode="NAIVE_EXHAUSTIVE")]
    assert s1 == s2


def test_t11_no_duplicate_xa():
    sc = sf.make_scenario("s", [task_local_ok(), task_local_ok()],
                          [server_default(), server_default()], full_links(2, 2))
    from cars.exact_oracle.model import OracleModel
    model = OracleModel(sc)
    seen = set()
    for x, a in discrete_enumerator.enumerate_xa(model, mode="EXACT_PRUNED"):
        key = (tuple(x), tuple(tuple(r) for r in a))
        assert key not in seen
        seen.add(key)
    assert len(seen) == 9


def test_t12_local_path_included():
    sc = sf.make_scenario("s", [task_local_ok()], [server_default()], full_links(1, 1))
    from cars.exact_oracle.model import OracleModel
    model = OracleModel(sc)
    found_local = False
    for x, a in discrete_enumerator.enumerate_xa(model, mode="EXACT_PRUNED"):
        if x == [0] and a == [[0]]:
            found_local = True
    assert found_local


# ===========================================================================
# C. Safe pruning（T13-T16）
# ===========================================================================
def test_t13_pruning_rules_have_proof():
    rules = feasibility.safe_pruning_rules()
    assert set(rules) >= {"PRUNE-A", "PRUNE-B"}
    for rid in rules:
        r = feasibility.pruning_rule(rid)
        assert r["mathematical_condition"]
        assert r["source"]
        assert r["proof_of_safety"]
        assert r["implementation"]


def test_t14_pruning_on_off_same_optimum():
    # N=2/M=1 超小实例：NAIVE 与 EXACT_PRUNED objective 一致
    sc = sf.make_scenario(
        "t14", [task_local_fail(), task_local_ok()], [server_default()],
        {(0, 0): sf.default_link_spec(), (1, 0): sf.default_link_spec()},
    )
    r_naive = run_prod(sc, mode="NAIVE_EXHAUSTIVE")
    r_pruned = run_prod(sc, mode="EXACT_PRUNED")
    assert r_naive["oracle_status"] in (EXACT_OPTIMAL, CERTIFIED_NUMERICAL_EXACT)
    assert r_pruned["objective_tuple"] is not None
    for k in range(3):
        assert abs(r_naive["objective_tuple"][k] - r_pruned["objective_tuple"][k]) <= 1e-9


def test_t15_unsafe_pruning_rejected():
    from cars.exact_oracle.oracle import solve_exact
    sc = sf.make_scenario("s", [task_local_ok()], [server_default()], full_links(1, 1))
    with pytest.raises(ValueError):
        solve_exact(sc, solver_cfg={"safe_pruning_rules": ["UNSAFE_X"]})


def test_t16_pruning_only_reduces_states():
    sc = sf.make_scenario(
        "t16", [task_local_fail(), task_local_ok()], [server_default()],
        {(0, 0): sf.default_link_spec(), (1, 0): sf.default_link_spec()},
    )
    r_naive = run_prod(sc, mode="NAIVE_EXHAUSTIVE")
    r_pruned = run_prod(sc, mode="EXACT_PRUNED")
    # PRUNE-B 减少成功集枚举（不减少离散 X/A 层），或持平
    assert r_pruned["certificate"]["visited_states"] <= r_naive["certificate"]["visited_states"]
    for k in range(3):
        assert abs(r_pruned["objective_tuple"][k] - r_naive["objective_tuple"][k]) <= 1e-9


# ===========================================================================
# D. Continuous solver（T17-T24）
# ===========================================================================
def _task_attr(index, ell_R, R_tx, a, A_u=1.0, K_u=0.0):
    return {"index": index, "ell_R": ell_R, "R_tx": R_tx, "a": a, "A_u": A_u, "K_u": K_u}


def test_t17_single_task_closed_form():
    # 单任务 free：f -> F_j（R 增）；R(f) 接近 R_tx
    sol = continuous_solver.solve_server([_task_attr(0, 2.1, 0.99, 0.2)], 1.0e10)
    assert sol is not None
    assert sol["f"][0] <= 1.0e10 + 1e-6
    assert abs(sol["capacity_residual"]) <= 1e-6


def test_t18_multi_task_one_server():
    # 两任务同服务器：KKT 分配，均 >= floor
    sol = continuous_solver.solve_server(
        [_task_attr(0, 2.1, 0.99, 0.2), _task_attr(1, 1.0, 0.99, 0.1)], 1.0e4
    )
    assert sol is not None
    assert sol["f"][0] >= 2.1 - 1e-6
    assert sol["f"][1] >= 1.0 - 1e-6
    assert sum(sol["f"].values()) <= 1.0e4 + 1e-3


def test_t19_capacity_boundary():
    # 容量恰好 = floor 之和 -> 全 active
    sol = continuous_solver.solve_server([_task_attr(0, 3.0, 0.99, 0.3), _task_attr(1, 5.0, 0.99, 0.5)], 8.0)
    assert sol is not None
    assert abs(sol["f"][0] - 3.0) <= 1e-3
    assert abs(sol["f"][1] - 5.0) <= 1e-3


def test_t20_floor_equality_boundary():
    # 全 active 且容量用满：KKT 有效
    sol = continuous_solver.solve_server([_task_attr(0, 8.0, 0.99, 0.4)], 8.0)
    assert sol is not None
    assert abs(sol["f"][0] - 8.0) <= 1e-3
    assert sol["capacity_residual"] <= 1e-6


def test_t21_zero_floor_boundary():
    # a=0 任务（R 常数）：每任务至少 f_min^exec=1.0（最小可调度速率，
    # MATH-FMIN-CR-R2）；A_u>0 时剩余按效用凹结构分配。
    sol = continuous_solver.solve_server([_task_attr(0, 0.0, 0.99, 0.0)], 1.0e4)
    assert sol is not None
    assert sol["f"][0] == pytest.approx(1.0e4)   # base 1.0 + 剩余 9999（A_u=1.0）
    assert sol["R2"] == pytest.approx(0.99)
    assert sol["zero_alloc_mode"] == "WATERFILL"
    # A_u=0（无效用方向）：仅保底 f_min^exec=1.0
    sol2 = continuous_solver.solve_server([_task_attr(0, 0.0, 0.99, 0.0, A_u=0.0)], 1.0e4)
    assert sol2 is not None
    assert sol2["f"][0] == pytest.approx(1.0)
    assert sol2["zero_alloc_mode"] == "EPSILON"


def test_t22_infeasible_allocation():
    # floor 总和超容量 -> None
    sol = continuous_solver.solve_server([_task_attr(0, 6.0, 0.99, 0.4), _task_attr(1, 6.0, 0.99, 0.4)], 8.0)
    assert sol is None


def test_t23_kkt_residual_certificate():
    sol = continuous_solver.solve_server(
        [_task_attr(0, 2.1, 0.99, 0.2), _task_attr(1, 1.0, 0.99, 0.1)], 1.0e4
    )
    assert sol is not None
    assert sol["kkt_residual"] <= 1e-6
    assert sol["mode"] == "CERTIFIED_NUMERICAL_EXACT"


def test_t24_deterministic_repeated_solve():
    tasks = [_task_attr(0, 2.1, 0.99, 0.2), _task_attr(1, 1.0, 0.99, 0.1)]
    s1 = continuous_solver.solve_server([dict(t) for t in tasks], 1.0e4)
    s2 = continuous_solver.solve_server([dict(t) for t in tasks], 1.0e4)
    assert s1["f"] == s2["f"]
    assert s1["R2"] == s2["R2"]


# ===========================================================================
# E. End-to-end Exact Oracle（T25-T34）
# ===========================================================================
def test_t25_tiny_feasible_instance():
    sc = sf.make_scenario("t25", [task_local_ok()], [server_default()], full_links(1, 1))
    r = run_prod(sc)
    assert r["oracle_status"] == CERTIFIED_NUMERICAL_EXACT
    assert r["objective_tuple"][0] == pytest.approx(1.0)
    assert r["decision"]["offloading_decision"] == [0]  # 本地已成功，不卸载


def test_t26_all_local_optimal():
    sc = sf.make_scenario("t26", [task_local_ok(), task_local_ok()],
                          [server_default()], full_links(2, 1))
    r = run_prod(sc)
    assert r["objective_tuple"][0] == pytest.approx(1.0)
    assert r["decision"]["offloading_decision"] == [0, 0]


def test_t27_edge_optimal():
    sc = sf.make_scenario("t27", [task_local_fail()], [server_default()], full_links(1, 1))
    r = run_prod(sc)
    assert r["objective_tuple"][0] == pytest.approx(1.0)
    assert r["decision"]["offloading_decision"] == [1]


def test_t28_mixed_local_edge():
    sc = sf.make_scenario(
        "t28", [task_local_ok(), task_local_fail()], [server_default()],
        {(0, 0): sf.default_link_spec(), (1, 0): sf.default_link_spec()},
    )
    r = run_prod(sc)
    assert r["objective_tuple"][0] == pytest.approx(1.0)
    assert r["decision"]["offloading_decision"] == [0, 1]


def test_t29_lex_equivalent_optimum():
    # 两任务本地均成功且卸载不提升任何层：本地全保留（等价最优之一），Oracle 确定性返回
    sc = sf.make_scenario(
        "t29", [task_local_ok(), task_local_ok()], [server_default()],
        {(0, 0): sf.default_link_spec(), (1, 0): sf.default_link_spec()},
    )
    r = run_prod(sc)
    assert r["oracle_status"] == CERTIFIED_NUMERICAL_EXACT
    assert r["objective_tuple"][0] == pytest.approx(1.0)
    # 与 naive 一致（独立验证）
    rn = naive_exhaustive(sc)
    assert rn["found"]
    for k in range(3):
        assert abs(r["objective_tuple"][k] - rn["objective_tuple"][k]) <= 1e-9


def test_t30_infeasible_edge_configuration():
    # 服务器容量不足（floor 超容量）：任务只能本地失败 -> TSSR=0（合法）
    sc = sf.make_scenario(
        "t30", [task_local_fail()],
        [{"capacity_cycles_per_sec": 1.0, "nominal_failure_rate": 1.0e-9}],
        full_links(1, 1),
    )
    r = run_prod(sc)
    assert r["oracle_status"] == CERTIFIED_NUMERICAL_EXACT
    assert r["objective_tuple"][0] == pytest.approx(0.0)


def test_t31_all_schedule_infeasible():
    # 本地失败且无任何物理边：任务在任何决策下失败 -> TSSR=0（合法方案）
    sc = sf.make_scenario("t31", [task_local_fail()], [server_default()], {})
    r = run_prod(sc)
    assert r["objective_tuple"][0] == pytest.approx(0.0)
    assert r["decision"]["offloading_decision"] == [0]


def test_t32_certificate_completeness():
    sc = sf.make_scenario("t32", [task_local_fail()], [server_default()], full_links(1, 1))
    r = run_prod(sc)
    c = r["certificate"]
    for k in (
        "oracle_status", "total_discrete_states", "visited_states",
        "safely_pruned_states", "infeasible_states", "feasible_states",
        "best_objective_tuple", "canonical_solution_hash", "exactness_mode",
        "primal_residual", "capacity_residual", "reliability_residual",
        "kkt_residual", "unsafe_pruning_used", "evaluator_id", "evaluator_version",
    ):
        assert k in c, "certificate 缺字段 %s" % k
    assert c["unsafe_pruning_used"] is False
    assert c["oracle_status"] in (EXACT_OPTIMAL, CERTIFIED_NUMERICAL_EXACT)


def test_t33_common_evaluator_used():
    sc = sf.make_scenario("t33", [task_local_fail()], [server_default()], full_links(1, 1))
    r = run_prod(sc)
    assert r["certificate"]["evaluator_id"] == "cars.evaluator"
    # Oracle 内部使用的就是公共 Evaluator：手动评价其 decision 应与 certificate 目标一致
    ev = evaluator_evaluate(sc, r["decision"], DerivedState(sc))
    assert ev["evaluator_status"].value == "VALID"
    tup = objective_tuple(ev["evaluator_output"])
    for k in range(3):
        assert abs(tup[k] - r["objective_tuple"][k]) <= 1e-9


def test_t34_no_cars_decision_imported():
    # Oracle 模块不得 import cars.methods（不读取 CARS 决策逻辑）
    import cars.exact_oracle.oracle as _oracle_mod
    src = open(os.path.join(ROOT, "src", "cars", "exact_oracle", "oracle.py"), encoding="utf-8").read()
    assert "cars.methods" not in src
    assert "from cars.methods" not in src


# ===========================================================================
# F. Independence cross-check（production == naive；10-20 个 tiny cases）
# ===========================================================================
def _cross_cases():
    cases = []
    # N=1, M=1
    cases.append(sf.make_scenario("x1", [task_local_ok()], [server_default()], full_links(1, 1)))
    cases.append(sf.make_scenario("x2", [task_local_fail()], [server_default()], full_links(1, 1)))
    # N=2, M=1
    cases.append(sf.make_scenario(
        "x3", [task_local_ok(), task_local_ok()], [server_default()],
        {(0, 0): sf.default_link_spec(), (1, 0): sf.default_link_spec()}))
    cases.append(sf.make_scenario(
        "x4", [task_local_fail(), task_local_fail()], [server_default()],
        {(0, 0): sf.default_link_spec(), (1, 0): sf.default_link_spec()}))
    cases.append(sf.make_scenario(
        "x5", [task_local_ok(), task_local_fail()], [server_default()],
        {(0, 0): sf.default_link_spec(), (1, 0): sf.default_link_spec()}))
    # N=2, M=2（全连接，容量不同）
    cases.append(sf.make_scenario(
        "x6", [task_local_fail(), task_local_ok()],
        [server_default(), server_default(1.0e9)], full_links(2, 2)))
    cases.append(sf.make_scenario(
        "x7", [task_local_fail(), task_local_fail()],
        [server_default(), server_default(5.0e3)], full_links(2, 2)))
    # N=3, M=1
    cases.append(sf.make_scenario(
        "x8", [task_local_ok(), task_local_ok(), task_local_fail()], [server_default()],
        {(0, 0): sf.default_link_spec(), (1, 0): sf.default_link_spec(), (2, 0): sf.default_link_spec()}))
    cases.append(sf.make_scenario(
        "x9", [task_local_fail(), task_local_fail(), task_local_fail()], [server_default()],
        {(0, 0): sf.default_link_spec(), (1, 0): sf.default_link_spec(), (2, 0): sf.default_link_spec()}))
    # N=3, M=2（容量竞争）
    cases.append(sf.make_scenario(
        "x10", [task_local_ok(), task_local_fail(), task_local_fail()],
        [server_default(8.0e3), server_default(8.0e3)], full_links(3, 2)))
    cases.append(sf.make_scenario(
        "x11", [task_local_fail(), task_local_fail(), task_local_fail()],
        [server_default(4.0e3), server_default(4.0e3)], full_links(3, 2)))
    cases.append(sf.make_scenario(
        "x12", [task_local_ok(), task_local_ok(), task_local_ok()],
        [server_default(), server_default(1.0e9)], full_links(3, 2)))
    # 部分链路缺失（非全连接）
    cases.append(sf.make_scenario(
        "x13", [task_local_fail(), task_local_ok()], [server_default()],
        {(0, 0): sf.default_link_spec()}))
    return cases


@pytest.mark.parametrize("case_idx", list(range(len(_cross_cases()))))
def test_crosscheck_production_equals_naive(case_idx):
    sc = _cross_cases()[case_idx]
    rp = run_prod(sc, mode=discrete_enumerator.EXACT_PRUNED)
    rn = naive_exhaustive(sc)
    assert rn["found"], "case %s naive 未找到解" % sc["scenario_id"]
    assert rp["oracle_status"] in (EXACT_OPTIMAL, CERTIFIED_NUMERICAL_EXACT)
    for k in range(3):
        assert abs(rp["objective_tuple"][k] - rn["objective_tuple"][k]) <= 1e-9, (
            "case %s tier %d mismatch: prod=%s naive=%s"
            % (sc["scenario_id"], k, rp["objective_tuple"], rn["objective_tuple"])
        )


# ===========================================================================
# G. Contract / integrity（T35-T44）
# ===========================================================================
def _load_yaml(p):
    import yaml
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_t35_formal_seeds_not_accessed():
    proto = _load_yaml(os.path.join(ROOT, "configs", "e4_exact", "e4_exact_protocol.yaml"))
    assert proto["seed_isolation_policy"]["formal_seeds_accessed"] is False


def test_t36_pilot_not_executed():
    proto = _load_yaml(os.path.join(ROOT, "configs", "e4_exact", "e4_exact_protocol.yaml"))
    assert proto["seed_isolation_policy"]["pilot_executed"] is False
    assert proto["seed_isolation_policy"]["formal_executed"] is False


def test_t37_cars_methods_unchanged():
    assert _dir_sha256(os.path.join(ROOT, "src", "cars", "methods")) == PRESTATE["src/cars/methods_dir"]


def test_t38_evaluator_unchanged():
    assert _dir_sha256(os.path.join(ROOT, "src", "cars", "evaluator")) == PRESTATE["src/cars/evaluator_dir"]


def test_t39_contract_v4_unchanged():
    assert _file_sha16(os.path.join(ROOT, "reports", "contracts",
                                    "CARS_EXECUTABLE_THEORY_CONTRACT_V4.md")) == PRESTATE[
        "reports/contracts/CARS_EXECUTABLE_THEORY_CONTRACT_V4.md"
    ]


def test_t40_schema_v4_unchanged():
    assert _dir_sha256(os.path.join(ROOT, "schemas", "CARS_ACTIVE_SCHEMA_V4")) == PRESTATE[
        "schemas/CARS_ACTIVE_SCHEMA_V4_dir"
    ]


def test_t41_no_write_to_iii_vii_by_oracle_code():
    """E4-EXACT-1 代码不得写 III_VII.md（语义检查）。

    NOTE(2026-08-09)：experiment_docs/III_VII.md 在 E4-EXACT-1 阶段内被外部修改
    （用户/编辑器，mtime 22:00 起，hash 6248e905 -> 490b4ca5 -> ...，非 E4-EXACT-1
    引入；E4-EXACT-1 无任何写 experiment_docs 的代码）。因此本测试不做固定 hash
    断言，改为验证 E4-EXACT-1 自身无对 III_VII/experiment_docs 的写入调用。
    """
    import glob as _glob
    import re as _re
    # E4-EXACT-1 专属代码（E4-EXACT-2 新增的只读完整性脚本不属于本检查范围；
    # 其 open("experiment_docs/III_VII.md") 为只读 hash 校验，非写入正文）
    src_files = (
        _glob.glob(os.path.join(ROOT, "src", "cars", "exact_oracle", "*.py"))
        + [os.path.join(ROOT, "scripts", "reproduce", "e4_exact",
                        "run_e4_exact_1_validation.py")]
    )
    for f in src_files:
        t = open(f, encoding="utf-8").read()
        for m in _re.finditer(r"open\s*\(", t):
            seg = t[m.start():m.start() + 300]
            if "experiment_docs" in seg or "III_VII" in seg:
                pytest.fail("%s 存在对 experiment_docs/III_VII 的 open() 调用（E4-EXACT-1 禁止写正文）" % f)


def test_t42_e4_v2_assets_unchanged():
    assert _dir_sha256(os.path.join(ROOT, "configs", "e4_v2")) == PRESTATE["configs/e4_v2_dir"]


def test_t43_data_unchanged():
    dc, ds = 0, 0
    for _dp, _dn, fn in os.walk(os.path.join(ROOT, "data")):
        for f in fn:
            dc += 1
            ds += os.path.getsize(os.path.join(_dp, f))
    assert dc == PRESTATE["data_files"]
    assert ds == PRESTATE["data_bytes"]


def test_t44_same_scenario_reproducibility():
    sc = sf.make_scenario("t44", [task_local_fail(), task_local_ok()],
                          [server_default()],
                          {(0, 0): sf.default_link_spec(), (1, 0): sf.default_link_spec()})
    r1 = run_prod(sc)
    r2 = run_prod(sc)
    assert r1["certificate"]["canonical_solution_hash"] == r2["certificate"]["canonical_solution_hash"]
    assert r1["objective_tuple"] == r2["objective_tuple"]
