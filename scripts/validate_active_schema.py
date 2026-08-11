#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CARS Active Schema V1 验证器（R1B 阶段）

职责（R1B 提示词 Step 4 冻结测试清单）：
  1. 所有 JSON/YAML 可解析
  2. 所有 Schema 通过 Draft 2020-12 元 Schema 校验
  3. 所有 $ref 可解析
  4. 所有 $id 唯一
  5. schema_manifest.yaml 与实际文件一致
  6. required / type / unit(x-unit) / version 完整
  7. 有效微型案例通过（JSON Schema 校验 + 跨字段不变量）
  8. 全部冻结非法案例被拒绝
  9. legacy_forbidden_fields 扫描（lambda_eff / gnn_candidate / teacher_label /
     oracle_edge / checkpoint / history_state / load_amplified_failure_rate）
 10. 状态时点检查（RUAD 输入不含 T2-T4 未来信息）
 11. 确定性：同一输入重复验证结果一致

用法：
  python scripts/validate_active_schema.py            # 全量校验
  python scripts/validate_active_schema.py --quiet    # 仅输出结论

本脚本不实现任何公式/算法/实验（R1B 范围边界）；跨字段不变量仅覆盖可由
Schema + 结构层表达的不变量（C1-C3、C5 的 a=>f 部分、C6、维度、ID 唯一、
引用存在、alpha+beta=1、eta 权重和=1）。依赖公式计算的语义（e_phy、T_i、
R_i、z_i、rho_tilde 等）留待 R2 Evaluator 契约。
"""

import json
import os
import sys

import yaml

try:
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012
except ImportError as exc:  # pragma: no cover
    sys.stderr.write(
        "ERROR: missing dependency 'jsonschema>=4.18' (Draft 2020-12 support). "
        "Install with: pip install jsonschema\n"
    )
    raise SystemExit(2)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)

# 支持版本：V3（历史，CR-RUAD-S1）/ V2（历史）/ V1（历史，均仍可独立验证）；
# V4（当前正式，CR-CARS-PROMOTION-E1：CARS=AADA→RCLA）。默认 V4。
SCHEMA_VERSION_NAME = "CARS_ACTIVE_SCHEMA_V4"
SCHEMA_DIR = os.path.join(PROJECT_ROOT, "schemas", SCHEMA_VERSION_NAME)
EXAMPLES_DIR = os.path.join(SCHEMA_DIR, "examples")
MANIFEST_PATH = os.path.join(SCHEMA_DIR, "schema_manifest.yaml")
VALID_CASE_PATH = os.path.join(EXAMPLES_DIR, "tiny_valid_case.json")
INVALID_CASES_PATH = os.path.join(EXAMPLES_DIR, "tiny_invalid_cases.json")

SCHEMA_VERSION = SCHEMA_VERSION_NAME
FLOAT_TOL = 1e-9

# 明确排除的旧语义字段（AGENTS.md / Contract Part 0.2 / 提示词 3.4）
BASE_LEGACY_FORBIDDEN_FIELDS = [
    "lambda_eff",
    "load_amplified_failure_rate",
    "gnn_candidate",
    "teacher_label",
    "oracle_edge",
    "checkpoint",
    "history_state",
]

# CR-R4-1：V2 正式 CARS 配置额外禁止旧三压力字段（eta_rho/eta_Q/eta_Z/s_Q/s_Z）
# 及旧派生状态字段（rho_tilde / f_tilde_req）。旧配置不得静默兼容。
V2_LEGACY_FORBIDDEN_FIELDS = [
    "eta_rho",
    "eta_Q",
    "eta_Z",
    "s_Q",
    "s_Z",
    "rho_tilde",
    "f_tilde_req",
]

# CR-RUAD-S1：V3 正式 CARS 配置额外禁止 ruad_gamma（RUAD 无可调混合权重；
# Q/Z 状态与增量代价完全由任务/服务器基础参数决定）。旧配置不得静默兼容。
V3_LEGACY_FORBIDDEN_FIELDS = [
    "ruad_gamma",
]

# CR-CARS-PROMOTION-E1：V4 正式 CARS 配置额外禁止 CALA/Repair 参数
# （cala_weights/repair_budget/repair_tolerances/kappa_R/kappa_D）——CARS=AADA→RCLA，
# 无 CALA/Repair 层（Contract V4；正文 V-A.4 Table V-1/V-C.4）。旧配置不得静默兼容。
V4_LEGACY_FORBIDDEN_FIELDS = [
    "cala_weights",
    "repair_budget",
    "repair_tolerances",
    "kappa_R",
    "kappa_D",
]

# 默认（V4 当前正式）：BASE + V2 旧 RUAD 字段 + V3 ruad_gamma + V4 CALA/Repair 参数；
# main() 按 --schema-version 调整
LEGACY_FORBIDDEN_FIELDS = (
    list(BASE_LEGACY_FORBIDDEN_FIELDS)
    + list(V2_LEGACY_FORBIDDEN_FIELDS)
    + list(V3_LEGACY_FORBIDDEN_FIELDS)
    + list(V4_LEGACY_FORBIDDEN_FIELDS)
)

# T2-T4 产物字段：禁止出现在 T0 决策前状态（Contract Part 5.2, Assumption 2）
FUTURE_TIMEPOINT_FIELDS = [
    "offloading_decision",
    "assignment_matrix",
    "resource_allocation",
    "final_plan",
    "repair_diagnostics",
    "module_statuses",
    "task_results",
    "system_metrics",
]

# 决策类对象：包含完整 X/A/F（或其中部分）
DECISION_OBJECTS = {
    "schedule_decision": {"has_x": True, "has_a": True, "has_f": True, "path": ""},
    "ruad_output": {"has_x": True, "has_a": True, "has_f": False, "path": ""},
    "cala_output": {"has_x": False, "has_a": False, "has_f": True, "path": ""},
    "repair_output": {"has_x": True, "has_a": True, "has_f": True, "path": "final_plan"},
    "aada_output": {"has_x": True, "has_a": True, "has_f": False, "path": ""},
    "rcla_output": {"has_x": False, "has_a": False, "has_f": True, "path": ""},
    "method_result": {"has_x": True, "has_a": True, "has_f": True, "path": "decision"},
    "evaluator_input": {"has_x": True, "has_a": True, "has_f": True, "path": "decision"},
}


# ---------------------------------------------------------------------------
# 文件加载
# ---------------------------------------------------------------------------

def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def list_schema_files():
    return sorted(
        name
        for name in os.listdir(SCHEMA_DIR)
        if name.endswith(".schema.json") and name != "common.schema.json"
    ) + ["common.schema.json"]  # common 也参与校验，但保持列表稳定


def absolutize_refs(doc):
    """把 doc 内所有相对 $ref 规范化为基于 doc['$id'] 的绝对 $ref。

    Draft 2020-12 中相对 $ref 相对于引用者的 base URI（即各 Schema 的 $id）
    解析。运行时统一绝对化后，registry 与 validator 均可按 $id 精确解析，
    避免依赖 validator 内部 base-URI 处理（jsonschema 4.24 / referencing 兼容性）。
    """
    base = doc.get("$id", "")
    if "/" in base:
        base_dir = base.rsplit("/", 1)[0] + "/"
    else:
        base_dir = base

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node and not node["$ref"].startswith(
                ("http://", "https://")
            ):
                ref = node["$ref"]
                if ref.startswith("#"):
                    # 同文档片段引用：基于完整 $id（无片段）
                    node["$ref"] = base + ref
                else:
                    # 同目录文件引用：基于 $id 所在目录
                    node["$ref"] = base_dir + ref
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(doc)
    return doc


def load_schema_docs():
    """加载全部 Schema 并绝对化 $ref。返回 {文件名: doc}。"""
    docs = {}
    for name in list_schema_files():
        doc = load_json(os.path.join(SCHEMA_DIR, name))
        absolutize_refs(doc)
        docs[name] = doc
    return docs


# ---------------------------------------------------------------------------
# Schema 结构检查
# ---------------------------------------------------------------------------

def check_meta_schema(doc):
    """Draft 2020-12 元 Schema 校验。check_schema 对无效 schema 抛异常，对有效返回 None。"""
    try:
        Draft202012Validator.check_schema(doc)
        return []
    except Exception as exc:  # SchemaError / best_match 等
        return [str(exc)]


def collect_refs(node, out):
    if isinstance(node, dict):
        if "$ref" in node:
            out.append(node["$ref"])
        for key, val in node.items():
            if key != "$ref":
                collect_refs(val, out)
    elif isinstance(node, list):
        for item in node:
            collect_refs(item, out)


def check_refs_resolvable(docs):
    """构建 referencing Registry 并按每个 $id 解析全部 $ref。返回错误列表。"""
    resources = {}
    for doc in docs:
        resources[doc["$id"]] = Resource.from_contents(
            doc, default_specification=DRAFT202012
        )
    registry = Registry().with_resources(resources.items())

    errors = []
    for doc in docs:
        refs = []
        collect_refs(doc, refs)
        resource = Resource.from_contents(doc, default_specification=DRAFT202012)
        resolver = registry.resolver_with_root(resource)
        for ref in refs:
            try:
                resolver.lookup(ref)
            except Exception as exc:  # NoSuchResource / Unresolvable
                errors.append(
                    "%s: unresolvable $ref '%s' (%s)" % (doc["$id"], ref, exc)
                )
    return errors


def check_ids_unique(docs):
    ids = [doc["$id"] for doc in docs]
    seen = set()
    dup = []
    for sid in ids:
        if sid in seen:
            dup.append(sid)
        seen.add(sid)
    return ["duplicate $id: %s" % sid for sid in dup]


def check_version(docs):
    errors = []
    for doc in docs:
        ver = doc.get("version")
        if ver != SCHEMA_VERSION:
            errors.append(
                "%s: version=%r, expected %r" % (doc["$id"], ver, SCHEMA_VERSION)
            )
    return errors


def check_field_units(schema_doc):
    """每个叶子字段必须具有 x-unit 或 description（enum/const/$ref 豁免）。

    检查范围：properties 下的每个字段，以及 $defs 顶层条目本身
    （如 common 的数值域定义、被 $ref 引用的命名定义）。不深入
    oneOf/anyOf/allOf 组合关键字内部（其内为内联约束而非命名字段）。
    返回违规列表。
    """
    violations = []

    def check_prop(prop, path):
        if not isinstance(prop, dict):
            return
        t = prop.get("type")
        has_annot = (
            "x-unit" in prop or "description" in prop or "$ref" in prop
            or "enum" in prop or "const" in prop
        )
        if t in ("number", "integer"):
            if not has_annot:
                violations.append("%s: numeric field missing x-unit/description" % path)
        elif t == "array":
            if not has_annot and "items" in prop:
                violations.append("%s: array field missing x-unit/description" % path)
        elif t == "string":
            if not has_annot:
                violations.append("%s: string field missing description/enum" % path)

    def walk(node, path):
        if not isinstance(node, dict):
            return
        props = node.get("properties")
        if isinstance(props, dict):
            for name, prop in props.items():
                p = "%s.%s" % (path, name)
                check_prop(prop, p)
                walk(prop, p)
        defs = node.get("$defs")
        if isinstance(defs, dict):
            for name, d in defs.items():
                p = "%s.$defs.%s" % (path, name)
                check_prop(d, p)
                walk(d, p)
        # 深入 items 定义（数组元素为命名结构时）
        items = node.get("items")
        if isinstance(items, dict) and "$ref" not in items:
            walk(items, "%s.items" % path)

    walk(schema_doc, schema_doc.get("$id", "schema"))
    return violations


def check_manifest(manifest, actual_files):
    """manifest 与实际 schema 文件双向一致。返回错误列表。"""
    errors = []
    manifest_files = [
        entry["file_path"].replace("\\", "/") for entry in manifest.get("schemas", [])
    ]
    actual_full = [
        os.path.join("schemas", SCHEMA_VERSION_NAME, f).replace("\\", "/")
        for f in actual_files
    ]
    missing = [f for f in manifest_files if f not in actual_full]
    unlisted = [f for f in actual_full if f not in manifest_files]
    if missing:
        errors.append("manifest lists files not present: %s" % missing)
    if unlisted:
        errors.append("schema files not listed in manifest: %s" % unlisted)
    if len(manifest_files) != len(set(manifest_files)):
        errors.append("manifest has duplicate file_path entries")
    return errors


# ---------------------------------------------------------------------------
# 跨字段不变量（validate_active_schema 自定义验证器部分）
# ---------------------------------------------------------------------------

def _ids(scenario, kind, id_key):
    return [item.get(id_key) for item in scenario.get(kind, [])]


def check_scenario_invariants(scenario):
    violations = []
    tasks = scenario.get("tasks", [])
    devices = scenario.get("devices", [])
    servers = scenario.get("servers", [])
    links = scenario.get("links", [])

    # ID 唯一
    for kind, key in (("tasks", "task_id"), ("devices", "device_id"),
                      ("servers", "server_id"), ("links", "link_id")):
        ids = _ids(scenario, kind, key)
        if len(ids) != len(set(ids)):
            violations.append("%s ID not unique" % kind)

    # N 一致性：len(tasks) == len(devices)
    if len(tasks) != len(devices):
        violations.append(
            "len(tasks)=%d != len(devices)=%d (must both equal N)"
            % (len(tasks), len(devices))
        )

    # 引用存在
    device_ids = set(_ids(scenario, "devices", "device_id"))
    server_ids = set(_ids(scenario, "servers", "server_id"))
    for t in tasks:
        if t.get("device_id") not in device_ids:
            violations.append(
                "task %s references unknown device %s"
                % (t.get("task_id"), t.get("device_id"))
            )
    for l in links:
        if l.get("source_device_id") not in device_ids:
            violations.append(
                "link %s references unknown source device %s"
                % (l.get("link_id"), l.get("source_device_id"))
            )
        if l.get("target_server_id") not in server_ids:
            violations.append(
                "link %s references unknown target server %s"
                % (l.get("link_id"), l.get("target_server_id"))
            )

    # alpha_i + beta_i = 1
    for t in tasks:
        alpha = t.get("delay_weight")
        beta = t.get("energy_weight")
        if alpha is not None and beta is not None:
            if abs(alpha + beta - 1.0) > FLOAT_TOL:
                violations.append(
                    "task %s: alpha+beta=%.6f != 1" % (t.get("task_id"), alpha + beta)
                )

    params = scenario.get("system_params", {})
    if SCHEMA_VERSION == "CARS_ACTIVE_SCHEMA_V4":
        # CR-CARS-PROMOTION-E1：V4 无 CALA/Repair；SystemParams 不得含 cala/repair 参数
        # （CARS=AADA→RCLA，无修复层；Contract V4 §9）
        for k in ("cala_weights", "repair_budget", "repair_tolerances", "kappa_R", "kappa_D"):
            if k in params:
                violations.append("system_params.%s is forbidden in V4 (CARS=AADA→RCLA)" % k)
    elif SCHEMA_VERSION == "CARS_ACTIVE_SCHEMA_V3":
        # CR-RUAD-S1：V3 无 gamma；SystemParams 不得含 ruad_gamma
        if "ruad_gamma" in params:
            violations.append("system_params.ruad_gamma is forbidden in V3 (CR-RUAD)")
    elif SCHEMA_VERSION == "CARS_ACTIVE_SCHEMA_V2":
        # CR-R4-1：V2 单参数 gamma in [0,1]
        gamma = params.get("ruad_gamma")
        if gamma is not None:
            if not (0.0 <= float(gamma) <= 1.0):
                violations.append(
                    "system_params.ruad_gamma=%.6f not in [0,1]" % float(gamma)
                )
    else:
        # V1 历史：eta_rho + eta_Q + eta_Z = 1
        weights = params.get("ruad_pressure_weights", {})
        if weights:
            total = sum(
                weights.get(k, 0.0) for k in ("eta_rho", "eta_Q", "eta_Z")
            )
            if abs(total - 1.0) > FLOAT_TOL:
                violations.append(
                    "system_params.ruad_pressure_weights sum=%.6f != 1" % total
                )
    return violations


def check_decision_invariants(scenario, decision):
    """对含 X/A/F 的决策对象运行结构层不变量（C3/C5/C6/维度/结构 C4）。

    X/A/F 各自可选：存在哪些字段就检查哪些（RUAD 输出只有 X/A，
    CALA 输出只有 F，完整决策有 X/A/F）。字段缺失本身由 JSON Schema
    required 负责捕获，此处只做存在字段的结构不变量。
    """
    violations = []
    n = len(scenario.get("tasks", []))
    m = len(scenario.get("servers", []))
    x = decision.get("offloading_decision")
    a = decision.get("assignment_matrix")
    f = decision.get("resource_allocation")
    has_xa = isinstance(x, list) and isinstance(a, list) and len(x) > 0
    has_f = isinstance(f, list) and len(f) > 0

    if has_xa:
        if len(x) != n:
            violations.append("len(X)=%d != N=%d" % (len(x), n))
        if len(a) != n or any(len(row) != m for row in a):
            violations.append("A dimension wrong (expected %dx%d)" % (n, m))
    if has_f:
        if len(f) != n or any(len(row) != m for row in f):
            violations.append("F dimension wrong (expected %dx%d)" % (n, m))

    # 行级检查要求 X、A、F 维度都正确
    dim_ok = (
        has_xa and has_f
        and len(x) == n and len(a) == n and len(f) == n
        and all(len(row) == m for row in a)
        and all(len(row) == m for row in f)
    )
    if not dim_ok:
        # 若 X/A 存在且维度正确，仍检查 C3 的 sum_j A[i][j] == x_i
        if has_xa and len(x) == n and len(a) == n and all(len(row) == m for row in a):
            for i in range(n):
                if sum(a[i]) != x[i]:
                    violations.append(
                        "C3 violation: sum_j A[%d][j]=%d != X[%d]=%d"
                        % (i, sum(a[i]), i, x[i])
                    )
        return violations

    f_j = [s.get("capacity_cycles_per_sec", 0.0) for s in scenario.get("servers", [])]

    # C3: sum_j A[i][j] == X[i]
    for i in range(n):
        if sum(a[i]) != x[i]:
            violations.append(
                "C3 violation: sum_j A[%d][j]=%d != X[%d]=%d"
                % (i, sum(a[i]), i, x[i])
            )
        # C5 lower: A==0 => F==0（含本地任务 f=0）
        for j in range(m):
            if a[i][j] == 0 and abs(f[i][j]) > FLOAT_TOL:
                violations.append(
                    "C5 violation: A[%d][%d]=0 but F[%d][%d]=%g"
                    % (i, j, i, j, f[i][j])
                )
            # C5 upper: 0 <= F <= A*F_j
            if f[i][j] < -FLOAT_TOL:
                violations.append("F[%d][%d]=%g < 0" % (i, j, f[i][j]))
            if f[i][j] > a[i][j] * f_j[j] + FLOAT_TOL:
                violations.append(
                    "C5 violation: F[%d][%d]=%g > A*F_j=%g"
                    % (i, j, f[i][j], a[i][j] * f_j[j])
                )

    # C6: sum_i F[i][j] <= F_j
    for j in range(m):
        total = sum(f[i][j] for i in range(n))
        if total > f_j[j] + FLOAT_TOL:
            violations.append(
                "C6 violation: sum_i F[i][%d]=%g > F_j=%g" % (j, total, f_j[j])
            )

    # 结构层 C4: A[i][j]==1 => (device_of_task_i, server_j) 存在 WirelessLink
    # 决策行顺序与 scenario.tasks 顺序一致（R1B_ACTIVE_SCHEMA_FREEZE.md 已约定）
    device_of = {
        t.get("task_id"): t.get("device_id")
        for t in scenario.get("tasks", [])
    }
    task_ids = [t.get("task_id") for t in scenario.get("tasks", [])]
    server_ids = [s.get("server_id") for s in scenario.get("servers", [])]
    link_pairs = {
        (l.get("source_device_id"), l.get("target_server_id"))
        for l in scenario.get("links", [])
    }
    for i in range(n):
        for j in range(m):
            if a[i][j] == 1:
                dev = device_of.get(task_ids[i])
                srv = server_ids[j]
                if (dev, srv) not in link_pairs:
                    violations.append(
                        "C4 (structural): A[%d][%d]=1 but no WirelessLink %s->%s"
                        % (i, j, dev, srv)
                    )
    return violations


def check_ruad_dynamic_states(scenario, payload):
    """模块输出动态状态：维度 M 且非负。

    CR-CARS-PROMOTION-E1：V4 必检 AADA 输出 final_resource_competition（Q_j）与
    final_floor_reservation（G_j=Σell_R）。
    CR-RUAD-S1：V3 必检 final_resource_competition（Q_j）与 final_fragility_load
    （Z_j=Σu_i）；final_demand_pressure（rho_dem）为诊断量，仅在存在时检查。
    """
    violations = []
    m = len(scenario.get("servers", []))
    if SCHEMA_VERSION == "CARS_ACTIVE_SCHEMA_V4":
        keys = ["final_resource_competition", "final_floor_reservation"]
    elif SCHEMA_VERSION == "CARS_ACTIVE_SCHEMA_V3":
        keys = ["final_resource_competition", "final_fragility_load"]
        if "final_demand_pressure" in payload:
            keys.append("final_demand_pressure")
    else:
        keys = ["final_demand_pressure", "final_fragility_load"]
    if SCHEMA_VERSION == "CARS_ACTIVE_SCHEMA_V1":
        keys.append("final_tilde_demand_pressure")
    for key in keys:
        arr = payload.get(key, [])
        if len(arr) != m:
            violations.append("%s dimension=%d != M=%d" % (key, len(arr), m))
        elif any(v < -FLOAT_TOL for v in arr):
            violations.append("%s contains negative value" % key)
    return violations


def check_timepoint(payload):
    """T0 决策前状态不得包含 T2-T4 未来信息字段。返回发现的字段。"""
    found = []

    def walk(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in FUTURE_TIMEPOINT_FIELDS:
                    found.append("%s.%s" % (path, k))
                walk(v, "%s.%s" % (path, k))
        elif isinstance(node, list):
            for idx, v in enumerate(node):
                walk(v, "%s[%d]" % (path, idx))

    walk(payload, "payload")
    return found


def scan_forbidden_fields(obj, path=""):
    """递归扫描 legacy_forbidden_fields。返回 (field_path, key) 列表。"""
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in LEGACY_FORBIDDEN_FIELDS:
                found.append("%s.%s" % (path, k))
            found.extend(scan_forbidden_fields(v, "%s.%s" % (path, k)))
    elif isinstance(obj, list):
        for idx, v in enumerate(obj):
            found.extend(scan_forbidden_fields(v, "%s[%d]" % (path, idx)))
    return found


# ---------------------------------------------------------------------------
# 实例校验
# ---------------------------------------------------------------------------

def resolve_schema_ref(schema_ref, docs_by_file):
    """解析 'file.schema.json#/pointer' 到目标 subschema。"""
    fname, _, pointer = schema_ref.partition("#")
    if fname not in docs_by_file:
        raise ValueError("unknown schema file in target_schema: %s" % fname)
    target = docs_by_file[fname]
    if pointer:
        for part in pointer.lstrip("/").split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            target = target[part]
    return target


def validate_instance(instance, schema_ref, registry, docs_by_file):
    """JSON Schema 校验实例。返回错误消息列表。

    $ref 在加载时已绝对化（见 absolutize_refs），registry 按 $id 精确解析，
    因此无需依赖 validator 的 base-URI 处理。
    """
    target = resolve_schema_ref(schema_ref, docs_by_file)
    validator = Draft202012Validator(target, registry=registry)
    return [
        list(e.path) and "%s: %s" % ("/".join(str(p) for p in e.path), e.message)
        or e.message
        for e in sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    ]


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main():
    quiet = "--quiet" in sys.argv
    global SCHEMA_VERSION, SCHEMA_DIR, EXAMPLES_DIR, MANIFEST_PATH
    global VALID_CASE_PATH, INVALID_CASES_PATH, SCHEMA_VERSION_NAME
    global LEGACY_FORBIDDEN_FIELDS
    errors = []

    # CR-CARS-PROMOTION-E1：版本选择（默认 V4 当前正式；V3/V2/V1 历史独立验证）
    version = "CARS_ACTIVE_SCHEMA_V4"
    if "--schema-version" in sys.argv:
        idx = sys.argv.index("--schema-version")
        if idx + 1 >= len(sys.argv):
            errors.append("--schema-version requires a value (V1|V2|V3|V4)")
        else:
            version = sys.argv[idx + 1]
    if version not in ("CARS_ACTIVE_SCHEMA_V1", "CARS_ACTIVE_SCHEMA_V2", "CARS_ACTIVE_SCHEMA_V3", "CARS_ACTIVE_SCHEMA_V4"):
        errors.append("unsupported schema version %r (V1|V2|V3|V4)" % version)
        for msg in errors:
            sys.stderr.write("  [FAIL] %s\n" % msg)
        return 1
    SCHEMA_VERSION_NAME = version
    SCHEMA_VERSION = version
    SCHEMA_DIR = os.path.join(PROJECT_ROOT, "schemas", version)
    EXAMPLES_DIR = os.path.join(SCHEMA_DIR, "examples")
    MANIFEST_PATH = os.path.join(SCHEMA_DIR, "schema_manifest.yaml")
    VALID_CASE_PATH = os.path.join(EXAMPLES_DIR, "tiny_valid_case.json")
    INVALID_CASES_PATH = os.path.join(EXAMPLES_DIR, "tiny_invalid_cases.json")
    LEGACY_FORBIDDEN_FIELDS = list(BASE_LEGACY_FORBIDDEN_FIELDS)
    if version == "CARS_ACTIVE_SCHEMA_V4":
        LEGACY_FORBIDDEN_FIELDS = (
            LEGACY_FORBIDDEN_FIELDS
            + list(V2_LEGACY_FORBIDDEN_FIELDS)
            + list(V3_LEGACY_FORBIDDEN_FIELDS)
            + list(V4_LEGACY_FORBIDDEN_FIELDS)
        )
    elif version == "CARS_ACTIVE_SCHEMA_V3":
        LEGACY_FORBIDDEN_FIELDS = (
            LEGACY_FORBIDDEN_FIELDS
            + list(V2_LEGACY_FORBIDDEN_FIELDS)
            + list(V3_LEGACY_FORBIDDEN_FIELDS)
        )
    elif version == "CARS_ACTIVE_SCHEMA_V2":
        LEGACY_FORBIDDEN_FIELDS = LEGACY_FORBIDDEN_FIELDS + list(V2_LEGACY_FORBIDDEN_FIELDS)
    else:
        LEGACY_FORBIDDEN_FIELDS = list(BASE_LEGACY_FORBIDDEN_FIELDS)

    # 1. 文件加载（JSON/YAML 可解析）
    schema_files = list_schema_files()
    docs = load_schema_docs()
    docs_by_file = docs

    manifest = load_yaml(MANIFEST_PATH)
    valid_case = load_json(VALID_CASE_PATH)
    invalid_cases = load_json(INVALID_CASES_PATH)["invalid_cases"]

    doc_list = list(docs.values())

    # 2. 元 Schema 校验
    for name, doc in docs.items():
        meta_errors = check_meta_schema(doc)
        errors.extend(
            "%s: meta-schema: %s" % (name, msg) for msg in meta_errors
        )

    # 3. $ref 可解析
    errors.extend(check_refs_resolvable(doc_list))

    # 4. $id 唯一
    errors.extend(check_ids_unique(doc_list))

    # 5. Manifest 一致性
    errors.extend(check_manifest(manifest, schema_files))

    # 6. version 完整
    errors.extend(check_version(doc_list))

    # 7. 字段单位完整
    for name, doc in docs.items():
        unit_errors = check_field_units(doc)
        errors.extend("%s: %s" % (name, msg) for msg in unit_errors)

    # 8. Registry（供实例校验）
    resources = {
        doc["$id"]: Resource.from_contents(doc, default_specification=DRAFT202012)
        for doc in doc_list
    }
    registry = Registry().with_resources(resources.items())

    # 9. 有效微型案例
    scenario = None
    for obj in valid_case.get("objects", []):
        payload = obj["payload"]
        schema_errors = validate_instance(
            payload, obj["target_schema"], registry, docs_by_file
        )
        if schema_errors:
            errors.extend(
                "VALID %s (schema): %s" % (obj["object_name"], msg)
                for msg in schema_errors
            )
        # 跨字段不变量
        if obj["object_name"] == "scenario":
            scenario = payload
            for msg in check_scenario_invariants(payload):
                errors.append("VALID scenario (invariant): %s" % msg)
            future = check_timepoint(payload)
            if future:
                errors.append("VALID scenario (timepoint): future fields %s" % future)
        elif obj["object_name"] == "predecision_state":
            future = check_timepoint(payload)
            if future:
                errors.append("VALID predecision_state (timepoint): %s" % future)
        elif obj["object_name"] in DECISION_OBJECTS:
            if scenario is None:
                errors.append("VALID case: scenario object must precede decision objects")
                continue
            spec = DECISION_OBJECTS[obj["object_name"]]
            sub = payload[spec["path"]] if spec["path"] else payload
            for msg in check_decision_invariants(scenario, sub):
                errors.append(
                    "VALID %s (invariant): %s" % (obj["object_name"], msg)
                )
            if obj["object_name"] in ("ruad_output", "aada_output"):
                for msg in check_ruad_dynamic_states(scenario, payload):
                    errors.append(
                        "VALID %s (state): %s" % (obj["object_name"], msg)
                    )
        # forbidden fields（所有对象）
        forbidden = scan_forbidden_fields(payload)
        if forbidden:
            errors.append(
                "VALID %s (forbidden): %s"
                % (obj["object_name"], ", ".join(forbidden))
            )

    if scenario is None:
        errors.append("VALID case: missing scenario object")

    # 10. 冻结非法案例必须被拒绝
    for case in invalid_cases:
        case_id = case["case_id"]
        kind = case["expected_rejection"]
        payload = case["payload"]
        target = case.get("target_schema")
        if kind == "schema_validation":
            schema_errors = validate_instance(
                payload, target, registry, docs_by_file
            )
            if not schema_errors:
                errors.append(
                    "INVALID %s: expected schema_validation rejection but passed"
                    % case_id
                )
        elif kind == "cross_field_invariant":
            # 需构造 scenario 上下文：若 target 是 schedule_decision，用有效案例 scenario
            schema_errors = validate_instance(
                payload, target, registry, docs_by_file
            )
            if schema_errors:
                errors.append(
                    "INVALID %s: expected cross_field rejection but schema failed: %s"
                    % (case_id, schema_errors[:1])
                )
            else:
                inv = check_decision_invariants(scenario, payload)
                if not inv:
                    errors.append(
                        "INVALID %s: expected cross_field rejection but passed" % case_id
                    )
        elif kind == "forbidden_field":
            found = scan_forbidden_fields(payload)
            if not found:
                errors.append(
                    "INVALID %s: expected forbidden_field rejection but none found"
                    % case_id
                )
        elif kind == "timepoint_violation":
            future = check_timepoint(payload)
            if not future:
                errors.append(
                    "INVALID %s: expected timepoint violation but none found" % case_id
                )
        elif kind == "unit_missing":
            unit_errors = check_field_units(payload)
            if not unit_errors:
                errors.append(
                    "INVALID %s: expected unit_missing rejection but none found"
                    % case_id
                )
        else:
            errors.append("INVALID %s: unknown expected_rejection '%s'" % (case_id, kind))

    # 11. 确定性：同一输入重复验证结果一致（对有效案例重复一次）
    deterministic_ok = True
    try:
        second_pass = []
        for obj in valid_case.get("objects", []):
            schema_errors = validate_instance(
                obj["payload"], obj["target_schema"], registry, docs_by_file
            )
            second_pass.append(bool(schema_errors))
        if second_pass and any(second_pass):
            deterministic_ok = False
    except Exception as exc:  # pragma: no cover
        deterministic_ok = False
        errors.append("determinism re-run failed: %s" % exc)
    if not deterministic_ok:
        errors.append("determinism check: re-run produced different result")

    # 汇总
    total = len(errors)
    for msg in errors:
        sys.stderr.write("  [FAIL] %s\n" % msg)

    if total == 0:
        if not quiet:
            print("VALIDATE ACTIVE SCHEMA: PASS")
        print("schemas=%d valid_case_objects=%d invalid_cases=%d errors=%d"
              % (len(schema_files), len(valid_case.get("objects", [])),
                 len(invalid_cases), total))
        return 0
    sys.stderr.write("VALIDATE ACTIVE SCHEMA: FAIL (%d errors)\n" % total)
    return 1


if __name__ == "__main__":
    sys.exit(main())
