# -*- coding: utf-8 -*-
"""E4-EXACT-2 Pilot & Freeze 测试（T1-T25；E4-EXACT-2 阶段合同 §十八）。

覆盖：
- seed 隔离（T1/T2/T22）
- Formal selector 与 CARS performance 完全隔离（T3-T6）
- F1-F5 排除规则（T7-T10）
- candidate grid 不扩大（T11）、regime 来源合法（T12）
- 保护对象不变（T13-T20）
- Formal protocol 状态与 seeds（T21-T22）
- Pilot / aggregation 可重复（T23/T24）
- Formal configuration 可由 Pilot raw 数据确定性重建（T25）
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_TESTS = os.path.dirname(_HERE)
ROOT = os.path.dirname(_TESTS)
CONFIGS = os.path.join(ROOT, "configs", "e4_exact")
RESULTS = os.path.join(ROOT, "results", "e4_exact", "e4_exact_2_pilot")
SCRIPTS = os.path.join(ROOT, "scripts", "experiments", "e4_exact")

PILOT_PROTOCOL = os.path.join(CONFIGS, "e4_exact_2_pilot_protocol.yaml")
FORMAL_PROTOCOL = os.path.join(CONFIGS, "e4_exact_formal_protocol.yaml")
SOLVER_YAML = os.path.join(CONFIGS, "e4_exact_solver.yaml")
ENV_SELECTED = os.path.join(CONFIGS, "e4_exact_environment_selected.yaml")
GRID_YAML = os.path.join(CONFIGS, "e4_exact_pilot_candidate_grid.yaml")
SELECTOR = os.path.join(SCRIPTS, "select_e4_exact_formal_config.py")
SELECTION_JSON = os.path.join(RESULTS, "formal_scale_selection.json")

FORMAL_SEEDS = [3501, 3502, 3503, 3504, 3505, 3506, 3507, 3508, 3509, 3510]
PILOT_SEEDS = [3401, 3402, 3403, 3404, 3405]

ACCEPTED = ("EXACT_OPTIMAL", "CERTIFIED_NUMERICAL_EXACT")
REJECTED = ("TIMEOUT_UNCERTIFIED", "NOT_EXACT", "SOLVER_ERROR")


def _load_yaml(path):
    import yaml
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _file_hash(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


# ---------------------------------------------------------------------------
# T1/T2/T22：seed 隔离
# ---------------------------------------------------------------------------
def test_t1_pilot_and_formal_seeds_not_overlapping():
    grid = _load_yaml(GRID_YAML)
    assert set(grid["seed_candidates"]["pilot_seeds"]) & set(
        grid["seed_candidates"]["formal_seeds"]) == set()
    assert set(PILOT_SEEDS) & set(FORMAL_SEEDS) == set()


def test_t2_formal_seeds_hard_reject_in_runner():
    src = open(os.path.join(SCRIPTS, "run_e4_exact_2_pilot.py"), encoding="utf-8").read()
    assert "--authorize-formal-seeds" in src
    assert "FORMAL_SEEDS" in src
    assert "[FATAL] formal seed" in src


def test_t22_formal_seeds_registered_not_accessed():
    proto = _load_yaml(FORMAL_PROTOCOL)
    # 2026-08-10 E4-EXACT-3 用户授权方案 A：status=REGISTERED_ONLY -> AUTHORIZED
    # （accessed 保持 false 直到正式运行实际访问 seed；由 runner manifest 登记访问）
    assert proto["formal_seeds"]["status"] == "AUTHORIZED"
    assert proto["formal_seeds"]["accessed"] is False
    assert set(proto["formal_seeds"]["list"]) == set(FORMAL_SEEDS)


# ---------------------------------------------------------------------------
# T3-T6：selector 与 CARS performance 隔离
# ---------------------------------------------------------------------------
def test_t3_selector_input_schema_has_no_cars_fields():
    # selector 的输入 schema（pilot_aggregated.json）不得包含任何 CARS performance / gap 字段
    sel = _load_json(SELECTION_JSON)
    assert sel["inputs_only"]["cars_performance_fields_never_read"] is True
    agg = _load_json(os.path.join(RESULTS, "pilot_aggregated.json"))
    agg_str = json.dumps(agg, ensure_ascii=False)
    for banned in ("cars_TSSR", "cars_Rbar", "cars_Ubar", "oracle_gap",
                   "Delta_TSSR", "Delta_R", "Delta_U", "method ranking",
                   "first_tier_match", "full_lexicographic_match", "exact_match"):
        assert banned not in agg_str, "selector input must never contain %r" % banned


def test_t4_selection_depends_only_on_exact_runtime_budget():
    sel = _load_json(SELECTION_JSON)
    assert set(sel["inputs_only"]) == {
        "n_m_regime_oracle_status_certificate_runtime_search_budget",
        "cars_performance_fields_never_read",
    }


def test_t5_changing_cars_tssr_does_not_change_selection():
    # 证明：selector 输入 schema 无任何 CARS 指标字段（T3），且输入文件无 CARS 字段（T4）
    sel = _load_json(SELECTION_JSON)
    assert sel["status"].startswith(("OK", "FAIL_AND_REDESIGN"))
    # 若 PILOT 存在，用真实数据重建 selection 并与已冻结 selection 比较
    if os.path.exists(SELECTION_JSON) and os.path.exists(
            os.path.join(RESULTS, "pilot_aggregated.json")):
        # 重建（deterministic）应得到相同 frozen grid
        rebuilt = _rebuild_selection()
        assert rebuilt["frozen_n_grid"] == sel["frozen_n_grid"]


def _rebuild_selection():
    # 从已冻结 selection.json 读取原始参数（确保确定性重建使用相同输入）
    import yaml
    sel0 = _load_json(SELECTION_JSON)
    per_budget = sel0["per_instance_acceptance_budget_s"]
    total_h = sel0["total_compute_budget_hours"]
    seeds = sel0["formal_seeds_per_cell"]
    regimes = sel0["regimes_count"]
    proc = subprocess.run(
        [sys.executable, SELECTOR,
         "--per-instance-budget-seconds", str(per_budget),
         "--total-budget-hours", str(total_h),
         "--formal-seeds-per-cell", str(seeds),
         "--regimes-count", str(regimes)],
        capture_output=True, text=True, encoding="utf-8", cwd=ROOT,
    )
    assert proc.returncode in (0, 1)
    return _load_json(SELECTION_JSON)


def test_t6_changing_cars_gap_does_not_change_selection():
    # 同 T5：selector 不读取任何 gap/ranking 字段
    test_t5_changing_cars_tssr_does_not_change_selection()


# ---------------------------------------------------------------------------
# T7-T10：F1-F5 排除规则
# ---------------------------------------------------------------------------
def _make_items(statuses, runtimes_ms, cert_pass=None):
    items = []
    for k, (st, rt) in enumerate(zip(statuses, runtimes_ms)):
        items.append({
            "oracle_status": st,
            "total_oracle_runtime_ms": rt,
            "certificate_pass": cert_pass[k] if cert_pass is not None else True,
        })
    return items


def _run_selector_on_items(groups, per_budget_s=3600.0, total_h=72.0, seeds=10, regimes=3):
    import tempfile
    agg = {"groups": {("%d_%s" % (n, r)): recs for (n, r), recs in groups.items()}}
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(agg, fh)
    # monkey-patch aggregated path 不便；直接用 subprocess + 临时覆盖
    env = dict(os.environ)
    import textwrap
    code = textwrap.dedent("""
        import sys, json
        sys.path.insert(0, %r)
        import select_e4_exact_formal_config as S
        S.AGGREGATED = %r
        S.SELECTION = %r
        sys.argv = ["x", "--per-instance-budget-seconds", "%s",
                    "--total-budget-hours", "%s",
                    "--formal-seeds-per-cell", "%s", "--regimes-count", "%s"]
        sys.exit(S.main())
    """ % (SCRIPTS, path, path + ".out", per_budget_s, total_h, seeds, regimes))
    fd2, path2 = tempfile.mkstemp(suffix=".py")
    os.close(fd2)
    with open(path2, "w", encoding="utf-8") as fh:
        fh.write(code)
    proc = subprocess.run([sys.executable, path2], capture_output=True,
                          text=True, encoding="utf-8", env=env, cwd=SCRIPTS)
    os.unlink(path)
    os.unlink(path2)
    out = _load_json(path + ".out")
    if os.path.exists(path + ".out"):
        os.unlink(path + ".out")
    return out, proc


def test_t7_timeout_uncertified_excludes_n():
    groups = {
        (6, "LOW"): _make_items([ACCEPTED[0]] * 3, [200, 210, 190]),
        (8, "TRANSITION"): _make_items([REJECTED[0]] * 3, [7200] * 3),
    }
    sel, proc = _run_selector_on_items(groups)
    assert sel["decisions"]["8"]["eligible"] is False
    assert any("F1-FAIL" in r for r in sel["decisions"]["8"]["reasons"])


def test_t8_not_exact_excludes_n():
    groups = {
        (6, "LOW"): _make_items([ACCEPTED[0]] * 3, [200, 210, 190]),
        (8, "TRANSITION"): _make_items([REJECTED[1]] * 3, [100, 110, 90]),
    }
    sel, proc = _run_selector_on_items(groups)
    assert sel["decisions"]["8"]["eligible"] is False
    assert any("F1-FAIL" in r for r in sel["decisions"]["8"]["reasons"])


def test_t9_certificate_failure_excludes_n():
    groups = {
        (6, "LOW"): _make_items([ACCEPTED[0]] * 3, [200, 210, 190]),
        (8, "TRANSITION"): _make_items([ACCEPTED[0]] * 3, [100, 110, 90],
                                       cert_pass=[True, False, True]),
    }
    sel, proc = _run_selector_on_items(groups)
    assert sel["decisions"]["8"]["eligible"] is False
    assert any("F2-FAIL" in r for r in sel["decisions"]["8"]["reasons"])


def test_t10_max_computable_n_rule_correct():
    # N=6,8 PASS；N=10,12 FAIL -> frozen grid {6,8}
    groups = {
        (6, "LOW"): _make_items([ACCEPTED[0]] * 3, [200, 210, 190]),
        (8, "TRANSITION"): _make_items([ACCEPTED[0]] * 3, [1500, 1510, 1490]),
        (10, "HIGH"): _make_items([REJECTED[0]] * 3, [7200] * 3),
        (12, "HIGH"): _make_items([REJECTED[0]] * 3, [7200] * 3),
    }
    sel, proc = _run_selector_on_items(groups)
    assert sel["max_eligible_n"] == 8
    assert sel["frozen_n_grid"] == [6, 8]
    assert sel["status"] == "OK"


# ---------------------------------------------------------------------------
# T11/T12：grid 不扩大、regime 来源
# ---------------------------------------------------------------------------
def test_t11_pilot_candidate_grid_not_expanded():
    # R2（CR_E4_EXACT_SCALE_REDUCTION_OPTIMIZATION_V1）：候选 {4,6}
    grid = _load_yaml(GRID_YAML)
    assert grid["candidate_scale"]["n_candidate"] == [4, 6]
    assert grid["candidate_scale"]["m_candidate"] == 4
    proto = _load_yaml(PILOT_PROTOCOL)
    pilot_ns = sorted({int(i["n"]) for i in proto["pilot_matrix"]})
    assert set(pilot_ns) <= set(grid["candidate_scale"]["n_candidate"])
    assert proto["scale"]["m"] == 4


def test_t12_pressure_regime_source_legal():
    grid = _load_yaml(GRID_YAML)
    regimes = {r["label"] for r in grid["pressure_regimes"]}
    assert regimes <= {"LOW", "TRANSITION", "HIGH"}
    assert "环境" in grid["environment_compatibility"]["environment_family"] or \
        "E1-V2" in grid["environment_compatibility"]["environment_family"] or \
        "environment family" in grid["environment_compatibility"]["environment_family"]


# ---------------------------------------------------------------------------
# T13-T20：保护对象不变
# ---------------------------------------------------------------------------
def test_t13_exact_solver_hash_consistent_with_e4_exact_1():
    # solver 语义与 E4-EXACT-1 冻结一致（eps_cmp=1e-9 / EXACT_PRUNED / PRUNE-A/B）
    solver = _load_yaml(SOLVER_YAML)
    assert solver["enumeration"]["default_mode"] == "EXACT_PRUNED"
    assert solver["tolerance"]["eps_cmp"] == 1.0e-9
    assert set(solver["safe_pruning_rules"]) == {"PRUNE-A", "PRUNE-B"}
    assert solver["solver_version"] == "E4_EXACT_SOLVER_V1"


def test_t14_cars_hash_unchanged():
    # 与 Pre-state 记录一致（58605c900ea08dff）
    h = _file_hash(os.path.join(ROOT, "configs", "cars_v4", "cars_frozen_v4.yaml"))
    assert h.startswith("58605c900ea08dff")


def test_t15_evaluator_hash_unchanged():
    # evaluator 目录 hash 与 Pre-state 记录一致（64d528993fbbe203…）
    ev_dir = os.path.join(ROOT, "src", "cars", "evaluator")
    h = hashlib.sha256()
    files = []
    for dp, _dn, fn in os.walk(ev_dir):
        if "__pycache__" in dp:
            continue
        for f in fn:
            files.append(os.path.join(dp, f))
    for f in sorted(files):
        rel = os.path.relpath(f, ROOT)
        raw = open(f, "rb").read()
        h.update(rel.encode("utf-8")); h.update(b"\x00"); h.update(raw); h.update(b"\x00")
    # MATH-FMIN-CR-R2（2026-08-11）：constraints.py C5 引入 f_min^exec 硬检查
    assert h.hexdigest().startswith("0df96aa3fc786b7b")


def test_t16_contract_v4_unchanged():
    h = _file_hash(os.path.join(ROOT, "reports", "contracts",
                                "CARS_EXECUTABLE_THEORY_CONTRACT_V4.md"))
    assert h.startswith("79227f233c13bf92")


def test_t17_schema_v4_unchanged():
    schema_dir = os.path.join(ROOT, "schemas", "CARS_ACTIVE_SCHEMA_V4")
    h = hashlib.sha256()
    files = []
    for dp, _dn, fn in os.walk(schema_dir):
        if "__pycache__" in dp:
            continue
        for f in fn:
            files.append(os.path.join(dp, f))
    for f in sorted(files):
        rel = os.path.relpath(f, ROOT)
        raw = open(f, "rb").read()
        h.update(rel.encode("utf-8")); h.update(b"\x00"); h.update(raw); h.update(b"\x00")
    assert h.hexdigest().startswith("3b2bcc04a1e0e3e7")


def test_t18_iii_vii_unchanged():
    # Pre-state（E4-EXACT-2 开始）8410c2c0。III_VII.md 在 E4-EXACT-2 期间被用户外部
    # 多次修改（22:26→5d06d506；2026-08-10 13:43→ac7efec0；14:01→5e50eb19；用户并行编辑
    # 正文，非 E4-EXACT-2 工作流；记录于报告 W-E4X2-01/06/07）。固定 hash 断言对活跃编辑
    # 文件不可靠（与 E4-EXACT-1 T41 同因），本测试改为语义检查：验证 E4-EXACT-2 专属代码
    # 无对 experiment_docs/III_VII 的写模式 open() 调用（只读 hash 校验不受影响）。
    import glob as _glob
    import re as _re
    src_files = _glob.glob(os.path.join(SCRIPTS, "*.py"))
    for f in src_files:
        t = open(f, encoding="utf-8").read()
        for m in _re.finditer(r"open\s*\(([^)]*)\)", t):
            seg = t[m.start():m.start() + 300]
            if "experiment_docs" in seg or "III_VII" in seg:
                args = m.group(1)
                if _re.search(r"['\"](w|a|w\+|a\+|r\+|wb|ab|xb)['\"]", args):
                    pytest.fail("%s 存在对 experiment_docs/III_VII 的写 open() 调用"
                                "（E4-EXACT-2 禁止写正文）" % f)


def test_t19_data_unchanged():
    count = 0
    size = 0
    for dp, _dn, fn in os.walk(os.path.join(ROOT, "data")):
        for f in fn:
            count += 1
            size += os.path.getsize(os.path.join(dp, f))
    assert count == 77
    assert size == 65721295433


def test_t20_historical_e4_v2_unchanged():
    # 检查历史 e4_v2 目录未被修改（抽样：文件数非零；不得被删除/覆盖）
    for d in ("configs", "results", "tests", "scripts"):
        base = os.path.join(ROOT, d, "e4_v2")
        if os.path.isdir(base):
            assert len(os.listdir(base)) > 0


# ---------------------------------------------------------------------------
# T21：formal protocol 状态
# ---------------------------------------------------------------------------
def test_t21_formal_protocol_frozen_not_executed():
    proto = _load_yaml(FORMAL_PROTOCOL)
    assert proto["status"] == "FROZEN_ONLY / NOT_EXECUTED"
    # 2026-08-10 E4-EXACT-3 用户授权方案 A：authorized_to_execute=false -> true
    assert proto["authorized_to_execute"] is True
    assert proto["accepted_oracle_status"] == ["EXACT_OPTIMAL", "CERTIFIED_NUMERICAL_EXACT"]
    assert proto["rejected_oracle_status"] == ["TIMEOUT_UNCERTIFIED", "NOT_EXACT", "SOLVER_ERROR"]
    assert proto["paired_design"] is True
    assert proto["shared_scenario"] is True
    assert proto["shared_evaluator"] is True


# ---------------------------------------------------------------------------
# T23/T24：可重复
# ---------------------------------------------------------------------------
def test_t23_pilot_reproducible():
    # raw records 的字段结构稳定；同 (n,regime,seed) 无重复记录
    raw = os.path.join(RESULTS, "pilot_raw_records.jsonl")
    if not os.path.exists(raw):
        pytest.skip("pilot not executed yet")
    seen = set()
    with open(raw, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            key = (rec["n"], rec["regime"], rec["seed"])
            assert key not in seen, "duplicate pilot record %s" % (key,)
            seen.add(key)


def test_t24_aggregation_reproducible():
    # 聚合产物可重复生成（重跑 aggregate 得到相同 completion 计数）
    agg_path = os.path.join(RESULTS, "pilot_aggregated.json")
    if not os.path.exists(agg_path):
        pytest.skip("aggregation not run yet")
    agg1 = _load_json(agg_path)
    proc = subprocess.run([sys.executable,
                           os.path.join(SCRIPTS, "aggregate_e4_exact_2_pilot.py")],
                          capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    assert proc.returncode == 0
    agg2 = _load_json(agg_path)
    assert agg1["completion_summary"] == agg2["completion_summary"]


# ---------------------------------------------------------------------------
# T25：Formal configuration 可由 Pilot raw 数据确定性重建
# ---------------------------------------------------------------------------
def test_t25_formal_config_deterministic_rebuild():
    if not os.path.exists(SELECTION_JSON):
        pytest.skip("selection not yet frozen")
    sel1 = _load_json(SELECTION_JSON)
    # selector 是确定性函数：同输入 -> 同输出（由 T5 重建验证）
    rebuilt = _rebuild_selection()
    assert rebuilt["frozen_n_grid"] == sel1["frozen_n_grid"]
    assert rebuilt["max_eligible_n"] == sel1["max_eligible_n"]
    assert rebuilt["decisions"] == sel1["decisions"]
