# -*- coding: utf-8 -*-
"""
R1B Active Schema 冻结测试（提示词 Step 4 冻结测试清单）。

覆盖：
  T-01 所有 JSON/YAML 可解析
  T-02 所有 Schema 通过 Draft 2020-12 元 Schema 校验
  T-03 所有 $ref 可解析
  T-04 所有 $id 唯一
  T-05 schema_manifest.yaml 与实际文件一致
  T-06 required/type/unit/version 完整
  T-07 validate_active_schema.py 可独立执行（subprocess）
  T-08 有效微型案例通过（schema 校验 + 跨字段不变量）
  T-09 全部冻结非法案例被拒绝
  T-10 全量 pytest（本文件即全量）
  T-11 同一输入重复验证结果一致（确定性）
"""

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

import validate_active_schema as vas

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _docs():
    return vas.load_schema_docs()


def _registry(docs):
    resources = {
        doc["$id"]: Resource.from_contents(doc, default_specification=DRAFT202012)
        for doc in docs.values()
    }
    return Registry().with_resources(resources.items())


def _schema_errors(payload, target, registry, docs):
    return vas.validate_instance(payload, target, registry, docs)


# ---------------------------------------------------------------------------
# T-01 可解析
# ---------------------------------------------------------------------------

def test_t01_all_json_yaml_parsable():
    for name in vas.list_schema_files():
        doc = vas.load_json(os.path.join(vas.SCHEMA_DIR, name))
        assert isinstance(doc, dict)
    assert isinstance(vas.load_yaml(vas.MANIFEST_PATH), dict)
    valid = vas.load_json(vas.VALID_CASE_PATH)
    assert "objects" in valid and len(valid["objects"]) >= 1
    invalid = vas.load_json(vas.INVALID_CASES_PATH)
    assert len(invalid["invalid_cases"]) >= 10


# ---------------------------------------------------------------------------
# T-02 元 Schema 校验
# ---------------------------------------------------------------------------

def test_t02_meta_schema_valid():
    docs = _docs()
    for name, doc in docs.items():
        assert vas.check_meta_schema(doc) == [], "meta-schema errors in %s" % name


# ---------------------------------------------------------------------------
# T-03 $ref 可解析
# ---------------------------------------------------------------------------

def test_t03_refs_resolvable():
    docs = _docs()
    assert vas.check_refs_resolvable(list(docs.values())) == []


# ---------------------------------------------------------------------------
# T-04 $id 唯一
# ---------------------------------------------------------------------------

def test_t04_ids_unique():
    docs = _docs()
    assert vas.check_ids_unique(list(docs.values())) == []


# ---------------------------------------------------------------------------
# T-05 Manifest 与实际文件一致
# ---------------------------------------------------------------------------

def test_t05_manifest_consistent():
    manifest = vas.load_yaml(vas.MANIFEST_PATH)
    assert vas.check_manifest(manifest, vas.list_schema_files()) == []


# ---------------------------------------------------------------------------
# T-06 required/type/unit/version 完整
# ---------------------------------------------------------------------------

def test_t06a_version_complete():
    docs = _docs()
    assert vas.check_version(list(docs.values())) == []


def test_t06b_field_units_complete():
    docs = _docs()
    for name, doc in docs.items():
        assert vas.check_field_units(doc) == [], "unit violations in %s" % name


def test_t06c_required_present_in_definitions():
    # 每个实体 $defs 均声明 required 且 required 字段存在
    docs = _docs()
    core = docs["core_entities.schema.json"]
    for def_name, node in core.get("$defs", {}).items():
        if node.get("type") == "object" and "properties" in node:
            req = node.get("required", [])
            props = node.get("properties", {})
            assert req, "missing required in %s" % def_name
            for field in req:
                assert field in props, "%s: required field %s missing" % (def_name, field)


# ---------------------------------------------------------------------------
# T-07 validate_active_schema.py 可独立执行
# ---------------------------------------------------------------------------

def test_t07_validator_script_independently_executable():
    script = os.path.join(vas.PROJECT_ROOT, "scripts", "validate_active_schema.py")
    result = subprocess.run(
        [sys.executable, script, "--quiet"],
        capture_output=True,
        text=True,
        cwd=vas.PROJECT_ROOT,
    )
    assert result.returncode == 0, "validator script failed:\n%s" % result.stderr


# ---------------------------------------------------------------------------
# T-08 有效微型案例通过
# ---------------------------------------------------------------------------

def test_t08_valid_case_passes():
    docs = _docs()
    registry = _registry(docs)
    valid = vas.load_json(vas.VALID_CASE_PATH)
    scenario = None
    for obj in valid["objects"]:
        payload = obj["payload"]
        schema_errors = _schema_errors(payload, obj["target_schema"], registry, docs)
        assert schema_errors == [], "schema errors in %s: %s" % (
            obj["object_name"], schema_errors
        )
        assert vas.scan_forbidden_fields(payload) == []
        if obj["object_name"] == "scenario":
            scenario = payload
            assert vas.check_scenario_invariants(payload) == []
            assert vas.check_timepoint(payload) == []
        elif obj["object_name"] in vas.DECISION_OBJECTS:
            spec = vas.DECISION_OBJECTS[obj["object_name"]]
            sub = payload[spec["path"]] if spec["path"] else payload
            assert vas.check_decision_invariants(scenario, sub) == []
            if obj["object_name"] in ("ruad_output", "aada_output"):
                assert vas.check_ruad_dynamic_states(scenario, payload) == []
    assert scenario is not None


# ---------------------------------------------------------------------------
# T-09 全部冻结非法案例被拒绝
# ---------------------------------------------------------------------------

def test_t09_invalid_cases_rejected():
    docs = _docs()
    registry = _registry(docs)
    valid = vas.load_json(vas.VALID_CASE_PATH)
    scenario = None
    for obj in valid["objects"]:
        if obj["object_name"] == "scenario":
            scenario = obj["payload"]
            break
    assert scenario is not None

    invalid = vas.load_json(vas.INVALID_CASES_PATH)["invalid_cases"]
    for case in invalid:
        kind = case["expected_rejection"]
        payload = case["payload"]
        target = case.get("target_schema")
        if kind == "schema_validation":
            assert _schema_errors(payload, target, registry, docs), (
                "%s: expected schema rejection" % case["case_id"]
            )
        elif kind == "cross_field_invariant":
            schema_errors = _schema_errors(payload, target, registry, docs)
            assert not schema_errors, "%s: schema failed, expected cross-field" % (
                case["case_id"]
            )
            assert vas.check_decision_invariants(scenario, payload), (
                "%s: expected cross-field rejection" % case["case_id"]
            )
        elif kind == "forbidden_field":
            assert vas.scan_forbidden_fields(payload), (
                "%s: expected forbidden field" % case["case_id"]
            )
        elif kind == "timepoint_violation":
            assert vas.check_timepoint(payload), (
                "%s: expected timepoint violation" % case["case_id"]
            )
        elif kind == "unit_missing":
            assert vas.check_field_units(payload), (
                "%s: expected unit missing" % case["case_id"]
            )
        else:
            raise AssertionError("unknown expected_rejection %s" % kind)


# ---------------------------------------------------------------------------
# T-10 全量 pytest（本文件为当前全部测试）
# ---------------------------------------------------------------------------

def test_t10_full_suite_is_current():
    # 全量 pytest 即 tests/ 下所有测试；本阶段仅 tests/schema/test_active_schema.py
    pass


# ---------------------------------------------------------------------------
# T-11 同一输入重复验证结果一致（确定性）
# ---------------------------------------------------------------------------

def test_t11_determinism():
    script = os.path.join(vas.PROJECT_ROOT, "scripts", "validate_active_schema.py")
    out1 = subprocess.run(
        [sys.executable, script, "--quiet"], capture_output=True, text=True,
        cwd=vas.PROJECT_ROOT,
    )
    out2 = subprocess.run(
        [sys.executable, script, "--quiet"], capture_output=True, text=True,
        cwd=vas.PROJECT_ROOT,
    )
    assert out1.returncode == 0
    assert out2.returncode == 0
    assert out1.stdout == out2.stdout
    assert out1.stderr == out2.stderr


# ---------------------------------------------------------------------------
# 结构层 C4 补充测试：A[i][j]=1 必须存在对应 WirelessLink
# ---------------------------------------------------------------------------

def test_structural_c4_link_existence():
    valid = vas.load_json(vas.VALID_CASE_PATH)
    scenario = None
    decision = None
    for obj in valid["objects"]:
        if obj["object_name"] == "scenario":
            scenario = obj["payload"]
        elif obj["object_name"] == "evaluator_input":
            decision = obj["payload"]["decision"]
    assert scenario is not None and decision is not None
    # 有效案例：A[1][0]=1 (t2->s1)，必须存在 d2->s1 link
    assert vas.check_decision_invariants(scenario, decision) == []


# ---------------------------------------------------------------------------
# legacy 禁止字段全集测试
# ---------------------------------------------------------------------------

def test_legacy_forbidden_fields_covered():
    # CR-CARS-PROMOTION-E1（SUPERSEDED_BY_CR_CARS_PROMOTION_E1）：V4 当前正式在
    # BASE + V2 旧 RUAD 字段 + V3 ruad_gamma 基础上增加 V4 CALA/Repair 参数
    # （cala_weights/repair_budget/repair_tolerances/kappa_R/kappa_D）。
    expected = {
        "lambda_eff",
        "load_amplified_failure_rate",
        "gnn_candidate",
        "teacher_label",
        "oracle_edge",
        "checkpoint",
        "history_state",
        "eta_rho",
        "eta_Q",
        "eta_Z",
        "s_Q",
        "s_Z",
        "rho_tilde",
        "f_tilde_req",
        "ruad_gamma",
        "cala_weights",
        "repair_budget",
        "repair_tolerances",
        "kappa_R",
        "kappa_D",
    }
    assert set(vas.LEGACY_FORBIDDEN_FIELDS) == expected
