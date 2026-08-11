# -*- coding: utf-8 -*-
"""pytest 配置：将 src/ 与 scripts/ 加入 sys.path，并提供 Schema 校验 fixtures。

R2 测试需要：
- 导入 cars 包（src/）；
- 复用 R1B 验证器 validate_active_schema.py（scripts/）做 Schema 校验。
"""

import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT = os.path.dirname(_HERE)
_SRC = os.path.join(_HERE, "..", "src")
_SCRIPTS = os.path.join(_PROJECT, "scripts")
for _p in (_SRC, _SCRIPTS):
    _abs = os.path.abspath(_p)
    if _abs not in sys.path:
        sys.path.insert(0, _abs)


# ---------------------------------------------------------------------------
# Schema 版本化 fixtures
#
# CR-CARS-PROMOTION-E1：Active Schema 升级为 V4（当前正式）。
# - schema_docs / schema_registry / schema_errors：V1（历史）。
# - schema_docs_v2 / schema_registry_v2 / schema_errors_v2：V2（历史）——
#   供历史 CR-R4-1 等测试使用。
# - schema_docs_v4 / schema_registry_v4 / schema_errors_v4：V4（当前正式）——
#   供正式 CARS/Runner 归一化决策校验使用。
# ---------------------------------------------------------------------------


def _load_schema_docs(version):
    """按版本加载 Schema 文档（复用 validate_active_schema 的绝对化逻辑）。"""
    import validate_active_schema as vas

    old = (vas.SCHEMA_DIR, vas.SCHEMA_VERSION, vas.SCHEMA_VERSION_NAME)
    try:
        vas.SCHEMA_VERSION_NAME = version
        vas.SCHEMA_VERSION = version
        vas.SCHEMA_DIR = os.path.join(vas.PROJECT_ROOT, "schemas", version)
        return vas.load_schema_docs()
    finally:
        vas.SCHEMA_DIR, vas.SCHEMA_VERSION, vas.SCHEMA_VERSION_NAME = old


@pytest.fixture(scope="session")
def schema_docs():
    return _load_schema_docs("CARS_ACTIVE_SCHEMA_V1")


@pytest.fixture(scope="session")
def schema_registry(schema_docs):
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    resources = {
        doc["$id"]: Resource.from_contents(doc, default_specification=DRAFT202012)
        for doc in schema_docs.values()
    }
    return Registry().with_resources(resources.items())


@pytest.fixture(scope="session")
def schema_docs_v2():
    return _load_schema_docs("CARS_ACTIVE_SCHEMA_V2")


@pytest.fixture(scope="session")
def schema_registry_v2(schema_docs_v2):
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    resources = {
        doc["$id"]: Resource.from_contents(doc, default_specification=DRAFT202012)
        for doc in schema_docs_v2.values()
    }
    return Registry().with_resources(resources.items())


@pytest.fixture(scope="session")
def schema_errors():
    import validate_active_schema as vas

    def _check(payload, target, registry, docs):
        return vas.validate_instance(payload, target, registry, docs)

    return _check


@pytest.fixture(scope="session")
def schema_errors_v2():
    import validate_active_schema as vas

    def _check(payload, target, registry, docs):
        return vas.validate_instance(payload, target, registry, docs)

    return _check


@pytest.fixture(scope="session")
def schema_docs_v4():
    return _load_schema_docs("CARS_ACTIVE_SCHEMA_V4")


@pytest.fixture(scope="session")
def schema_registry_v4(schema_docs_v4):
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    resources = {
        doc["$id"]: Resource.from_contents(doc, default_specification=DRAFT202012)
        for doc in schema_docs_v4.values()
    }
    return Registry().with_resources(resources.items())


@pytest.fixture(scope="session")
def schema_errors_v4():
    import validate_active_schema as vas

    def _check(payload, target, registry, docs):
        return vas.validate_instance(payload, target, registry, docs)

    return _check


# ---------------------------------------------------------------------------
# OS2: external-artifact dependent tests
#
# The public repo does NOT bundle formal results / trace data / contracts /
# manuscript. Tests that validate those artifacts are skipped in a clean clone
# (they become active once the corresponding reproduce script under
# scripts/reproduce/ has been executed and produced the artifact in results/).
# This is a test-packaging decision (OS2 contract §6); no algorithm or metric
# semantics are changed.
# ---------------------------------------------------------------------------

_PROJECT_ROOT = os.path.dirname(_HERE)


def _artifact(rel: str) -> str:
    return os.path.join(_PROJECT_ROOT, rel.replace("/", os.sep))


EXTERNAL_MODULE_DEPS = {
    "tests/e0_v2/test_e0_v2_2_formal.py": ["results/e0_v2/e0_v2_2_formal/formal_summary.json"],
    "tests/e3_v2/test_e3_v2_2_formal.py": ["results/e3_v2/e3_v2_2_formal/formal_meta.json"],
    "tests/e4_v2/test_e4_v2_2_formal.py": ["results/e4_v2/e4_v2_2_formal/formal_window_manifest.json"],
    "tests/e4_v2/test_e4_v2_statistical_reanalysis.py": ["results/e4_v2/e4_v2_statistical_reanalysis/window_level_paired_effects.csv"],
    "tests/e4_exact/test_e4_exact_2_pilot_and_freeze.py": ["results/e4_exact/e4_exact_2_pilot/formal_scale_selection.json"],
    "tests/e4_exact/test_e4_exact_0_contract.py": ["reports/contracts/E4_EXACT_ORACLE_CONTRACT_V1.md"],
}

_DATA = "data/processed/e4_trace_enhanced/"
_RES_E4V2_PILOT = "results/e4_v2/e4_v2_1_pilot/trace_regime_diagnostics.csv"
_SENTINEL_CONTRACT = "reports/contracts/CARS_EXECUTABLE_THEORY_CONTRACT_V4.md"

EXTERNAL_TEST_DEPS = {
    # e1_v2: artifacts produced by reproduce scripts
    "tests/e1_v2/test_e1_v2_contract.py::test_promotion_equivalence_artifact_exists": ["results/e1_v2/promotion_equivalence.json"],
    "tests/e1_v2/test_e1_v2_environment_calibration.py::test_protected_objects_unchanged": ["results/e1_v2/e1_v2_0_calibration/pre_state_hashes.json"],
    # e4_exact oracle: source-repo integrity guards (not applicable to the public copy)
    "tests/e4_exact/test_e4_exact_1_oracle.py::test_t37_cars_methods_unchanged": [_SENTINEL_CONTRACT],
    "tests/e4_exact/test_e4_exact_1_oracle.py::test_t38_evaluator_unchanged": [_SENTINEL_CONTRACT],
    "tests/e4_exact/test_e4_exact_1_oracle.py::test_t39_contract_v4_unchanged": [_SENTINEL_CONTRACT],
    "tests/e4_exact/test_e4_exact_1_oracle.py::test_t40_schema_v4_unchanged": [_SENTINEL_CONTRACT],
    "tests/e4_exact/test_e4_exact_1_oracle.py::test_t42_e4_v2_assets_unchanged": [_SENTINEL_CONTRACT],
    "tests/e4_exact/test_e4_exact_1_oracle.py::test_t43_data_unchanged": [_SENTINEL_CONTRACT],
    # e4_v2_0_contract: trace data not bundled
    "tests/e4_v2/test_e4_v2_0_contract.py::test_t01_trace_root_read_only": [_DATA],
    "tests/e4_v2/test_e4_v2_0_contract.py::test_t10_partitions_disjoint": [_DATA],
    "tests/e4_v2/test_e4_v2_0_contract.py::test_t10b_time_order_cal_pilot_formal": [_DATA],
    "tests/e4_v2/test_e4_v2_0_contract.py::test_t20_e4_v2_0_tests_collect": [_DATA],
    "tests/e4_v2/test_e4_v2_0_contract.py::test_manual_micro_case_mapping_smoke": [_DATA],
    # e4_v2_1_pilot: trace data / pilot results not bundled
    "tests/e4_v2/test_e4_v2_1_pilot.py::test_t01b_formal_access_guard_behavior": [_DATA],
    "tests/e4_v2/test_e4_v2_1_pilot.py::test_t02_partitions_disjoint": [_DATA],
    "tests/e4_v2/test_e4_v2_1_pilot.py::test_t03_no_data_write": [_DATA],
    "tests/e4_v2/test_e4_v2_1_pilot.py::test_t11_layer_a_no_method_result": [_RES_E4V2_PILOT],
    "tests/e4_v2/test_e4_v2_1_pilot.py::test_t12_no_method_dependent_diagnostics": [_RES_E4V2_PILOT],
    "tests/e4_v2/test_e4_v2_1_pilot.py::test_t13_candidates_preserved": [_RES_E4V2_PILOT],
    "tests/e4_v2/test_e4_v2_1_pilot.py::test_t14_selected_windows_reproducible": [_RES_E4V2_PILOT],
    "tests/e4_v2/test_e4_v2_1_pilot.py::test_t16_same_scenario_across_methods": [_RES_E4V2_PILOT],
    "tests/e4_v2/test_e4_v2_1_pilot.py::test_t17_timeout_30s": [_RES_E4V2_PILOT],
    "tests/e4_v2/test_e4_v2_1_pilot.py::test_t18_errors_not_deleted": [_RES_E4V2_PILOT],
    "tests/e4_v2/test_e4_v2_1_pilot.py::test_t19_not_formal": [_RES_E4V2_PILOT],
    "tests/e4_v2/test_e4_v2_1_pilot.py::test_t20_formal_not_executed": [_RES_E4V2_PILOT],
    "tests/e4_v2/test_e4_v2_1_pilot.py::test_t22_e4_v2_targeted": [_RES_E4V2_PILOT],
    "tests/e4_v2/test_e4_v2_1_pilot.py::test_manual_micro_case_window_scenario_schema": [_RES_E4V2_PILOT],
}


def pytest_collection_modifyitems(config, items):
    for item in items:
        nodeid = item.nodeid.replace("\\", "/")
        deps = EXTERNAL_TEST_DEPS.get(nodeid.split("[")[0])
        if deps is None:
            deps = EXTERNAL_MODULE_DEPS.get(nodeid.split("::")[0])
        if not deps:
            continue
        missing = [d for d in deps if not os.path.exists(_artifact(d))]
        if missing:
            item.add_marker(pytest.mark.skip(
                reason="requires non-bundled artifact(s): %s (formal results / trace data / "
                       "contracts / manuscript are not distributed with this public repo; "
                       "run the corresponding reproduce script under scripts/reproduce/ to "
                       "generate results/, or supply the artifact)" % ", ".join(missing)))
