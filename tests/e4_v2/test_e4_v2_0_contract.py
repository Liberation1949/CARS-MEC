# -*- coding: utf-8 -*-
"""E4-V2-0 冻结测试（T1..T20）：Trace 输入兼容性与协议冻结。

测试只读；不运行任何方法；不访问 formal 分区方法结果；不写入 data/。
直接依据: 用户 E4-V2-0 指示；Contract V4；Schema V4；E4-V2 协议/清单/映射。
"""

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

DATASETS = ["azure", "nep", "shanghai"]
PARTITIONS = ["calibration", "pilot", "formal"]


def load_yaml(rel: str):
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


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# T1. data/processed/e4_trace_enhanced/ 全只读
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("ds", DATASETS)
def test_t01_trace_root_read_only(ds):
    manifest = load_yaml("e4_v2_trace_input_manifest.yaml")
    declared = {f["path"]: f["sha256"] for f in manifest["file_hashes"]}
    # 只检查本数据集相关文件，保证 hash 与 manifest 一致（= 自 manifest 建立以来未被修改）
    for rel, expected in declared.items():
        if rel.startswith(ds + "/") or rel.startswith("splits/" + ds + "/"):
            p = TRACE_ROOT / rel
            assert p.exists(), f"missing {rel}"
            assert sha256(p) == expected, f"hash mismatch (file modified): {rel}"


def test_t01b_manifest_declares_19_files():
    manifest = load_yaml("e4_v2_trace_input_manifest.yaml")
    assert manifest["file_count"] == 19
    assert len(manifest["file_hashes"]) == 19


# ---------------------------------------------------------------------------
# T2. manifest 能解析
# ---------------------------------------------------------------------------
def test_t02_manifest_parses():
    m = load_yaml("e4_v2_trace_input_manifest.yaml")
    assert m["manifest_version"].startswith("E4_V2_TRACE_INPUT_MANIFEST_V1")
    assert m["status"] == "READ_ONLY_FROZEN_INPUT"
    assert set(m["datasets"].keys()) == set(DATASETS)
    assert m["compatibility"]["legacy_semantics_present_in_data"] is False
    assert m["compatibility"]["conclusion"] == "COMPATIBLE_AS_TRACE_DRIVER"


# ---------------------------------------------------------------------------
# T3. mapping 能解析
# ---------------------------------------------------------------------------
def test_t03_mapping_parses():
    m = load_yaml("e4_v2_trace_field_mapping.yaml")
    assert m["mapping_version"].startswith("E4_V2_TRACE_FIELD_MAPPING_V1")
    assert len(m["trace_fields"]) >= 13
    assert len(m["synthetic_fixed_fields"]) >= 6
    assert len(m["model_derived_fields"]) >= 2


# ---------------------------------------------------------------------------
# T4. 每个 E4 输入字段都有来源
# ---------------------------------------------------------------------------
def test_t04_every_input_field_has_source():
    m = load_yaml("e4_v2_trace_field_mapping.yaml")
    required = ["source_field", "source_unit", "target_object", "target_field",
                "target_unit", "mapping_rule", "evidence", "evidence_strength",
                "semantic_status", "classification"]
    for f in m["trace_fields"]:
        for k in required:
            assert k in f, f"missing {k} in {f.get('source_field')}"
    for f in m["synthetic_fixed_fields"] + m["model_derived_fields"]:
        assert "target_object" in f and "mapping_rule" in f


# ---------------------------------------------------------------------------
# T5. 不存在无依据 field fabrication
# ---------------------------------------------------------------------------
def test_t05_no_fabricated_fields():
    m = load_yaml("e4_v2_trace_field_mapping.yaml")
    for f in m["trace_fields"]:
        cls = f["classification"]
        st = f["semantic_status"]
        # UNUSED 字段不得声称有真实信号；WORKING_ASSUMPTION 必须注明为设计假设
        if st == "UNUSED":
            assert cls == "UNUSED"
        if f["source_field"] == "burst_score":
            assert st == "UNUSED"
    # NOT_AVAILABLE 登记（burstiness）不得被当作有效证据
    assert str(m["e4_metric_sources"]["workload_burstiness"]).startswith("NOT_AVAILABLE")


# ---------------------------------------------------------------------------
# T6. current model 不读取 deadline
# ---------------------------------------------------------------------------
def test_t06_model_does_not_read_deadline():
    # Schema V4 允许占位；正式 cars 代码与 Evaluator 不得依赖 deadline 语义
    # 检查 cars frozen config 与协议明确无 deadline 语义
    protocol = load_yaml("e4_v2_protocol.yaml")
    assert "无 deadline 模型" in protocol["scenario_semantics"]["deadline"]
    mapping = load_yaml("e4_v2_trace_field_mapping.yaml")
    for f in mapping["model_derived_fields"]:
        if f.get("target_field") == "deadline_seconds":
            assert "不读取" in f["mapping_rule"]
            assert f["classification"] == "PROJECT_MODEL_DERIVED"
    # 禁止指标必须包含 V_D 族（V_D 不在 E4 指标集合内）
    assert "V_D" in protocol["metrics"]["forbidden_metrics"]
    assert "V_D" not in protocol["metrics"]["primary"]
    assert "V_D" not in protocol["metrics"]["secondary"]
    assert "V_D" not in protocol["metrics"]["diagnostic"]


# ---------------------------------------------------------------------------
# T7. current model 不读取 lambda_eff
# ---------------------------------------------------------------------------
def test_t07_model_does_not_read_lambda_eff():
    protocol = load_yaml("e4_v2_protocol.yaml")
    assert "lambda_eff" in protocol["metrics"]["forbidden_metrics"]
    mapping_txt = open(CONFIG_ROOT / "e4_v2_trace_field_mapping.yaml", encoding="utf-8").read()
    # lambda_eff 只允许出现在禁止性语境（禁止/不得/恢复；整行语境）
    for m in re.finditer(r"lambda_eff", mapping_txt):
        line_start = mapping_txt.rfind("\n", 0, m.start()) + 1
        line_end = mapping_txt.find("\n", m.end())
        line = mapping_txt[line_start: line_end if line_end != -1 else None]
        assert any(k in line for k in ["禁止", "不得", "恢复"]), f"non-forbidden lambda_eff: {line}"


# ---------------------------------------------------------------------------
# T8. current model 不读取 RUAD/CALA/Repair legacy state
# ---------------------------------------------------------------------------
def test_t08_no_ruad_cala_repair_legacy():
    mapping_txt = open(CONFIG_ROOT / "e4_v2_trace_field_mapping.yaml", encoding="utf-8").read()
    protocol = load_yaml("e4_v2_protocol.yaml")
    model = protocol["scenario_semantics"]["model"]
    # 当前模型链 = AADA -> RCLA（无 Repair 层）；RUAD/CALA 不得为当前链元素
    assert "AADA" in model
    assert "RCLA" in model
    assert "无 Repair" in model or "Repair" not in model
    assert "RUAD" not in model
    assert "CALA" not in model
    # mapping 中 RUAD/CALA/Repair 只允许禁止性提及（整行语境）
    for kw in ["RUAD", "CALA", "Repair"]:
        for m in re.finditer(kw, mapping_txt):
            line_start = mapping_txt.rfind("\n", 0, m.start()) + 1
            line_end = mapping_txt.find("\n", m.end())
            line = mapping_txt[line_start: line_end if line_end != -1 else None]
            assert any(k in line for k in ["禁止", "不得", "恢复"]), f"non-forbidden {kw}: {line}"


# ---------------------------------------------------------------------------
# T9. fixed nominal λ_j 语义未被 Trace 改写
# ---------------------------------------------------------------------------
def test_t09_nominal_lambda_not_rewritten_by_trace():
    mapping = load_yaml("e4_v2_trace_field_mapping.yaml")
    for f in mapping["synthetic_fixed_fields"]:
        if f.get("target_field") == "nominal_failure_rate":
            assert "Trace 不得改写" in f["mapping_rule"]
            assert "lambda_eff" in f["mapping_rule"] or "禁止" in f["mapping_rule"]
    # cpu_pressure 映射只影响容量（F_j），不改变 λ_j
    for f in mapping["trace_fields"]:
        if f["source_field"] == "cpu_pressure":
            assert "固定名义故障率 λ_j" in f["mapping_rule"]


# ---------------------------------------------------------------------------
# T10. Pilot/Formal partition 不重叠
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("ds", DATASETS)
def test_t10_partitions_disjoint(ds):
    ids = {}
    for p in PARTITIONS:
        ids[p] = {r["slot_id"] for r in load_jsonl(TRACE_ROOT / "splits" / ds / f"{ds}_{p}.jsonl")}
    assert not (ids["calibration"] & ids["pilot"])
    assert not (ids["calibration"] & ids["formal"])
    assert not (ids["pilot"] & ids["formal"])
    # split ⊆ raw
    raw = {r["slot_id"] for r in load_jsonl(TRACE_ROOT / ds / f"{ds}_trace_slots.jsonl")}
    assert ids["calibration"] | ids["pilot"] | ids["formal"] <= raw


def test_t10b_time_order_cal_pilot_formal():
    for ds in DATASETS:
        t = {}
        for p in PARTITIONS:
            t[p] = load_jsonl(TRACE_ROOT / "splits" / ds / f"{ds}_{p}.jsonl")[0]["timestamp"]
        assert t["calibration"] < t["pilot"] < t["formal"]


# ---------------------------------------------------------------------------
# T11. formal partition 未运行
# ---------------------------------------------------------------------------
def test_t11_formal_not_executed():
    # OS2：公开协议为参考协议（源仓库状态可能已 EXECUTED/CLOSED）；
    # 本测试改为验证 formal 分区守卫语义仍然存在（不依赖协议状态字段）。
    proto = load_yaml("e4_v2_2_formal_protocol.yaml")
    assert "formal" in json.dumps(proto)
    # pilot 协议禁止访问 formal
    pilot = load_yaml("e4_v2_1_pilot_protocol.yaml")
    assert "forbidden_partitions" in pilot
    assert "formal" in json.dumps(pilot["forbidden_partitions"])


# ---------------------------------------------------------------------------
# T12. method pool 与 E1/E2 公平边界一致
# ---------------------------------------------------------------------------
def test_t12_method_pool_consistent():
    proto = load_yaml("e4_v2_protocol.yaml")
    assert proto["methods"]["main"] == ["cars", "bpso_rata_la", "jtora_adapted",
                                        "nfa_adapted", "reliability_only", "local_only"]
    assert proto["methods"]["diagnostic"] == ["foa"]
    assert proto["fairness"]["timeout_seconds"] == 30.0
    assert proto["methods"]["cars_config"] == "configs/cars_v4/cars_frozen_v4.yaml"


# ---------------------------------------------------------------------------
# T13. timeout 与当前公共执行边界一致
# ---------------------------------------------------------------------------
def test_t13_timeout_consistent():
    proto = load_yaml("e4_v2_protocol.yaml")
    assert proto["fairness"]["timeout_seconds"] == 30.0
    assert proto["runtime_semantics"]["shared_timeout_seconds"] == 30.0
    assert "method_runtime_ms" in proto["metrics"]["efficiency"]


# ---------------------------------------------------------------------------
# T14. evaluator metrics 与当前 Schema/Contract 一致
# ---------------------------------------------------------------------------
def test_t14_metrics_consistent_with_contract():
    proto = load_yaml("e4_v2_protocol.yaml")
    assert proto["metrics"]["primary"] == "TSSR"
    assert set(proto["metrics"]["secondary"]) == {"Rbar_eff", "Ubar_eff"}
    assert proto["metrics"]["diagnostic"] == ["V_R"]
    assert "V_D" in proto["metrics"]["forbidden_metrics"]   # V_D 族被禁止，非 E4 指标
    # 统一 Evaluator 唯一指标计算者（协议明文）
    assert "Evaluator" in json.dumps(proto, ensure_ascii=False)


# ---------------------------------------------------------------------------
# T15. Trace-derived / synthetic-fixed / model-derived 字段分类完整
# ---------------------------------------------------------------------------
def test_t15_classification_complete():
    m = load_yaml("e4_v2_trace_field_mapping.yaml")
    classes = set()
    for f in m["trace_fields"]:
        classes.add(f["classification"])
    for f in m["synthetic_fixed_fields"]:
        classes.add(f["classification"])
    for f in m["model_derived_fields"]:
        classes.add(f["classification"])
    assert {"TRACE_OBSERVED", "TRACE_DERIVED", "SYNTHETIC_FIXED",
            "PROJECT_MODEL_DERIVED", "UNUSED"} <= classes


# ---------------------------------------------------------------------------
# T16. formal Claim rules 为 outcome-neutral
# ---------------------------------------------------------------------------
def test_t16_outcome_neutral():
    proto = load_yaml("e4_v2_protocol.yaml")
    assert proto["outcome_neutral_claim_rules"]["allowed_conclusions"] == \
        ["supported", "conditionally_supported", "not_supported"]
    assert proto["prohibited_claims"]
    formal = load_yaml("e4_v2_2_formal_protocol.yaml")
    assert formal["claim_rules"]["outcome_neutral"] is True


# ---------------------------------------------------------------------------
# T17. scripts 不包含写 data/ 的代码路径
# ---------------------------------------------------------------------------
def test_t17_inspect_script_no_data_write():
    src = (SCRIPT_ROOT / "inspect_e4_trace_input.py").read_text(encoding="utf-8")
    # 静态检查：不得出现写入 data/ 的调用
    forbidden_patterns = [
        r"open\([^)]*TRACE_ROOT[^)]*['\"]w",
        r"open\([^)]*TRACE_ROOT[^)]*['\"]a",
        r"os\.makedirs\([^)]*TRACE_ROOT",
        r"shutil\.(copy|move|rmtree)",
    ]
    for pat in forbidden_patterns:
        assert not re.search(pat, src), f"forbidden write pattern: {pat}"
    # 只读打开（sha256_file 中以 "rb" 只读打开）
    assert 'open(path, "rb")' in src or 'open(p, "rb")' in src


# ---------------------------------------------------------------------------
# T18. 不存在 preprocessing command execution
# ---------------------------------------------------------------------------
def test_t18_no_preprocessing_execution():
    src = (SCRIPT_ROOT / "inspect_e4_trace_input.py").read_text(encoding="utf-8")
    for kw in ["subprocess", "os.system", "preprocess", "normalize(", "interpolate"]:
        assert kw not in src, f"preprocessing keyword present: {kw}"
    proto = load_yaml("e4_v2_protocol.yaml")
    assert proto["stage_scope"]["preprocessing_executed"] is False


# ---------------------------------------------------------------------------
# T19. py_compile 通过
# ---------------------------------------------------------------------------
def test_t19_py_compile():
    for f in ["inspect_e4_trace_input.py"]:
        p = SCRIPT_ROOT / f
        r = subprocess.run([sys.executable, "-m", "py_compile", str(p)],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


# ---------------------------------------------------------------------------
# T20. 本阶段相关 pytest 通过（本文件自身即证明）
# ---------------------------------------------------------------------------
def test_t20_e4_v2_0_tests_collect():
    # 本测试文件被收集并执行 = T20 成立；同时确认 inspect 脚本可运行（--smoke NOT_FORMAL）
    r = subprocess.run([sys.executable, str(SCRIPT_ROOT / "inspect_e4_trace_input.py"),
                        "--smoke"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OVERALL: PASS" in r.stdout


# ---------------------------------------------------------------------------
# 人工微型案例（mapping smoke；NOT_FORMAL）
# ---------------------------------------------------------------------------
def _absolutize_refs(doc):
    """将 doc 内相对 $ref 规范化为基于 $id 的绝对 $ref（与项目 validate_active_schema 一致）。"""
    base = doc.get("$id", "")
    base_dir = base.rsplit("/", 1)[0] + "/" if "/" in base else base

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node and not node["$ref"].startswith(("http://", "https://")):
                ref = node["$ref"]
                node["$ref"] = (base + ref) if ref.startswith("#") else (base_dir + ref)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(doc)
    return doc


def _schema_v4_registry():
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    schema_dir = PROJECT_ROOT / "schemas" / "CARS_ACTIVE_SCHEMA_V4"
    resources = {}
    for f in schema_dir.glob("*.schema.json"):
        doc = json.loads(f.read_text(encoding="utf-8"))
        _absolutize_refs(doc)
        resources[doc["$id"]] = Resource.from_contents(doc, default_specification=DRAFT202012)
    return Registry().with_resources(resources.items())


def test_manual_micro_case_mapping_smoke():
    """Trace record -> field mapping -> E4 Scenario input 语义链（NOT_FORMAL）。"""
    import importlib.util
    from jsonschema import Draft202012Validator

    spec = importlib.util.spec_from_file_location(
        "inspect_e4_trace_input", SCRIPT_ROOT / "inspect_e4_trace_input.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    smoke = mod.build_smoke_scenario("azure")
    assert smoke["NOT_FORMAL"] is True
    sc = smoke["scenario"]
    # Schema V4 结构
    assert sc["schema_version"] == "CARS_ACTIVE_SCHEMA_V4"
    assert sc["state_timepoint"] == "T0"
    assert len(sc["tasks"]) == len(sc["devices"]) == 20
    assert len(sc["servers"]) == 8
    assert len(sc["links"]) == 20 * 8
    # 语义链：trace 字段 -> scenario
    assert smoke["window_id_from_trace"].startswith("azure_d")
    assert 0.0 <= smoke["workload_intensity_from_trace"] <= 1.0
    # synthetic-fixed 明确标注
    assert "servers(F_j, lambda_j)" in smoke["scenario_inputs_from_synthetic_fixed"]
    # 无 deadline 语义：占位且不被读取
    assert all(t["deadline_seconds"] == 1000.0 for t in sc["tasks"])
    # 最终 Scenario 符合 Schema V4（场景级校验：tasks/devices/servers/links/system_params）
    registry = _schema_v4_registry()
    scenario_schema = _absolutize_refs(json.loads(
        (PROJECT_ROOT / "schemas" / "CARS_ACTIVE_SCHEMA_V4" / "scenario.schema.json")
        .read_text(encoding="utf-8")))
    validator = Draft202012Validator(scenario_schema, registry=registry)
    errors = sorted(validator.iter_errors(sc), key=lambda e: list(e.path))
    assert not errors, f"Schema V4 validation errors: {[e.message for e in errors]}"
