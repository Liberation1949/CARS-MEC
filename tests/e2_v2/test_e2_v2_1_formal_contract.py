# -*- coding: utf-8 -*-
"""E2-V2-1 Formal 合同冻结测试（E2_V2_FORMAL_PROTOCOL_V1）。

覆盖：
  1. 协议文件结构（N=170/M=8/CV_F grid/seeds/方法/统计/图表合同）；
  2. formal seeds 2101-2110 授权守卫（未授权拒绝；授权后放行）；
  3. 环境生成与冻结协议一致（F_total=101000、CV 精确命中）；
  4. py_compile（runner/aggregate/figure 三脚本）。
不运行任何正式实验（formal seeds 仅测试守卫）。
"""
from __future__ import annotations

import os
import py_compile
import sys

import pytest
import yaml

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPTS_E2 = os.path.join(_PROJECT, "scripts", "experiments", "e2_v2")
if _SCRIPTS_E2 not in sys.path:
    sys.path.insert(0, _SCRIPTS_E2)

from build_e2_v2_environment import build_e2_v2_environment  # noqa: E402

PROTOCOL_PATH = os.path.join(_PROJECT, "configs", "e2_v2", "e2_v2_formal_protocol.yaml")


def _protocol():
    with open(PROTOCOL_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# 1. 协议文件结构
def test_protocol_structure():
    p = _protocol()
    assert p["protocol_id"] == "e2_v2_formal_protocol_v1"
    assert p["schema_version"] == "CARS_ACTIVE_SCHEMA_V4"
    assert p["environment"]["n"] == 170
    assert p["environment"]["m"] == 8
    assert p["environment"]["total_capacity"] == 101000.0
    assert p["environment"]["s_f"] == 1.0
    assert p["cv_f_grid"] == [0.0, 0.3, 0.6, 0.9, 1.2]
    assert p["formal_seeds"] == list(range(2101, 2111))
    assert p["methods"]["main"] == ["cars", "bpso_rata_la", "jtora_adapted",
                                    "nfa_adapted", "reliability_only", "local_only"]
    assert p["methods"]["diagnostic"] == ["foa"]
    assert p["formal_runs"] == 350
    assert p["statistics"]["degradation"]["definition"].startswith(
        "degradation(Y) = (Y(CV_F^high)")
    assert "CARS exhibits lower performance sensitivity" in p["claim_rules"]["best_claim"]
    assert p["stage_boundary"]["this_stage"] == "E2-V2-1 Formal 主实验（350 runs；2 图 1 表；正式报告）"


# 2. formal seeds 授权守卫
def test_formal_seed_guard_without_authorization():
    import run_e2_v2_1_formal as runner_mod
    with pytest.raises(SystemExit):
        runner_mod.guard_authorization(runner_mod.FORMAL_SEEDS, authorize_formal=False)
    # 单个 formal seed 同样拒绝
    with pytest.raises(SystemExit):
        runner_mod.guard_authorization([2101], authorize_formal=False)
    # 授权后放行
    runner_mod.guard_authorization(runner_mod.FORMAL_SEEDS, authorize_formal=True)
    # 非 formal seeds 无需授权
    runner_mod.guard_authorization([1201, 1202], authorize_formal=False)


# 3. 环境生成与冻结协议一致
def test_environment_matches_frozen_protocol():
    p = _protocol()
    for cv in p["cv_f_grid"]:
        md = build_e2_v2_environment(seed=2101, cv_f_target=cv,
                                     n_max=p["environment"]["n"])["metadata"]
        assert abs(md["cv_f_realized"] - cv) <= 1e-4
        assert abs(md["f_total"] - 101000.0) <= 1e-6
    # 同 seed 跨 CV_F 一致性（任务/λ_j）
    a = build_e2_v2_environment(seed=2101, cv_f_target=0.0, n_max=170)["scenario_cfg"]
    b = build_e2_v2_environment(seed=2101, cv_f_target=1.2, n_max=170)["scenario_cfg"]
    assert [t["task_id"] for t in a["tasks"]] == [t["task_id"] for t in b["tasks"]]
    assert [s["nominal_failure_rate"] for s in a["servers"]] == \
        [s["nominal_failure_rate"] for s in b["servers"]]


# 4. py_compile
def test_py_compile():
    for name in ["run_e2_v2_1_formal.py", "aggregate_e2_v2_1_formal.py",
                 "make_e2_v2_figure.py"]:
        py_compile.compile(os.path.join(_SCRIPTS_E2, name), doraise=True)
