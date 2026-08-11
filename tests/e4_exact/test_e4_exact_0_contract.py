# -*- coding: utf-8 -*-
"""E4-EXACT-0 冻结测试（T1–T25 + 人工 lexicographic 案例）。

只测试 E4-EXACT-0 阶段冻结的合同与协议，不测试尚未实现的 Exact Oracle。
直接依据：
  - E4_EXACT_ORACLE_CONTRACT_V1.md（reports/contracts/）
  - configs/e4_exact/e4_exact_protocol.yaml
  - configs/e4_exact/e4_exact_metric_definitions.yaml
  - configs/e4_exact/e4_exact_pilot_candidate_grid.yaml
  - experiment_docs/III_VII.md（IV 章 P0）
  - CARS_EXECUTABLE_THEORY_CONTRACT_V4.md
  - CARS_ACTIVE_SCHEMA_V4（schedule_decision）
"""

from __future__ import annotations

import hashlib
import json
import os
import re

import pytest

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))          # tests/e4_exact
_TESTS = os.path.dirname(_HERE)                              # tests
ROOT = os.path.dirname(_TESTS)                               # 仓库根

DOCS = os.path.join(ROOT, "experiment_docs")
CONTRACTS = os.path.join(ROOT, "reports", "contracts")
CONFIG_E4X = os.path.join(ROOT, "configs", "e4_exact")
SCHEMAS_V4 = os.path.join(ROOT, "schemas", "CARS_ACTIVE_SCHEMA_V4")
SRC_CARS = os.path.join(ROOT, "src", "cars")
DATA = os.path.join(ROOT, "data")
E4V2 = os.path.join(ROOT, "configs", "e4_v2")

CONTRACT = os.path.join(CONTRACTS, "E4_EXACT_ORACLE_CONTRACT_V1.md")
PROTOCOL = os.path.join(CONFIG_E4X, "e4_exact_protocol.yaml")
METRICS = os.path.join(CONFIG_E4X, "e4_exact_metric_definitions.yaml")
GRID = os.path.join(CONFIG_E4X, "e4_exact_pilot_candidate_grid.yaml")

# Pre-state 保护对象基线（E4-EXACT-0 阶段开始时记录；本阶段要求零修改）
PRESTATE = {
    "experiment_docs/III_VII.md": "6248e905e98bc7e6",
    "reports/contracts/CARS_EXECUTABLE_THEORY_CONTRACT_V4.md": "79227f233c13bf92",
    "reports/contracts/CARS_FORMULA_IMPLEMENTATION_MAP_V4.yaml": "4944aebca71137ee",
    "schemas/CARS_ACTIVE_SCHEMA_V4_dir": (
        "3b2bcc04a1e0e3e7b80f5d4653904a8065cb16cd140558bc45e58924f276def8"
    ),
    "src/cars_dir": (
        "07eee9f6ef982f352d29640503dab632b15925c2973458bd6814f28d564bbdab"
    ),
    "configs/cars_v4/cars_frozen_v4.yaml": "58605c900ea08dff",
    "configs/cars_v4/cars_system_params_v4.yaml": "6808401aa281cb31",
    "configs/e4_v2_dir": (
        "463d984474914b889ccf24d5319cacd8a10975d89f6d91441f9a11e60810bb83"
    ),
    "data_files": 77,
    "data_bytes": 65721295433,
}


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------
def _file_sha16(p: str) -> str:
    return hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]


def _dir_sha256(root: str) -> str:
    """对目录内全部文件做确定性 hash（路径用相对 ROOT，与 Pre-state 基线一致）。"""
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


def _load_yaml(p: str):
    if yaml is None:
        pytest.skip("pyyaml 未安装")
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _text(p: str) -> str:
    return open(p, encoding="utf-8").read()


# ---------------------------------------------------------------------------
# T1-T2：P0 目标层次与共享 Evaluator
# ---------------------------------------------------------------------------
def test_t1_p0_objective_hierarchy_machine_readable():
    proto = _load_yaml(PROTOCOL)
    oh = proto["objective_hierarchy"]
    assert oh["tier_1"] == "TSSR"
    assert oh["tier_2"] == "mean_effective_reliability"
    assert oh["tier_3"] == "mean_effective_utility"
    assert oh["feasible_set"] == "Omega_phy"
    assert oh["not_weighted_sum"] is True
    assert "lexicographic_compare" in oh
    assert set(oh["constraints"]) >= {
        "C1_binary_offloading",
        "C2_binary_assignment",
        "C3_offloading_assignment_consistency",
        "C4_link_admissibility",
        "C5_resource_activation",
        "C6_server_physical_capacity",
    }


def test_t2_oracle_and_cars_share_evaluator():
    proto = _load_yaml(PROTOCOL)
    assert proto["shared_evaluator"] == "src/cars/evaluator"
    assert set(proto["comparison_methods"]) == {"oracle", "cars"}
    assert proto["paired_scenario"] is True
    assert proto["shared_physical_models"] is True
    assert proto["shared_failure_accounting"] is True


# ---------------------------------------------------------------------------
# T3-T4：禁止 deadline 与旧语义（按"键定义"判定，禁止性说明文字不误报）
# ---------------------------------------------------------------------------
_DEADLINE_KEYS = re.compile(
    r"^\s*(deadline_violation_rate|deadline_only_rate|joint_violation_rate|V_D)\s*:",
    re.M,
)
_LEGACY_KEYS = re.compile(
    r"^\s*(ruad_gamma|cala_weights|repair_budget|repair_tolerances|"
    r"kappa_R|kappa_D|lambda_eff)\s*:",
    re.M,
)


def test_t3_no_deadline_fields_in_protocol():
    for p in (PROTOCOL, METRICS, GRID):
        t = _text(p)
        assert not _DEADLINE_KEYS.search(t), f"{p} 含 deadline 字段键定义"


def test_t4_no_legacy_ruad_cala_repair_semantics():
    for p in (PROTOCOL, METRICS, GRID):
        t = _text(p)
        assert not _LEGACY_KEYS.search(t), f"{p} 含旧 RUAD/CALA/Repair 字段键定义"


# ---------------------------------------------------------------------------
# T5：决策变量与 Schema V4 一致
# ---------------------------------------------------------------------------
def test_t5_decision_variables_match_schema_v4():
    proto = _load_yaml(PROTOCOL)
    assert proto["decision_variables"] == ["X", "A", "F"]
    sch = json.load(
        open(os.path.join(SCHEMAS_V4, "schedule_decision.schema.json"), encoding="utf-8")
    )
    req = set(sch["required"])
    assert {"offloading_decision", "assignment_matrix", "resource_allocation"} <= req
    assert sch["version"] == "CARS_ACTIVE_SCHEMA_V4"


# ---------------------------------------------------------------------------
# T6-T8：Exact 资格、安全剪枝、tie-break
# ---------------------------------------------------------------------------
def test_t6_exactness_qualification_complete():
    t = _text(CONTRACT)
    for kw in (
        "A. 完整性",
        "B. 连续子问题精确性",
        "C. 安全剪枝",
        "D. 统一评价",
    ):
        assert kw in t, f"合同缺少 Exact 资格条件 {kw}"


def test_t7_unsafe_pruning_forbidden():
    t = _text(CONTRACT)
    assert "未获证明的剪枝禁止进入 Exact 模式" in t or "无证明剪枝" in t
    assert "禁止" in t and "剪枝" in t


def test_t8_tie_break_not_change_objective():
    t = _text(CONTRACT)
    assert "tie-break" in t.lower()
    assert "不得改变 P0 最优值" in t


# ---------------------------------------------------------------------------
# T9-T11：Oracle gap 指标
# ---------------------------------------------------------------------------
def test_t9_gap_sign_oracle_minus_cars():
    m = _load_yaml(METRICS)
    assert m["delta_definitions"]["sign_convention"] == "Oracle - CARS"
    assert m["delta_definitions"]["delta_tier_1"]["symbol"] == "Delta_TSSR"
    assert m["delta_definitions"]["delta_tier_2"]["symbol"] == "Delta_R"
    assert m["delta_definitions"]["delta_tier_3"]["symbol"] == "Delta_U"


def test_t10_lexicographic_conditional_comparison():
    m = _load_yaml(METRICS)
    li = m["lexicographic_interpretation"]
    assert "Tier-1" in li["level_1"]
    assert "Tier-2" in li["level_2"]
    assert "Tier-3" in li["level_3"]
    assert li["level_2"].startswith("仅当 Tier-1")
    assert li["level_3"].startswith("仅当 Tier-1、Tier-2 都相同")


def test_t11_exact_match_defined():
    m = _load_yaml(METRICS)
    mi = m["match_indicators"]
    for k in (
        "first_tier_match",
        "full_lexicographic_match",
        "exact_match",
        "exact_match_rate",
        "first_tier_match_rate",
    ):
        assert k in mi, f"缺少 match indicator {k}"
    assert mi["exact_match"]["definition"] == "full_lexicographic_match == true"


# ---------------------------------------------------------------------------
# T12：Pilot 候选网格 ≠ Formal 冻结
# ---------------------------------------------------------------------------
def test_t12_grid_is_candidate_only_not_formal():
    g = _load_yaml(GRID)
    assert g["status"] == "CANDIDATE_ONLY"
    assert g["candidate_scale"]["m_candidate"] == 4
    assert g["candidate_scale"]["n_candidate"] == [6, 8, 10, 12]
    assert isinstance(g["formal_not_frozen"], list) and len(g["formal_not_frozen"]) >= 1
    assert g["pressure_regimes"][0]["label"] == "LOW"
    assert g["pressure_regimes"][-1]["label"] == "HIGH"


# ---------------------------------------------------------------------------
# T13：Formal seeds 零访问
# ---------------------------------------------------------------------------
def test_t13_formal_seeds_not_accessed():
    p = _load_yaml(PROTOCOL)
    sip = p["seed_isolation_policy"]
    assert sip["formal_seeds_accessed"] is False
    assert len(sip["formal_seeds_registered"]) == 10
    assert len(sip["pilot_seeds_registered"]) == 5
    # 与历史范围不重叠
    existing = {201, 202, 203, 204, 205, 301, 302, 303, 304, 305,
                401, 402, 403, 404, 405, 406, 407, 408, 409, 410,
                601, 602, 603, 604, 605, 606, 607, 608, 609, 610,
                611, 612, 613, 614, 615, 616, 617, 618, 619, 620,
                1101, 1102, 1103, 1104, 1105, 1106, 1107, 1108, 1109, 1110,
                2101, 2102, 2103, 2104, 2105, 2106, 2107, 2108, 2109, 2110,
                2401, 2402, 2403, 2501, 2502, 2503, 2504, 2505,
                2506, 2507, 2508, 2509, 2510}
    assert existing.isdisjoint(set(sip["formal_seeds_registered"]))
    assert existing.isdisjoint(set(sip["pilot_seeds_registered"]))


# ---------------------------------------------------------------------------
# T14-T19：保护对象零变化（Pre-state 基线）
# ---------------------------------------------------------------------------
def test_t14_e4_v2_assets_unchanged():
    assert _dir_sha256(E4V2) == PRESTATE["configs/e4_v2_dir"]


def test_t15_iii_vii_unchanged():
    assert _file_sha16(os.path.join(DOCS, "III_VII.md")) == PRESTATE[
        "experiment_docs/III_VII.md"
    ]


def test_t16_contract_v4_unchanged():
    assert _file_sha16(
        os.path.join(CONTRACTS, "CARS_EXECUTABLE_THEORY_CONTRACT_V4.md")
    ) == PRESTATE["reports/contracts/CARS_EXECUTABLE_THEORY_CONTRACT_V4.md"]


def test_t17_schema_v4_unchanged():
    assert _dir_sha256(SCHEMAS_V4) == PRESTATE["schemas/CARS_ACTIVE_SCHEMA_V4_dir"]


def test_t18_src_cars_unchanged():
    assert _dir_sha256(SRC_CARS) == PRESTATE["src/cars_dir"]


def test_t19_data_unchanged():
    dc, ds = 0, 0
    for _dp, _dn, fn in os.walk(DATA):
        for f in fn:
            dc += 1
            ds += os.path.getsize(os.path.join(_dp, f))
    assert dc == PRESTATE["data_files"]
    assert ds == PRESTATE["data_bytes"]


# ---------------------------------------------------------------------------
# T20-T22：协议可解析、确定性、状态定义
# ---------------------------------------------------------------------------
def test_t20_protocol_yamls_parse():
    for p in (PROTOCOL, METRICS, GRID):
        assert _load_yaml(p) is not None


def test_t21_deterministic_ordering_reproducible():
    t = _text(CONTRACT)
    assert "tie-break" in t.lower()
    assert "确定性" in t
    p = _text(PROTOCOL)
    assert "确定性" in p or "deterministic" in p.lower()


def test_t22_status_definitions_complete():
    m = _load_yaml(METRICS)
    os_ = m["status_definitions"]["oracle_status"]
    for s in ("SUCCESS", "TIMEOUT", "SOLVER_ERROR", "NOT_EXACT", "INFEASIBLE_INSTANCE"):
        assert s in os_, f"Oracle 状态缺少 {s}"
    cs = m["status_definitions"]["cars_status"]
    for s in ("SUCCESS", "TIMEOUT", "METHOD_ERROR", "BUDGET_EXHAUSTED"):
        assert s in cs, f"CARS 状态缺少 {s}"


# ---------------------------------------------------------------------------
# T23-T25：Oracle/Pilot/Formal 均未实现、未运行
# ---------------------------------------------------------------------------
def test_t23_oracle_not_implemented_not_run():
    p = _load_yaml(PROTOCOL)
    assert p["seed_isolation_policy"]["oracle_implemented"] is False
    for _dp, _dn, fn in os.walk(SRC_CARS):
        for f in fn:
            if f.endswith(".py"):
                assert "oracle" not in f.lower(), f"发现 Oracle 实现文件 {os.path.join(_dp, f)}"


def test_t24_pilot_not_executed():
    p = _load_yaml(PROTOCOL)
    assert p["seed_isolation_policy"]["pilot_executed"] is False


def test_t25_formal_not_executed():
    p = _load_yaml(PROTOCOL)
    assert p["seed_isolation_policy"]["formal_executed"] is False


# ---------------------------------------------------------------------------
# 合同级人工 lexicographic 案例（不实现 solver；验证比较语义）
# ---------------------------------------------------------------------------
def _lex_better(a, b, eps=1e-9):
    """字典序比较：a 是否严格优于 b（先 Tier-1，相等才 Tier-2，再 Tier-3）。"""
    for x, y in zip(a, b):
        if abs(x - y) > eps:
            return x > y
    return False  # 三层全部等价 -> 无严格更优


def test_manual_lexicographic_case_1_tier1_priority():
    # Tier-1 不同时只看 Tier-1：A(TSSR 更高) 优于 C（即使 C 的 Tier-2/Tier-3 更高）
    a = (0.95, 0.80, 0.50)
    c = (0.90, 0.98, 0.95)
    assert _lex_better(a, c)
    assert not _lex_better(c, a)


def test_manual_lexicographic_case_2_tier2_conditional():
    # Tier-1 相同才比较 Tier-2
    a = (0.90, 0.82, 0.40)
    b = (0.90, 0.79, 0.90)  # Tier-3 更高也不能翻盘
    assert _lex_better(a, b)
    assert not _lex_better(b, a)


def test_manual_lexicographic_case_3_tier3_conditional():
    # 前两层相同才比较 Tier-3
    a = (0.90, 0.80, 0.60)
    b = (0.90, 0.80, 0.50)
    assert _lex_better(a, b)
    assert not _lex_better(b, a)


def test_manual_lexicographic_case_4_equivalence_then_tiebreak():
    # 三层完全等价 -> 字典序下无严格更优；由 deterministic tie-break 决定返回哪个
    a = (0.90, 0.80, 0.60)
    b = (0.90, 0.80, 0.60)
    assert not _lex_better(a, b)
    assert not _lex_better(b, a)
    # tie-break 只在目标完全等价后启动：等价时任意确定性规则均可，但不改变最优值
    tie_break = min  # 示例：确定性规则
    chosen = tie_break(a, b)
    assert chosen == a  # 确定性


def test_manual_lexicographic_case_5_delta_sign():
    # Delta 始终按 Oracle - CARS
    oracle = (1.0, 0.982, 0.61)
    cars = (1.0, 0.979, 0.60)
    delta = tuple(o - c for o, c in zip(oracle, cars))
    assert abs(delta[0]) < 1e-9       # Delta_TSSR = 0（Tier-1 相同）
    assert delta[1] > 0               # Delta_R > 0
    assert delta[2] > 0               # Delta_U > 0
    # Tier-1 不同时，字典序判定由 Tier-1 主导（不因 Tier-2/Tier-3 更高而翻盘）
    oracle2 = (1.0, 0.98, 0.60)
    cars2 = (0.90, 0.99, 0.90)
    assert oracle2[0] - cars2[0] > 0
    assert _lex_better(oracle2, cars2)  # Oracle 字典序更优


def test_manual_lexicographic_case_6_not_weighted_sum():
    # 不允许把 weighted sum 当作 P0：构造加权和判定与字典序判定相反的例子
    def wsum(t):
        return 0.4 * t[0] + 0.3 * t[1] + 0.3 * t[2]

    a = (0.90, 0.80, 0.40)
    b = (0.85, 0.85, 0.85)
    assert _lex_better(a, b)          # 字典序：A 优（Tier-1 更高）
    assert wsum(a) < wsum(b)          # 加权和：B 优 -> 二者不一致，证明加权和≠P0
    # 协议明确 not_weighted_sum=true
    proto = _load_yaml(PROTOCOL)
    assert proto["objective_hierarchy"]["not_weighted_sum"] is True
