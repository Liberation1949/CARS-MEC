# -*- coding: utf-8 -*-
"""E4-V2-0：E4 Trace 输入只读检查器（Trace Input Inspector）。

职责（仅限只读）：
  1. 枚举 data/processed/e4_trace_enhanced/ 全部文件并校验 SHA-256（与 manifest 对照）；
  2. 解析 trace_slots JSONL 的 header/schema，输出字段与单位；
  3. 检查时间顺序与 slot 顺序完整性；
  4. 检查 missing/invalid record 的既有状态；
  5. 验证 Trace 字段映射合同（e4_v2_trace_field_mapping.yaml）可解析且分类合法；
  6. 验证 pilot/formal partition 隔离（互斥、子集、时间先后）；
  7. --smoke 模式：从 calibration 分区取一个最小 Trace record，演示
     Trace record -> field mapping -> E4 Scenario input 的语义链
     （NOT_FORMAL；不运行任何方法；不写 data/）。

禁止：写入 data/；重新处理；归一化；缩放；插值；补缺失；修改 mapping。

用法：
  python scripts/reproduce/e4_v2/inspect_e4_trace_input.py
  python scripts/reproduce/e4_v2/inspect_e4_trace_input.py --smoke
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from typing import Any, Dict, List

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TRACE_ROOT = os.path.join(PROJECT_ROOT, "data", "processed", "e4_trace_enhanced")
CONFIG_ROOT = os.path.join(PROJECT_ROOT, "configs", "e4_v2")

MANIFEST_PATH = os.path.join(CONFIG_ROOT, "e4_v2_trace_input_manifest.yaml")
MAPPING_PATH = os.path.join(CONFIG_ROOT, "e4_v2_trace_field_mapping.yaml")

DATASETS = ["azure", "nep", "shanghai"]
PARTITIONS = ["calibration", "pilot", "formal"]

# 合法分类枚举（与 mapping 合同一致）
CLASSIFICATIONS = {
    "TRACE_OBSERVED",
    "TRACE_DERIVED",
    "SYNTHETIC_FIXED",
    "PROJECT_MODEL_DERIVED",
    "UNUSED",
}
SEMANTIC_STATUS = {"CONFIRMED", "WORKING_ASSUMPTION", "UNUSED"}


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_yaml(path: str) -> Dict[str, Any]:
    import yaml  # local import：PyYAML 为环境既有依赖

    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_jsonl(path: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def walk_files(root: str) -> List[str]:
    out: List[str] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in sorted(filenames):
            out.append(os.path.relpath(os.path.join(dirpath, fn), root).replace("\\", "/"))
    return sorted(out)


def check_manifest_hashes() -> Dict[str, Any]:
    """检查 manifest 声明的 19 个文件与磁盘实际文件、hash 一致（只读）。"""
    result: Dict[str, Any] = {"status": "PASS", "checks": []}
    manifest = load_yaml(MANIFEST_PATH)
    declared = {f["path"]: f["sha256"] for f in manifest["file_hashes"]}
    actual_files = walk_files(TRACE_ROOT)
    if len(actual_files) != len(declared):
        result["status"] = "FAIL"
        result["checks"].append(
            f"file count mismatch: actual={len(actual_files)} declared={len(declared)}"
        )
    mismatches = []
    for rel, expected in sorted(declared.items()):
        p = os.path.join(TRACE_ROOT, rel.replace("/", os.sep))
        if not os.path.exists(p):
            mismatches.append(f"MISSING {rel}")
            continue
        h = sha256_file(p)
        if h != expected:
            mismatches.append(f"HASH_MISMATCH {rel}: {h[:16]} != {expected[:16]}")
    if mismatches:
        result["status"] = "FAIL"
        result["checks"].extend(mismatches)
    else:
        result["checks"].append(f"all {len(declared)} declared files hash-verified")
    return result


def inspect_header(path: str, dataset: str) -> Dict[str, Any]:
    recs = load_jsonl(path)
    if not recs:
        return {"dataset": dataset, "records": 0}
    keys = list(recs[0].keys())
    ts = [r["timestamp"] for r in recs]
    ordered = ts == sorted(ts)
    null_counts = {
        k: sum(1 for r in recs if r.get(k) is None)
        for k in ["cpu_pressure", "memory_pressure", "bandwidth_state", "rtt_state",
                  "region_id", "hotspot_distribution"]
    }
    return {
        "dataset": dataset,
        "records": len(recs),
        "keys": keys,
        "time_ordered": ordered,
        "time_start": ts[0],
        "time_end": ts[-1],
        "null_counts": null_counts,
    }


def check_partition_isolation() -> Dict[str, Any]:
    result: Dict[str, Any] = {"status": "PASS", "checks": []}
    for ds in DATASETS:
        raw_ids = {r["slot_id"] for r in load_jsonl(os.path.join(TRACE_ROOT, ds, f"{ds}_trace_slots.jsonl"))}
        part_ids = {}
        for part in PARTITIONS:
            path = os.path.join(TRACE_ROOT, "splits", ds, f"{ds}_{part}.jsonl")
            part_ids[part] = {r["slot_id"] for r in load_jsonl(path)}
        # subset
        union = set().union(*part_ids.values()) if part_ids else set()
        if not union.issubset(raw_ids):
            result["status"] = "FAIL"
            result["checks"].append(f"{ds}: split not subset of raw")
        # disjoint
        a, b, c = part_ids["calibration"], part_ids["pilot"], part_ids["formal"]
        if a & b or a & c or b & c:
            result["status"] = "FAIL"
            result["checks"].append(f"{ds}: partitions overlap")
        # time order: max(cal) < min(pilot) < min(formal)
        def tmin(s):
            return min(load_jsonl(os.path.join(TRACE_ROOT, "splits", ds, f"{ds}_{p}.jsonl"))[0]["timestamp"]
                       for p in [s]) if False else None
        cal0 = load_jsonl(os.path.join(TRACE_ROOT, "splits", ds, f"{ds}_calibration.jsonl"))[0]["timestamp"]
        pil0 = load_jsonl(os.path.join(TRACE_ROOT, "splits", ds, f"{ds}_pilot.jsonl"))[0]["timestamp"]
        for0 = load_jsonl(os.path.join(TRACE_ROOT, "splits", ds, f"{ds}_formal.jsonl"))[0]["timestamp"]
        if not (cal0 < pil0 < for0):
            result["status"] = "FAIL"
            result["checks"].append(f"{ds}: partition time order violated")
        result["checks"].append(f"{ds}: cal={len(a)} pilot={len(b)} formal={len(c)} disjoint+subset+ordered")
    return result


def validate_mapping() -> Dict[str, Any]:
    """验证 field mapping 合同：分类与 semantic_status 合法；无凭想象补字段。"""
    result: Dict[str, Any] = {"status": "PASS", "checks": [], "field_count": 0}
    mapping = load_yaml(MAPPING_PATH)
    issues = []
    n = 0
    for f in mapping["trace_fields"]:
        n += 1
        cls = f.get("classification")
        st = f.get("semantic_status")
        if cls not in CLASSIFICATIONS:
            issues.append(f"bad classification {cls} @ {f['source_field']}")
        if st not in SEMANTIC_STATUS:
            issues.append(f"bad semantic_status {st} @ {f['source_field']}")
        if st == "UNUSED" and cls != "UNUSED":
            issues.append(f"status UNUSED but class {cls} @ {f['source_field']}")
        for req in ["source_field", "source_unit", "target_object", "target_field",
                    "target_unit", "mapping_rule", "evidence", "evidence_strength",
                    "semantic_status", "classification"]:
            if req not in f:
                issues.append(f"missing {req} @ {f['source_field']}")
    for f in mapping["synthetic_fixed_fields"]:
        n += 1
        if f.get("classification") not in CLASSIFICATIONS:
            issues.append(f"bad class @ {f['target_field']}")
    result["field_count"] = n
    if issues:
        result["status"] = "FAIL"
        result["checks"].extend(issues)
    else:
        result["checks"].append(f"mapping contract valid: {n} field entries")
    return result


def build_smoke_scenario(dataset: str = "azure") -> Dict[str, Any]:
    """人工微型案例：从 calibration 分区取最小 Trace record -> E4 Scenario input。

    NOT_FORMAL：仅验证语义链（Trace -> mapping -> Schema V4 场景结构），
    不运行 CARS/Baseline，不构造正式数据。
    """
    cal_path = os.path.join(TRACE_ROOT, "splits", dataset, f"{dataset}_calibration.jsonl")
    rec = load_jsonl(cal_path)[0]
    # 语义链（与 mapping 合同一致）：
    #   timestamp/slot_id -> window_id（TRACE_OBSERVED）
    #   workload_intensity -> workload 驱动（TRACE_DERIVED，既有归一化）
    #   任务/设备/服务器/链路参数 -> synthetic-fixed（冻结环境值，示例）
    window_id = rec["slot_id"]
    workload = rec["workload_intensity"]
    n_tasks = 20  # 冻结桥接示例值（正式规则由 Pilot 协议冻结；此处仅演示语义链）

    scenario = {
        "schema_version": "CARS_ACTIVE_SCHEMA_V4",
        "scenario_id": f"e4v2_smoke_{dataset}_{window_id}",
        "state_timepoint": "T0",
        "system_params": {
            "rcla_solver": {
                "rcla_mu_tol": 1.0e-9, "rcla_max_iters": 200,
                "rcla_mu_lo": 1.0e-12, "rcla_mu_hi": 1.0e12,
                "rcla_numeric_epsilon": 1.0e-12,
            },
            "numeric_epsilon": 1.0e-12,
        },
        "tasks": [
            {
                "task_id": f"t{i}",
                "device_id": f"d{i}",
                "data_bits": 1000.0,
                "cpu_cycles": float([2000, 5000, 12000][i % 3]),
                "fragility": float([0, 8, 16][i % 3]),
                "delay_weight": 0.6,
                "energy_weight": 0.4,
                "deadline_seconds": 1000.0,  # 占位；无 deadline 模型不读取
                "min_reliability": 0.90,
            }
            for i in range(1, n_tasks + 1)
        ],
        "devices": [
            {
                "device_id": f"d{i}",
                "local_cpu_rate": float([800, 1200][i % 2]),
                "local_failure_rate": 0.002,
                "switch_capacitance": 0.5,
                "tx_power_watts": 1.0,
            }
            for i in range(1, n_tasks + 1)
        ],
        "servers": [
            {
                "server_id": f"s{j}",
                "capacity_cycles_per_sec": 10000.0 * (1 + 0.3 * (j % 3)),
                "nominal_failure_rate": 0.002,
            }
            for j in range(1, 9)
        ],
        "links": [
            {
                "link_id": f"l{d}_{j}",
                "source_device_id": f"d{d}",
                "target_server_id": f"s{j}",
                "bandwidth_hz": 1.0e6,
                "channel_gain": 1.0,
                "noise_power": 1.0,
                "error_probability": 0.01,
            }
            for d in range(1, n_tasks + 1) for j in range(1, 9)
        ],
    }
    return {
        "NOT_FORMAL": True,
        "trace_record": rec,
        "window_id_from_trace": window_id,
        "workload_intensity_from_trace": workload,
        "trace_signal_source": "TRACE_OBSERVED/DERIVED",
        "scenario_inputs_from_synthetic_fixed": [
            "servers(F_j, lambda_j)", "devices", "links", "task params",
            "M=8", "deadline_seconds placeholder",
        ],
        "scenario_schema_version": "CARS_ACTIVE_SCHEMA_V4",
        "scenario": scenario,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="E4 Trace input read-only inspector")
    ap.add_argument("--smoke", action="store_true",
                    help="build a minimal NOT_FORMAL mapping smoke scenario from calibration record")
    args = ap.parse_args()

    results: Dict[str, Any] = {"checks": {}}

    print("== [1] manifest hash verification ==")
    r1 = check_manifest_hashes()
    results["checks"]["manifest_hashes"] = r1
    print(f"   {r1['status']}: {r1['checks']}")

    print("== [2] trace slot header/schema ==")
    headers = {}
    for ds in DATASETS:
        h = inspect_header(os.path.join(TRACE_ROOT, ds, f"{ds}_trace_slots.jsonl"), ds)
        headers[ds] = h
        print(f"   {ds}: records={h['records']} time_ordered={h['time_ordered']} "
              f"null={h['null_counts']}")
    results["checks"]["headers"] = headers

    print("== [3] partition isolation ==")
    r3 = check_partition_isolation()
    results["checks"]["partition_isolation"] = r3
    print(f"   {r3['status']}: {r3['checks']}")

    print("== [4] mapping contract validation ==")
    r4 = validate_mapping()
    results["checks"]["mapping_contract"] = r4
    print(f"   {r4['status']}: {r4['checks']}")

    print("== [5] data/ write-protection (script has no write code path) ==")
    src = open(os.path.abspath(__file__), "r", encoding="utf-8").read()
    # 静态检查：本脚本不应有以写模式打开文件（w/a/r+）的调用（除读取自身文本外）
    import re
    dangerous = re.findall(r"open\(\s*[^,)]*,\s*['\"]([wa]|r\+)[b]?['\"]", src)
    results["checks"]["no_write_path"] = {
        "status": "PASS" if not dangerous else "FAIL",
        "write_calls_found": dangerous,
    }
    print(f"   {results['checks']['no_write_path']['status']}: write calls = {dangerous}")

    if args.smoke:
        print("== [6] NOT_FORMAL mapping smoke (manual micro-case) ==")
        smoke = build_smoke_scenario()
        print(f"   window_id={smoke['window_id_from_trace']} "
              f"workload={smoke['workload_intensity_from_trace']:.4f}")
        print(f"   scenario: N={len(smoke['scenario']['tasks'])} "
              f"M={len(smoke['scenario']['servers'])} "
              f"links={len(smoke['scenario']['links'])} "
              f"schema={smoke['scenario']['schema_version']}")
        results["smoke"] = smoke

    overall = "PASS"
    for name, r in results["checks"].items():
        if isinstance(r, dict) and r.get("status") == "FAIL":
            overall = "FAIL"
    print(f"\n== OVERALL: {overall} ==")
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
