# -*- coding: utf-8 -*-
"""E0-V2-2 Formal 数据完整性测试（AC-1..AC-6；E0-V2-2 合同）。

覆盖：
- AC-1：formal_raw.jsonl 560 行；TIMEOUT/METHOD_ERROR 如实计数；
- AC-2：paired 共享——同 (seed,N) 内 scenario_hash16 唯一一致；
- AC-3：pilot seeds 201-205 未进入正式统计；
- AC-4：核心指标与机制指标记录完整；
- AC-6：formal_seed_used=True、pilot_seed_used=False、diagnostic_control 标记正确。
"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT = os.path.dirname(os.path.dirname(_HERE))

RAW_PATH = os.path.join(_PROJECT, "results", "e0_v2", "e0_v2_2_formal", "formal_raw.jsonl")
SUMMARY_PATH = os.path.join(_PROJECT, "results", "e0_v2", "e0_v2_2_formal", "formal_summary.json")

FORMAL_GRID = [20, 50, 80, 110, 140, 170, 200]
FORMAL_SEEDS = list(range(601, 621))
PILOT_SEEDS = [201, 202, 203, 204, 205]
MAIN_METHODS = ["reliability_only", "bpso_rata_la", "cars_aada_rcla_candidate"]
DIAGNOSTIC = ["local_only"]


def _load_records():
    assert os.path.exists(RAW_PATH), "formal_raw.jsonl 缺失：先运行 run_e0_v2_2_formal.py"
    return [json.loads(l) for l in open(RAW_PATH, encoding="utf-8") if l.strip()]


@pytest.fixture(scope="module")
def records():
    return _load_records()


def test_total_runs(records):
    """AC-1a：560 行（420 主 + 140 诊断）。"""
    assert len(records) == 560


def test_status_and_timeout(records):
    """AC-1b：TIMEOUT/METHOD_ERROR 如实计数（本环境预期 0，但不隐藏）。"""
    assert sum(1 for r in records if r["timed_out"]) == 0
    assert sum(1 for r in records if r["method_status"] == "METHOD_ERROR") == 0
    statuses = Counter(r["method_status"] for r in records)
    assert all(s in ("SUCCESS", "BUDGET_EXHAUSTED") for s in statuses)


def test_paired_scenario_shared(records):
    """AC-2：同 (seed,N) 全部方法 scenario_hash16 唯一一致。"""
    by_cell = defaultdict(set)
    for r in records:
        by_cell[(r["seed"], r["N"])].add(r["scenario_hash16"])
    assert len(by_cell) == 7 * 20
    for cell, hashes in by_cell.items():
        assert len(hashes) == 1, cell


def test_pilot_seeds_excluded(records):
    """AC-3：pilot seeds 201-205 未进入正式统计。"""
    seeds = {r["seed"] for r in records}
    assert seeds.isdisjoint(PILOT_SEEDS)
    assert seeds == set(FORMAL_SEEDS)


def test_method_grid_coverage(records):
    """AC-4a：主方法 3 × 7 N × 20 seeds = 420；local_only 140。"""
    main = [r for r in records if not r["diagnostic_control"]]
    diag = [r for r in records if r["diagnostic_control"]]
    assert len(main) == 420
    assert len(diag) == 140
    methods = Counter(r["method"] for r in main)
    assert set(methods) == set(MAIN_METHODS)
    assert all(v == 140 for v in methods.values())


def test_metrics_complete(records):
    """AC-4b：核心 4 指标非 None；机制 6 指标结构完整。"""
    core = ["TSSR", "Rbar_eff", "Ubar_eff", "V_R"]
    mech = ["V_F", "median_f_over_ellR", "max_G_over_F", "LI_dem", "edge_ratio"]
    for r in records:
        for c in core:
            assert r[c] is not None, (r["seed"], r["N"], r["method"], c)
        assert r["mechanism"] is not None
        for c in mech:
            assert c in r["mechanism"], (r["seed"], r["N"], r["method"], c)


def test_flags(records):
    """AC-6：formal_seed_used/pilot_seed_used/diagnostic 标记正确。"""
    for r in records:
        assert r["formal_seed_used"] is True
        assert r["pilot_seed_used"] is False
        assert r["diagnostic_control"] == (r["method"] in DIAGNOSTIC)


def test_summary_exists_and_primary(records):
    """AC-5：summary 存在；primary=TSSR；per_cell 覆盖 3 主方法 × 7 N。"""
    assert os.path.exists(SUMMARY_PATH)
    with open(SUMMARY_PATH, "r", encoding="utf-8") as fh:
        summary = json.load(fh)
    assert summary["primary_outcome"] == "TSSR"
    assert summary["n_runs"] == 560
    assert len(summary["per_cell"]) == 3 * 7
    # 每 cell 20 seeds
    ns = Counter(v["n_seeds"] for v in summary["per_cell"].values())
    assert all(n == 20 for n in ns)
    # paired 差异记录完整
    assert len(summary["paired_differences"]) == 7 * 2  # 7 N × (AADA-BPSO, AADA-rel)
