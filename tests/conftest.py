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
