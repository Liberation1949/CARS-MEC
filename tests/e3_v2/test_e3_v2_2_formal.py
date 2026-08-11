# -*- coding: utf-8 -*-
"""E3-V2-2 正式结果完整性测试（Step 8；只读正式产物）。

覆盖（合同 Step 8）：
- AC-F1：raw records = 210；units = 7；pressures = 3；seeds 401-410 各 7 条；
- AC-F2：formal seed 唯一性 + pilot seed 排除（201-203 不得出现）；
- AC-F3：fixed-assignment X/A hash 一致（full/fixed_rcla/fixed_ordinary_la）；
- AC-F4：同 (pressure, seed) 全部 variant 共享同一 scenario hash；
- AC-F5：正确性（max_epsilon_dphi < 1e-12；N_ALLOCATION_INFEASIBLE = 0）；
- AC-F6：Table E3-1 CSV 存在且 8 行（表头 + 7 units）。
"""
from __future__ import annotations

import csv
import json
import os

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT = os.path.dirname(os.path.dirname(_HERE))

RAW = os.path.join(_PROJECT, "results", "e3_v2", "e3_v2_2_formal", "raw_records.jsonl")
SUMMARY = os.path.join(_PROJECT, "results", "e3_v2", "e3_v2_2_formal_summary.json")
CSV_PATH = os.path.join(_PROJECT, "results", "e3_v2", "e3_v2_2_table_e3_1.csv")

UNITS = {"full", "no_rescue", "rescue_only", "no_alloc_aware", "no_utility_gate",
         "fixed_rcla", "fixed_ordinary_la"}
PRESSURES = {"LOW", "TRANSITION", "HIGH"}
FORMAL_SEEDS = set(range(401, 411))
PILOT_SEEDS = {201, 202, 203}


def _load_raw():
    assert os.path.exists(RAW), "E3-V2-2 raw_records.jsonl 缺失——需先运行 run_e3_v2_2_formal.py"
    rows = []
    with open(RAW, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def test_raw_records_completeness():
    """AC-F1：210 = 10 seeds × 3 pressures × 7 units。"""
    rows = _load_raw()
    assert len(rows) == 210
    assert set(r["unit"] for r in rows) == UNITS
    assert set(r["pressure"] for r in rows) == PRESSURES
    for p in PRESSURES:
        for s in range(401, 411):
            assert sum(1 for r in rows if r["pressure"] == p and r["seed"] == s) == 7


def test_seed_uniqueness_and_pilot_exclusion():
    """AC-F2：formal seed 唯一；pilot 201-203 不得进入正式记录。"""
    rows = _load_raw()
    seeds = set(r["seed"] for r in rows)
    assert seeds == FORMAL_SEEDS
    assert not (seeds & PILOT_SEEDS)


def test_fixed_xa_hash_consistent():
    """AC-F3：full/fixed_rcla/fixed_ordinary_la 的 X/A hash 一致（30 cells）。"""
    s = json.load(open(SUMMARY, encoding="utf-8"))
    assert s["correctness"]["fixed_xa_hash_consistent"] is True
    rows = _load_raw()
    for p in PRESSURES:
        for seed in range(401, 411):
            recs = [r for r in rows if r["pressure"] == p and r["seed"] == seed]
            hx = {r["unit"]: r["X_hash16"] for r in recs}
            ha = {r["unit"]: r["A_hash16"] for r in recs}
            assert hx["full"] == hx["fixed_rcla"] == hx["fixed_ordinary_la"]
            assert ha["full"] == ha["fixed_rcla"] == ha["fixed_ordinary_la"]


def test_scenario_shared_per_cell():
    """AC-F4：同 (pressure, seed) 的 7 units 共享同一 scenario hash。"""
    rows = _load_raw()
    for p in PRESSURES:
        for seed in range(401, 411):
            recs = [r for r in rows if r["pressure"] == p and r["seed"] == seed]
            hashes = {r["scenario_hash16"] for r in recs}
            assert len(hashes) == 1, "scenario hash mismatch at %s seed=%d" % (p, seed)


def test_correctness_diagnostics():
    """AC-F5：Lemma 2 精确性 + Admission invariant + 无 ALLOCATION_INFEASIBLE。"""
    s = json.load(open(SUMMARY, encoding="utf-8"))
    c = s["correctness"]
    assert c["max_epsilon_dphi_max"] < 1e-12
    assert c["N_ALLOCATION_INFEASIBLE_total"] == 0
    assert c["formal_seeds_only"] is True
    assert c["paired_scenario_shared"] is True


def test_table_e3_1_csv():
    """AC-F6：Table E3-1 CSV 存在且含表头 + 7 units。"""
    assert os.path.exists(CSV_PATH)
    with open(CSV_PATH, "r", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    assert len(rows) == 8  # header + 7 units
    assert rows[0][0] == "Variant"
    unit_col = [r[0] for r in rows[1:]]
    assert set(unit_col) == UNITS
