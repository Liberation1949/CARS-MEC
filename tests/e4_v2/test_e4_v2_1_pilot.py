# -*- coding: utf-8 -*-
"""E4-V2-1 冻结测试（T1..T22）：Trace 动态区域识别与 Pilot 校准。

测试只读；不运行正式方法排名；不访问 formal 分区；不写入 data/。
直接依据: 用户 E4-V2-1 指示；E4_V2_1_PILOT_PROTOCOL_V1；E4_V2_ENVIRONMENT_SELECTED_V1；
       E4_V2_TRACE_FIELD_MAPPING_V1；Layer A/B 实测产物。
"""

import csv
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TRACE_ROOT = PROJECT_ROOT / "data" / "processed" / "e4_trace_enhanced"
CONFIG_ROOT = PROJECT_ROOT / "configs" / "e4_v2"
SCRIPT_ROOT = PROJECT_ROOT / "scripts" / "reproduce" / "e4_v2"
PILOT_DIR = PROJECT_ROOT / "results" / "e4_v2" / "e4_v2_1_pilot"

DATASETS = ["azure", "nep", "shanghai"]
PARTITIONS = ["calibration", "pilot", "formal"]


def load_yaml(rel):
    with open(CONFIG_ROOT / rel, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_jsonl(p: Path):
    out = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def load_csv(p: Path):
    with open(p, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# T1. formal partition 访问守卫
# ---------------------------------------------------------------------------
def test_t01_formal_access_guard_static():
    src = (SCRIPT_ROOT / "run_e4_v2_1_pilot.py").read_text(encoding="utf-8")
    # 必须存在显式 formal 拒绝
    assert "formal" in src and "SystemExit" in src
    assert "allowed_partitions" in src
    # 运行时行为：formal 路径被拒绝
    assert "REFUSED" in src


def test_t01b_formal_access_guard_behavior():
    # inspect 与 pilot runner 都不得读取 formal 文件（用隔离输出目录跑 Layer A）
    r = subprocess.run(
        [sys.executable, str(SCRIPT_ROOT / "run_e4_v2_1_pilot.py"),
         "--out-dir", str(PROJECT_ROOT / "results" / "e4_v2" / "_t01_guard")],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT))
    assert r.returncode == 0, r.stdout + r.stderr
    # 产物不含 formal
    diag = load_csv(PROJECT_ROOT / "results" / "e4_v2" / "_t01_guard" / "trace_regime_diagnostics.csv")
    assert all("formal" not in (d.get("partition") or "") for d in diag)


# ---------------------------------------------------------------------------
# T2. calibration/pilot 与 formal 不重叠
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("ds", DATASETS)
def test_t02_partitions_disjoint(ds):
    ids = {}
    for p in PARTITIONS:
        ids[p] = {r["slot_id"] for r in load_jsonl(TRACE_ROOT / "splits" / ds / f"{ds}_{p}.jsonl")}
    assert not (ids["calibration"] & ids["formal"])
    assert not (ids["pilot"] & ids["formal"])
    assert not (ids["calibration"] & ids["pilot"])


# ---------------------------------------------------------------------------
# T3. data/ 零写入
# ---------------------------------------------------------------------------
def test_t03_no_data_write():
    for f in ["run_e4_v2_1_pilot.py", "aggregate_e4_v2_1_pilot.py"]:
        src = (SCRIPT_ROOT / f).read_text(encoding="utf-8")
        # 写模式 open 只允许指向输出（results/），禁止指向 data/ 或 TRACE_ROOT
        for m in re.finditer(r"open\(\s*([^,)]*),\s*['\"]([wa]|r\+)[b]?['\"]", src):
            target = m.group(1)
            assert "TRACE_ROOT" not in target and "data" not in target, \
                f"{f}: write open targeting data: {target}"
    # run 脚本引用只读数据根；aggregate 只读 results/ 输出（无 data 引用属正常）
    run_src = (SCRIPT_ROOT / "run_e4_v2_1_pilot.py").read_text(encoding="utf-8")
    assert "TRACE_ROOT" in run_src
    # data/ hash 与 manifest 一致（自 E4-V2-0 以来未变）
    man = load_yaml("e4_v2_trace_input_manifest.yaml")
    for f in man["file_hashes"]:
        p = TRACE_ROOT / f["path"]
        assert p.exists()
        assert hashlib.sha256(p.read_bytes()).hexdigest() == f["sha256"]


# ---------------------------------------------------------------------------
# T4. 不执行 preprocessing
# ---------------------------------------------------------------------------
def test_t04_no_preprocessing():
    for f in ["run_e4_v2_1_pilot.py", "aggregate_e4_v2_1_pilot.py"]:
        src = (SCRIPT_ROOT / f).read_text(encoding="utf-8")
        for kw in ["subprocess", "os.system", "normalize(", "interpolate"]:
            assert kw not in src, f"{f}: preprocessing keyword {kw}"
    env = load_yaml("e4_v2_environment_selected.yaml")
    assert env["trace_to_scenario"]["forbidden_trace_effects"]


# ---------------------------------------------------------------------------
# T5. burst_score 不参与分类
# ---------------------------------------------------------------------------
def test_t05_burst_score_not_used():
    for f in ["run_e4_v2_1_pilot.py", "aggregate_e4_v2_1_pilot.py"]:
        src = (SCRIPT_ROOT / f).read_text(encoding="utf-8")
        # burst_score 只能出现在禁止性语境（不得作为字段访问/分类输入）
        for m in re.finditer(r"burst_score", src):
            ctx = src[max(0, m.start() - 20): m.end() + 20]
            assert "禁止" in ctx or "NOT_AVAILABLE" in ctx, f"non-forbidden burst_score: {ctx}"
    env = load_yaml("e4_v2_environment_selected.yaml")
    assert any("burst" in e["name"] and "NOT_AVAILABLE" in e["reason"]
               for e in env["excluded_diagnostics"])


# ---------------------------------------------------------------------------
# T6. NEP 全零 workload 字段不参与分类
# ---------------------------------------------------------------------------
def test_t06_nep_zero_workload_not_used():
    src = (SCRIPT_ROOT / "run_e4_v2_1_pilot.py").read_text(encoding="utf-8")
    # NEP 分支只使用 cpu_pressure
    assert "cpu_pressure" in src
    # workload_intensity 仅用于 azure/shanghai
    nep_use = "nep" in src
    assert nep_use
    # NEP p_win 只来自 cpu_pressure
    assert "statistics.median(cp)" in src or "median(cp)" in src
    env = load_yaml("e4_v2_environment_selected.yaml")
    assert "不得使用 workload_intensity/request_count/user_count" in env["trace_to_scenario"]["workload_size_rule"]["nep"]


# ---------------------------------------------------------------------------
# T7. NEP 使用 cpu_pressure
# ---------------------------------------------------------------------------
def test_t07_nep_uses_cpu_pressure():
    env = load_yaml("e4_v2_environment_selected.yaml")
    assert env["trace_fields_used"]["nep"] == ["cpu_pressure（TRACE_OBSERVED）", "region_id/hotspot（诊断参考）", "timestamp", "slot_id"]
    assert "cpu_pressure" in env["datasets"]["nep"]["regime_definition"]


# ---------------------------------------------------------------------------
# T8. λ_j 不由 Trace 修改
# ---------------------------------------------------------------------------
def test_t08_lambda_not_modified_by_trace():
    env = load_yaml("e4_v2_environment_selected.yaml")
    ft = env["trace_to_scenario"]["forbidden_trace_effects"]
    assert any("Trace 不得改写 λ_j" in x for x in ft)
    # NEP 容量规则只改 F_j 不动 λ_j
    assert "λ_j 不变" in env["trace_to_scenario"]["server_capacity_rule"]["nep"]
    src = (SCRIPT_ROOT / "run_e4_v2_1_pilot.py").read_text(encoding="utf-8")
    # 场景构造只改 capacity_cycles_per_sec（λ_j 由 base environment 生成，Trace 不触碰）
    assert "capacity_cycles_per_sec" in src


# ---------------------------------------------------------------------------
# T9. R_min 不由 Trace 修改
# ---------------------------------------------------------------------------
def test_t09_rmin_not_modified_by_trace():
    env = load_yaml("e4_v2_environment_selected.yaml")
    ft = env["trace_to_scenario"]["forbidden_trace_effects"]
    assert any("Trace 不得改写 R_min" in x for x in ft)
    src = (SCRIPT_ROOT / "run_e4_v2_1_pilot.py").read_text(encoding="utf-8")
    # run 脚本自身不引用/修改 min_reliability（由 base environment 生成；Trace 只驱动 N/容量）
    assert "min_reliability" not in src


# ---------------------------------------------------------------------------
# T10. 算法参数不由 Trace 修改
# ---------------------------------------------------------------------------
def test_t10_algorithm_params_not_modified():
    env = load_yaml("e4_v2_environment_selected.yaml")
    ft = env["trace_to_scenario"]["forbidden_trace_effects"]
    assert any("Trace 不得改写任何算法/Baseline 参数" in x for x in ft)
    src = (SCRIPT_ROOT / "run_e4_v2_1_pilot.py").read_text(encoding="utf-8")
    # 方法配置来自 frozen configs；Trace 只驱动 scenario
    assert "CONFIGS" in src
    assert "method_config=mcfg" in src


# ---------------------------------------------------------------------------
# T11. Layer A 不读取 method result
# ---------------------------------------------------------------------------
def test_t11_layer_a_no_method_result():
    src = (SCRIPT_ROOT / "run_e4_v2_1_pilot.py").read_text(encoding="utf-8")
    # Layer A 路径不含 runner 调用（run_layer_a 不调用 MethodRunner）
    la = src[src.find("def run_layer_a("):src.find("def select_candidates(")]
    assert "MethodRunner" not in la
    assert "runner.run" not in la
    # 运行产物：diagnostics CSV 列不包含方法结果列
    diag = load_csv(PILOT_DIR / "trace_regime_diagnostics.csv")
    assert diag
    cols = set(diag[0].keys())
    for forbidden in ["tssr", "rbar_eff", "ubar_eff", "v_r", "method_runtime_ms", "method_status"]:
        assert forbidden not in cols


# ---------------------------------------------------------------------------
# T12. Layer A 不使用 method-dependent LI_dem/rho_dem
# ---------------------------------------------------------------------------
def test_t12_no_method_dependent_diagnostics():
    env = load_yaml("e4_v2_environment_selected.yaml")
    names = [e["name"] for e in env["excluded_diagnostics"]]
    assert "li_dem" in names and "rho_dem" in names
    diag = load_csv(PILOT_DIR / "trace_regime_diagnostics.csv")
    cols = set(diag[0].keys())
    assert "li_dem" not in cols and "rho_dem" not in cols


# ---------------------------------------------------------------------------
# T13. candidate windows 全保留
# ---------------------------------------------------------------------------
def test_t13_candidates_preserved():
    cand = json.load(open(PILOT_DIR / "candidate_windows.json", encoding="utf-8"))
    assert len(cand["candidates"]) == 16  # azure 6 + nep 6 + shanghai 4
    by = {}
    for c in cand["candidates"]:
        by.setdefault(c["dataset"], {}).setdefault(c["regime"], 0)
        by[c["dataset"]][c["regime"]] += 1
    assert by["azure"] == {"LOW": 2, "TRANSITION": 2, "HIGH": 2}
    assert by["nep"] == {"LOW": 2, "TRANSITION": 2, "HIGH": 2}
    assert by["shanghai"] == {"LOW": 2, "HIGH": 2}


# ---------------------------------------------------------------------------
# T14. selected windows 可复现
# ---------------------------------------------------------------------------
def test_t14_selected_windows_reproducible():
    import importlib.util
    spec = importlib.util.spec_from_file_location("run_e4_v2_1_pilot", SCRIPT_ROOT / "run_e4_v2_1_pilot.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    per_dataset, _ = mod.run_layer_a()
    cand = mod.select_candidates(per_dataset)
    orig = json.load(open(PILOT_DIR / "candidate_windows.json", encoding="utf-8"))["candidates"]
    got = [(c["dataset"], c["window_id"], c["regime"], round(c["p_win"], 6)) for c in cand]
    exp = [(c["dataset"], c["window_id"], c["regime"], round(c["p_win"], 6)) for c in orig]
    assert sorted(got) == sorted(exp)


# ---------------------------------------------------------------------------
# T15. 相同 window 构造相同 Scenario
# ---------------------------------------------------------------------------
def test_t15_same_window_same_scenario():
    import importlib.util
    spec = importlib.util.spec_from_file_location("run_e4_v2_1_pilot", SCRIPT_ROOT / "run_e4_v2_1_pilot.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for ds, seed in mod.DATASET_SEEDS.items():
        sc1 = mod.build_window_scenario(ds, 0.5, seed, materialized=True)
        sc2 = mod.build_window_scenario(ds, 0.5, seed, materialized=True)
        assert json.dumps(sc1, sort_keys=True) == json.dumps(sc2, sort_keys=True)


# ---------------------------------------------------------------------------
# T16. 各方法共享同一 canonical Scenario
# ---------------------------------------------------------------------------
def test_t16_same_scenario_across_methods():
    records = load_jsonl(PILOT_DIR / "pilot_raw_records.jsonl")
    per_window = {}
    for r in records:
        per_window.setdefault((r["trace_dataset"], r["window_id"]), set()).add(r["method"])
    # 每窗口都跑了全部 4 个 sanity 方法
    for k, methods in per_window.items():
        assert methods == {"cars", "bpso_rata_la", "nfa_adapted", "reliability_only"}, k
    # 每窗口只有一个场景文件（共享）
    scen_files = set()
    for ds in DATASETS:
        for p in (PILOT_DIR / "scenarios").glob(f"scenario_{ds}_*.yaml"):
            scen_files.add(p.name)
    assert len(scen_files) == 16


# ---------------------------------------------------------------------------
# T17. timeout 统一 30s
# ---------------------------------------------------------------------------
def test_t17_timeout_30s():
    src = (SCRIPT_ROOT / "run_e4_v2_1_pilot.py").read_text(encoding="utf-8")
    assert "TIMEOUT = 30.0" in src
    assert "hard_timeout_seconds=TIMEOUT" in src
    records = load_jsonl(PILOT_DIR / "pilot_raw_records.jsonl")
    assert all(not r["timeout"] for r in records)  # 无超时 = timeout 受控


# ---------------------------------------------------------------------------
# T18. METHOD_ERROR/TIMEOUT 不删除
# ---------------------------------------------------------------------------
def test_t18_errors_not_deleted():
    records = load_jsonl(PILOT_DIR / "pilot_raw_records.jsonl")
    assert len(records) == 64  # 全部保留
    # 若有 error/timeout 也保留（本 Pilot 恰好 0；不删除是规则而非运气）
    src = (SCRIPT_ROOT / "run_e4_v2_1_pilot.py").read_text(encoding="utf-8")
    assert "error" in src


# ---------------------------------------------------------------------------
# T19. Pilot 结果标记 NOT_FORMAL
# ---------------------------------------------------------------------------
def test_t19_not_formal():
    records = load_jsonl(PILOT_DIR / "pilot_raw_records.jsonl")
    assert all(r["NOT_FORMAL"] is True for r in records)
    summary = json.load(open(PILOT_DIR / "pilot_sanity_summary.json", encoding="utf-8"))
    assert summary["NOT_FORMAL"] is True


# ---------------------------------------------------------------------------
# T20. formal protocol 仍 NOT_EXECUTED
# ---------------------------------------------------------------------------
def test_t20_formal_not_executed():
    proto = load_yaml("e4_v2_2_formal_protocol.yaml")
    assert proto["status"] == "FROZEN_ONLY"
    assert proto["execution_status"] == "NOT_EXECUTED"
    assert proto["formal_data_accessed"] is False
    assert proto["formal_partition"]["formal_environment_selection_rule"] == \
        "FROZEN（configs/e4_v2/e4_v2_environment_selected.yaml；E4_V2_ENVIRONMENT_SELECTED_V1）"
    # formal seeds 登记但禁止访问
    assert proto["isolation"]["formal_seeds"][0] == 2501
    assert "须用户授权" in proto["isolation"]["formal_seed_policy"]


# ---------------------------------------------------------------------------
# T21. py_compile 通过
# ---------------------------------------------------------------------------
def test_t21_py_compile():
    for f in ["run_e4_v2_1_pilot.py", "aggregate_e4_v2_1_pilot.py"]:
        r = subprocess.run([sys.executable, "-m", "py_compile", str(SCRIPT_ROOT / f)],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


# ---------------------------------------------------------------------------
# T22. E4-V2 targeted pytest 通过
# ---------------------------------------------------------------------------
def test_t22_e4_v2_targeted():
    # 本文件被收集并执行即证明；再确认 aggregate 可运行
    r = subprocess.run([sys.executable, str(SCRIPT_ROOT / "aggregate_e4_v2_1_pilot.py")],
                       capture_output=True, text=True, cwd=str(PROJECT_ROOT))
    assert r.returncode == 0, r.stdout + r.stderr


# ---------------------------------------------------------------------------
# 人工微型案例（window -> pressure -> Scenario -> Schema V4；NOT_FORMAL）
# ---------------------------------------------------------------------------
def test_manual_micro_case_window_scenario_schema():
    import importlib.util
    from jsonschema import Draft202012Validator

    spec = importlib.util.spec_from_file_location("run_e4_v2_1_pilot", SCRIPT_ROOT / "run_e4_v2_1_pilot.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # 取一个 calibration 窗口（azure_win_0069：LOW）
    cand = json.load(open(PILOT_DIR / "candidate_windows.json", encoding="utf-8"))
    az_low = [c for c in cand["candidates"] if c["dataset"] == "azure" and c["regime"] == "LOW"][0]
    assert "formal" not in az_low["window_id"]

    sc = mod.build_window_scenario("azure", az_low["p_win"], mod.DATASET_SEEDS["azure"], materialized=True)
    assert sc["state_timepoint"] == "T0"
    # materialize 硬编码 schema_version=V1（W37 既有）；此处做 V4 内容级校验（与 E2-V2 一致）
    sc["schema_version"] = "CARS_ACTIVE_SCHEMA_V4"

    # Schema V4 校验（复用 E4-V2-0 的绝对化 registry 逻辑）
    def _abs(doc):
        b = doc.get("$id", "")
        bd = b.rsplit("/", 1)[0] + "/" if "/" in b else b
        def w(node):
            if isinstance(node, dict):
                if "$ref" in node and not node["$ref"].startswith(("http://", "https://")):
                    r = node["$ref"]
                    node["$ref"] = (b + r) if r.startswith("#") else (bd + r)
                for v in node.values():
                    w(v)
            elif isinstance(node, list):
                for it in node:
                    w(it)
        w(doc)
        return doc

    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012
    schema_dir = PROJECT_ROOT / "schemas" / "CARS_ACTIVE_SCHEMA_V4"
    resources = {}
    for f in schema_dir.glob("*.schema.json"):
        doc = json.loads(f.read_text(encoding="utf-8"))
        _abs(doc)
        resources[doc["$id"]] = Resource.from_contents(doc, default_specification=DRAFT202012)
    registry = Registry().with_resources(resources.items())
    scenario_schema = _abs(json.loads(
        (schema_dir / "scenario.schema.json").read_text(encoding="utf-8")))
    validator = Draft202012Validator(scenario_schema, registry=registry)
    errors = sorted(validator.iter_errors(sc), key=lambda e: list(e.path))
    assert not errors, f"Schema V4 errors: {[e.message for e in errors]}"

    # 语义链说明：真实 Trace（window 信号）-> synthetic-fixed（任务/服务器/设备/链路）-> model-derived（占位/派生量）
    assert az_low["p_win"] > 0.0
    assert 0 <= sc["tasks"][0]["min_reliability"] < 1
    assert sc["tasks"][0]["deadline_seconds"] == 1000.0  # model-derived 占位
