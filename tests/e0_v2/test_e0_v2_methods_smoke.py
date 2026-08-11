# -*- coding: utf-8 -*-
"""E0-V2 方法冒烟测试（AC-4/AC-6；E0-V2-0 冻结）。

覆盖：
- AC-4：微型场景上 3 主方法 + local_only 可运行；统一 Evaluator 唯一评价；
  机制指标（V_F/chi/LI_dem/edge_ratio/max G/F）输出合法；
- AC-6：候选配置注入旧语义字段（gamma/V_D/deadline）被拒绝（ValueError）；
- 统一执行边界：baseline 经 MethodRunner（子进程 + 统一 Evaluator + 硬超时）；
  候选直接实例化（与 baseline 同源 Evaluator）。
"""

from __future__ import annotations

import os
import sys

import pytest
import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_TESTS = os.path.dirname(_HERE)
_PROJECT = os.path.dirname(_TESTS)
_E0_DIR = os.path.join(_PROJECT, "scripts", "reproduce", "e0_v2")
for _p in (_TESTS, _E0_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from build_e0_v2_environment import build_e0_v2_environment  # noqa: E402
from cars.runner.runner import MethodRunner  # noqa: E402
from cars.simulator.derived_state import DerivedState  # noqa: E402
from cars.simulator.scenario_materializer import materialize  # noqa: E402

from run_e0_v2_pilot import (  # noqa: E402
    CANDIDATE_CONFIG_PATH,
    METHOD_CONFIG_PATHS,
    METHOD_SEED,
    TIMEOUT,
    compute_e0_mechanism_metrics,
)

N = 4
M = 2
NORMAL_STATUSES = ("SUCCESS", "BUDGET_EXHAUSTED", "NO_IMPROVEMENT")


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    cfg = build_e0_v2_environment(seed=201, n=N, n_max=20)
    scen = materialize(cfg)
    derived = DerivedState(scen)
    scen_path = tmp_path_factory.mktemp("e0v2_smoke") / "scenario.yaml"
    with open(scen_path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg, fh, allow_unicode=True, sort_keys=False)
    return scen, derived, str(scen_path)


def _assert_valid_record(rec):
    assert rec["method_status"] in NORMAL_STATUSES, rec
    assert rec["timed_out"] is False
    assert rec["TSSR"] is not None
    assert rec["Rbar_eff"] is not None
    assert rec["Ubar_eff"] is not None
    assert rec["V_R"] is not None
    assert 0.0 <= rec["TSSR"] <= 1.0
    assert 0.0 <= rec["V_R"] <= 1.0
    mech = rec["mechanism"]
    assert mech is not None
    assert 0.0 <= mech["edge_ratio"] <= 1.0
    assert 0.0 <= mech["V_F"] <= 1.0
    assert 0.0 <= mech["max_G_over_F"] <= 1.0 + 1e-6
    assert mech["LI_dem"] >= 0.0


def test_candidate_aada_rcla_runs(env):
    """AC-4a：候选 AADA-RCLA 在微型场景可运行；Evaluator + 机制指标合法。"""
    from cars.evaluator import evaluator as ev
    from cars.methods.cars.method import CarsMethod
    from cars.methods.protocol import MethodContext

    scen, derived, _ = env
    with open(os.path.join(_PROJECT, CANDIDATE_CONFIG_PATH), "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    m = CarsMethod(cfg)
    ctx = MethodContext(
        scenario=scen, derived=derived, config=cfg, method_seed=METHOD_SEED,
        soft_deadline_seconds=TIMEOUT - 3.0, hard_timeout_seconds=TIMEOUT,
    )
    prop = m.run(ctx)
    assert prop.decision is not None
    assert prop.method_status in NORMAL_STATUSES, prop.method_status
    out = ev.evaluate(scen, prop.decision, derived)
    sm = (out.get("evaluator_output") or {}).get("system_metrics") or {}
    assert sm.get("tssr") is not None
    assert sm.get("reliability_violation_rate") is not None
    mech = compute_e0_mechanism_metrics(scen, derived, prop.decision)
    assert 0.0 <= mech["V_F"] <= 1.0
    assert mech["edge_ratio"] >= 0.0


@pytest.mark.parametrize("method_id", ["reliability_only", "local_only", "bpso_rata_la"])
def test_baseline_runs_via_methodrunner(env, method_id):
    """AC-4b：baseline 经统一 MethodRunner 运行；统一 Evaluator 评价；机制指标合法。"""
    scen, derived, scen_path = env
    runner = MethodRunner()
    with open(os.path.join(_PROJECT, METHOD_CONFIG_PATHS[method_id]), "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    record = runner.run(
        method_id=method_id,
        scenario_cfg_path=scen_path,
        method_config=cfg,
        method_seed=METHOD_SEED,
        hard_timeout_seconds=TIMEOUT,
    )
    assert record["method_status"] in NORMAL_STATUSES, record["method_status"]
    assert record["timed_out"] is False
    sm = (record.get("evaluator_output") or {}).get("system_metrics") or {}
    assert sm.get("tssr") is not None
    assert sm.get("reliability_violation_rate") is not None
    dec = record.get("decision")
    assert dec is not None
    mech = compute_e0_mechanism_metrics(scen, derived, dec)
    assert 0.0 <= mech["V_F"] <= 1.0
    assert mech["edge_ratio"] >= 0.0


@pytest.mark.parametrize("legacy_key,legacy_value", [
    ("gamma", 0.5),
    ("ruad_gamma", 1.0),
    ("V_D", 0.1),
    ("deadline_seconds", 100.0),
    ("Q_j", 1.0),
    ("Z_j", 1.0),
])
def test_legacy_fields_rejected_in_candidate(env, legacy_key, legacy_value):
    """AC-6：候选配置注入旧语义字段 -> 构造时拒绝（ValueError）。"""
    from cars.methods.cars.method import CarsMethod

    with open(os.path.join(_PROJECT, CANDIDATE_CONFIG_PATH), "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    bad = dict(cfg)
    bad[legacy_key] = legacy_value
    with pytest.raises(ValueError):
        CarsMethod(bad)


def test_pilot_runner_smoke_flag(env):
    """AC-4c：run_e0_v2_pilot.py --smoke 可执行（微型网格；工具验证路径）。"""
    import subprocess
    import sys as _sys

    script = os.path.join(_E0_DIR, "run_e0_v2_pilot.py")
    proc = subprocess.run(
        [_sys.executable, script, "--smoke"],
        capture_output=True, text=True, timeout=600,
        cwd=_PROJECT,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    assert "n_runs:" in proc.stdout
