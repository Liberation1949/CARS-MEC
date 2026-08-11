# -*- coding: utf-8 -*-
"""E0-V2-0 协议与字段定义测试（configs/e0_v2/*；E0-V2-0 冻结）。

覆盖：
- AC-1：e0_v2_protocol.yaml 覆盖环境/Pilot/Formal/方法/指标/坍缩判断/图表/禁止项；
- AC-2：e0_v2_field_definitions.yaml 定义全部主指标与机制指标（V_F/chi/max G/F 口径）；
- AC-6：旧语义字段（V_D/deadline/gamma/Q/Z/lambda_eff）在协议禁止列表与字段定义禁用表中；
- D2：formal seeds 601-620 与 E3-V2 401-410、旧 E3 301-305 全互斥；
- 用户设计：Pilot N 网格 / 方法白名单 / 指标优先级 / 2 图 1 表。
"""

from __future__ import annotations

import os
import sys

import pytest
import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_TESTS = os.path.dirname(_HERE)
_PROJECT = os.path.dirname(_TESTS)

CFG_DIR = os.path.join(_PROJECT, "configs", "e0_v2")
PROTOCOL_PATH = os.path.join(CFG_DIR, "e0_v2_protocol.yaml")
FIELD_PATH = os.path.join(CFG_DIR, "e0_v2_field_definitions.yaml")


@pytest.fixture(scope="module")
def protocol():
    with open(PROTOCOL_PATH, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@pytest.fixture(scope="module")
def fields():
    with open(FIELD_PATH, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# ---------------------------------------------------------------------------
# AC-1：协议覆盖全部冻结项
# ---------------------------------------------------------------------------
def test_protocol_stage_identity(protocol):
    assert protocol["stage_id"] == "E0_V2_0"
    assert protocol["authorized"] is False
    assert protocol["next_stage"] == "E0_V2_1"
    assert protocol["e0_positioning"]["type"] == "phenomenon identification（现象识别实验，不是性能排名实验）"
    assert protocol["e0_positioning"]["not_responsible"]


def test_protocol_environment(protocol):
    env = protocol["environment"]
    assert env["independent_variable"] == "N"
    assert env["servers_m"] == 8
    assert env["topology"] == "fully_connected"
    assert env["n_max"] == 260
    assert env["nested_tasks"]["rule"].startswith("每个 seed 一次生成 N_max")


def test_protocol_pilot_grid(protocol):
    pilot = protocol["pilot"]
    assert pilot["n_grid"] == [20, 40, 60, 80, 100, 120, 150, 180, 220, 260]
    assert pilot["seeds"] == [201, 202, 203, 204, 205]
    assert pilot["seeds_status"] == "NOT_FORMAL"
    assert pilot["keep_at_least"] == [20, 80, 150]
    assert "调算法参数" in pilot["forbidden_adjustment"]
    assert "为制造 collapse 修改任务分布" in pilot["forbidden_adjustment"]


def test_protocol_formal_grid_and_seeds(protocol):
    formal = protocol["formal"]
    assert formal["n_points"] == 7
    assert formal["candidate_grid_a"] == [20, 50, 80, 110, 140, 170, 200]
    assert formal["candidate_grid_b"] == [20, 50, 80, 110, 150, 200, 250]
    assert formal["seeds"] == list(range(601, 621))
    assert formal["seeds_status"] == "NEW_PAIRED_UNSEEN"
    assert formal["total_runs"] == 420
    assert formal["status"] == "REGISTERED_ONLY_NOT_EXECUTED"


def test_protocol_methods(protocol):
    methods = protocol["methods"]
    for key in ("cars_aada_rcla_candidate", "bpso_rata_la", "reliability_only", "local_only"):
        assert key in methods
    assert methods["bpso_rata_la"]["role"] == "E0 最重要的强基线"
    assert methods["reliability_only"]["role"] == "机制诊断基线"
    assert methods["local_only"]["role"] == "诊断控制（不入主图；可选附录/表一行）"
    assert protocol["methods"]["excluded_from_e0"] == ["jtora_adapted", "nfa_adapted", "foa"]
    assert protocol["methods"]["fairness"]["timeout_seconds"] == 30.0


def test_protocol_metrics(protocol):
    metrics = protocol["metrics"]
    assert metrics["primary_outcome"] == "TSSR"
    assert metrics["core_metrics"] == ["TSSR", "Rbar_eff", "Ubar_eff", "V_R"]
    assert set(metrics["mechanism_metrics"]) == {
        "V_F", "chi_ij", "median_f_over_ellR", "max_G_over_F", "LI_dem", "edge_ratio",
    }
    assert metrics["metric_priority"] == "TSSR > Rbar_eff > Ubar_eff"


def test_protocol_collapse_judgment(protocol):
    cj = protocol["collapse_judgment"]
    assert "固定 collapse threshold" in cj["forbidden"]
    assert cj["step2_segmented_regression"]
    assert cj["verdict"][0] == "证据不足 -> ordinary degradation"
    assert "accelerated degradation regime" in cj["verdict"][1]


def test_protocol_manuscript_budget(protocol):
    mb = protocol["manuscript_budget"]
    assert mb["figures"] == 2
    assert mb["tables"] == 1
    assert len(mb["fig_e0_1"]["panels"]) == 3
    assert mb["fig_e0_1"]["lines"] == ["reliability_only", "bpso_rata_la", "cars_aada_rcla_candidate"]
    assert len(mb["table_e0_1"]["columns"]) == 9


def test_protocol_forbidden(protocol):
    forbid = protocol["stage_scope"]["forbidden"]
    assert "运行 Pilot / Formal（AUTHORIZED=NO）" in forbid
    assert "引入旧语义指标（V_D/deadline/gamma/Q/Z/lambda_eff）" in forbid
    assert "定义固定 collapse threshold" in forbid
    assert "修改正式 cars / Contract V3 / Schema V3 / III_VI" in forbid


# ---------------------------------------------------------------------------
# AC-2：字段定义完整
# ---------------------------------------------------------------------------
def test_field_core_metrics(fields):
    core = fields["core_metrics"]
    assert set(core.keys()) == {"TSSR", "Rbar_eff", "Ubar_eff", "V_R"}
    for k in core:
        assert core[k]["source"] and core[k]["definition"]


def test_field_mechanism_metrics(fields):
    mech = fields["mechanism_metrics"]
    assert set(mech.keys()) == {
        "V_F", "chi_ij", "median_f_over_ellR", "max_G_over_F", "LI_dem", "edge_ratio",
    }
    # V_F 口径：Gamma_edge = {i : x_i = 1}
    assert "Gamma_edge" in mech["V_F"]["edge_set"]
    assert mech["V_F"]["ellR_source"]
    # max G/F 口径
    assert "ell_R_ij" in mech["max_G_over_F"]["definition"]


def test_field_forbidden(fields):
    forb = fields["forbidden_fields"]
    for name in ["V_D", "deadline_violation_rate", "lambda_eff", "Q_j", "Z_j",
                 "ruad_gamma", "gamma", "collapse_threshold"]:
        assert name in forb, name


# ---------------------------------------------------------------------------
# AC-6：旧语义字段在协议/字段定义中被拒绝（双重）
# ---------------------------------------------------------------------------
def test_legacy_fields_rejected_in_protocol(protocol):
    forbidden_metrics = protocol["methods"]["forbidden_metrics"]
    for name in ["V_D", "deadline_violation_rate", "lambda_eff", "Q_j", "Z_j", "ruad_gamma", "gamma"]:
        assert name in forbidden_metrics, name


# ---------------------------------------------------------------------------
# D2：formal seeds 互斥（与 E3-V2 401-410、旧 E3 301-305 全互斥）
# ---------------------------------------------------------------------------
def test_formal_seeds_disjoint_from_all_history(protocol):
    formal = set(protocol["formal"]["seeds"])
    assert formal == set(range(601, 621))
    assert formal.isdisjoint(set(range(401, 411)))      # E3-V2 formal
    assert formal.isdisjoint(set(range(201, 206)))      # E0/E3-V2 pilot
    assert formal.isdisjoint(set(range(301, 306)))      # 旧 E3 formal（作废）
    assert formal.isdisjoint(set(range(1101, 1111)))    # 旧 E1 formal（作废）


def test_pilot_seeds_not_formal(protocol):
    pilot = set(protocol["pilot"]["seeds"])
    formal = set(protocol["formal"]["seeds"])
    assert pilot.isdisjoint(formal)
