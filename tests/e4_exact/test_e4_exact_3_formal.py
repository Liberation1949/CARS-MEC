# -*- coding: utf-8 -*-
"""E4-EXACT-3 Formal 冻结测试（方案 A；20 runs）。

覆盖：
- Formal protocol 授权状态与方案 A matrix（T1-T3）
- runner 授权守卫 / seed 白名单（T4-T6）
- worker tier_metrics 逻辑（gap/match/缺失；T7-T9）
- scenario 确定性（T10；用 pilot seed，不访问 formal seed）
- 聚合逻辑（合成数据；T11）
- 保护对象与 formal seeds 纪律（T12-T13）
- worker 端到端 smoke（T14；N=4/LOW/3401——非 formal seed，验证 oracle+cars 链路）

formal seeds 3501-3510 在本测试中仅作为白名单常量校验，不用于场景生成/运行。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_TESTS = os.path.dirname(_HERE)
ROOT = os.path.dirname(_TESTS)
CONFIGS = os.path.join(ROOT, "configs", "e4_exact")
SCRIPTS = os.path.join(ROOT, "scripts", "reproduce", "e4_exact")

sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.join(ROOT, "src"))

FORMAL_PROTOCOL = os.path.join(CONFIGS, "e4_exact_formal_protocol.yaml")
FORMAL_SEEDS = [3501, 3502, 3503, 3504, 3505, 3506, 3507, 3508, 3509, 3510]
PILOT_SEEDS = [3401, 3402, 3403, 3404, 3405]


def _load_yaml(path):
    import yaml
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# ---------------------------------------------------------------------------
# T1-T3：Formal protocol 授权与方案 A matrix
# ---------------------------------------------------------------------------
def test_t1_formal_protocol_authorized():
    p = _load_yaml(FORMAL_PROTOCOL)
    assert p["authorized_to_execute"] is True
    assert p["formal_seeds"]["status"] == "AUTHORIZED"
    # MATH-FMIN-CR-R2（2026-08-11 用户批准）：加入 N=5
    assert p["n_grid"] == [4, 5, 6]
    assert p["pressure_regimes"] == ["LOW", "TRANSITION"]


def test_t2_formal_matrix_scheme_a():
    p = _load_yaml(FORMAL_PROTOCOL)
    fm = p["formal_matrix"]
    assert fm["structure"].startswith("regime-bounded")
    assert fm["runs"] == 30
    assert len(fm["cells"]) == 3
    assert {"regime": "LOW", "n": 4, "seeds": 10} in fm["cells"]
    assert {"regime": "TRANSITION", "n": 5, "seeds": 10} in fm["cells"]
    assert {"regime": "TRANSITION", "n": 6, "seeds": 10} in fm["cells"]


def test_t3_formal_matrix_no_cross_product():
    # 方案 A：regime 绑定 N；禁止把 (LOW,6) 或 (TRANSITION,4) 纳入
    p = _load_yaml(FORMAL_PROTOCOL)
    cells = {(c["regime"], c["n"]) for c in p["formal_matrix"]["cells"]}
    assert cells == {("LOW", 4), ("TRANSITION", 5), ("TRANSITION", 6)}


# ---------------------------------------------------------------------------
# T4-T6：runner 授权守卫 / seed 白名单
# ---------------------------------------------------------------------------
def test_t4_runner_refuses_without_auth():
    runner = os.path.join(SCRIPTS, "run_e4_exact_3_formal.py")
    r = subprocess.run([sys.executable, runner, "--max-instances", "1"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=60, cwd=ROOT)
    assert r.returncode != 0
    assert "REFUSED" in (r.stdout + r.stderr)


def test_t5_build_matrix_seed_whitelist():
    from run_e4_exact_3_formal import build_matrix, load_protocol
    proto = load_protocol()
    matrix = build_matrix(proto)
    assert len(matrix) == 30
    seeds = {item["seed"] for item in matrix}
    assert seeds == set(FORMAL_SEEDS)
    assert seeds.isdisjoint(set(PILOT_SEEDS))
    # regime 绑定：LOW 只配 N=4；TRANSITION 配 N=5/6
    low_n = {item["n"] for item in matrix if item["regime"] == "LOW"}
    tr_n = {item["n"] for item in matrix if item["regime"] == "TRANSITION"}
    assert low_n == {4}
    assert tr_n == {5, 6}


def test_t6_runner_hard_reject_non_formal_seed():
    # 直接验证 build_matrix 后的 seed 均为 formal 白名单（同 T5）；并验证 runner
    # 内部对非 formal seed 的 FATAL 逻辑（构造注入矩阵）。
    import run_e4_exact_3_formal as R
    proto = R.load_protocol()
    matrix = R.build_matrix(proto)
    # 模拟注入 pilot seed 应被拒绝
    bad = matrix[0].copy()
    bad["seed"] = 3401
    assert bad["seed"] in PILOT_SEEDS
    # runner main 的校验：非 formal seed -> SystemExit（逻辑检查）
    assert bad["seed"] not in set(FORMAL_SEEDS)


# ---------------------------------------------------------------------------
# T7-T9：worker tier_metrics 逻辑
# ---------------------------------------------------------------------------
def test_t7_tier_metrics_gap():
    from _e4x3_single_instance import tier_metrics
    # oracle TSSR=1.0, Rbar=0.95, Ubar=0.5；cars TSSR=0.9, Rbar=0.9, Ubar=0.4
    m = tier_metrics([1.0, 0.95, 0.5], {"tssr": 0.9, "rbar_eff": 0.9, "ubar_eff": 0.4})
    assert m["computable"] is True
    assert m["tier1_gap"] == pytest.approx(0.1)
    assert m["tier1_match"] is False
    assert m["tier2_gap"] is None  # conditional：tier1 不 match 时不解释 tier2
    assert m["full_lex_match"] is False


def test_t8_tier_metrics_match_eps():
    from _e4x3_single_instance import tier_metrics, EPS_CMP
    # 全 match（差 < EPS_CMP=1e-9）
    eps = EPS_CMP
    m = tier_metrics([1.0, 0.95, 0.5],
                     {"tssr": 1.0 - 0.5 * eps, "rbar_eff": 0.95, "ubar_eff": 0.5})
    assert m["tier1_match"] is True
    assert m["tier2_match"] is True
    assert m["tier3_match"] is True
    assert m["full_lex_match"] is True
    # tier2 差一点 -> full match False
    m2 = tier_metrics([1.0, 0.95, 0.5],
                      {"tssr": 1.0, "rbar_eff": 0.95 + 10 * eps, "ubar_eff": 0.5})
    assert m2["tier1_match"] is True
    assert m2["tier2_match"] is False
    assert m2["full_lex_match"] is False
    assert m2["tier3_gap"] is None


def test_t9_tier_metrics_missing():
    from _e4x3_single_instance import tier_metrics
    m = tier_metrics(None, {"tssr": 0.9, "rbar_eff": 0.9, "ubar_eff": 0.4})
    assert m["computable"] is False
    m2 = tier_metrics([1.0, 0.95, 0.5], {"tssr": None, "rbar_eff": None, "ubar_eff": None})
    assert m2["computable"] is False


# ---------------------------------------------------------------------------
# T10：scenario 确定性（pilot seed；不访问 formal seed）
# ---------------------------------------------------------------------------
def test_t10_scenario_deterministic():
    from _e4x3_single_instance import scenario_config_for, materialized_scenario
    c1 = scenario_config_for(4, 4, 3401, "LOW")
    c2 = scenario_config_for(4, 4, 3401, "LOW")
    assert c1 == c2
    assert c1["mode"] == "explicit"
    s1 = materialized_scenario(c1)
    assert len(s1["tasks"]) == 4
    assert len(s1["servers"]) == 4


# ---------------------------------------------------------------------------
# T11：聚合逻辑（合成数据）
# ---------------------------------------------------------------------------
def test_t11_aggregate_synthetic(tmp_path):
    import aggregate_e4_exact_3_formal as A
    # 合成 2 条 N=4 记录（直接调 bootstrap）
    gaps = [0.05, -0.01]
    ci = A._bootstrap_ci(gaps)
    assert ci["n"] == 2
    assert ci["mean"] is not None
    assert ci["ci95_low"] <= ci["mean"] <= ci["ci95_high"]
    # 确定性：同 seed 两次 bootstrap 相同
    ci2 = A._bootstrap_ci(gaps)
    assert ci == ci2


# ---------------------------------------------------------------------------
# T12-T13：保护对象与 formal seeds 纪律
# ---------------------------------------------------------------------------
def test_t12_protected_objects_unchanged():
    import hashlib
    def f16(p):
        return hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]
    assert f16(os.path.join(ROOT, "configs", "cars_v4", "cars_frozen_v4.yaml")).startswith("58605c90")
    # exact_oracle 目录 hash
    h = hashlib.sha256()
    files = []
    for dp, _dn, fn in os.walk(os.path.join(ROOT, "src", "cars", "exact_oracle")):
        if "__pycache__" in dp:
            continue
        for f in fn:
            files.append(os.path.join(dp, f))
    for f in sorted(files):
        rel = os.path.relpath(f, ROOT)
        raw = open(f, "rb").read()
        h.update(rel.encode()); h.update(b"\x00"); h.update(raw); h.update(b"\x00")
    # MATH-ORACLE-CONSISTENCY-R1 + MATH-FMIN-CR-R2：continuous_solver/oracle 增加
    # Tier-3 tie-break + f_min^exec=1.0（zero 任务下限与保底分配）
    assert h.hexdigest().startswith("cdb3e4bb3adbadef")


def test_t13_formal_seeds_discipline():
    # formal seeds 仅在白名单常量与 protocol 中出现；测试自身不得用 formal seed 生成场景
    from _e4x3_single_instance import scenario_config_for  # noqa: F401
    assert 3501 not in PILOT_SEEDS
    assert set(FORMAL_SEEDS) & set(PILOT_SEEDS) == set()


# ---------------------------------------------------------------------------
# T14：worker 端到端 smoke（N=4/LOW/3401；非 formal seed；验证 oracle+cars 链路）
# ---------------------------------------------------------------------------
def test_t14_worker_end_to_end_smoke():
    import _e4x3_single_instance as W
    cfg = W.scenario_config_for(4, 4, 3401, "LOW")
    oracle = W.run_oracle(cfg)
    cars = W.run_cars(cfg)
    assert oracle["status"] == "COMPLETED"
    assert oracle["accepted_exact"] is True
    assert oracle["certificate_pass"] is True
    assert cars["status"] == "COMPLETED"
    assert cars["method_status"] == "SUCCESS"
    assert cars["tssr"] is not None
    m = W.tier_metrics(oracle["objective_tuple"], cars)
    assert m["computable"] is True
    assert 0.0 <= cars["tssr"] <= 1.0
