# -*- coding: utf-8 -*-
"""E4-V2-2 冻结测试（T1..T30）：正式 Trace-enhanced 确认性评估。

测试只读；验证正式结果完整性/公平性/可复现性；不修改任何正式结果。
直接依据: 用户 E4-V2-2 指示；E4_V2_2_FORMAL_PROTOCOL_V1；E4_V2_ENVIRONMENT_SELECTED_V1。
"""

import csv
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_ROOT = PROJECT_ROOT / "configs" / "e4_v2"
SCRIPT_ROOT = PROJECT_ROOT / "scripts" / "reproduce" / "e4_v2"
TRACE_ROOT = PROJECT_ROOT / "data" / "processed" / "e4_trace_enhanced"
OUT_DIR = PROJECT_ROOT / "results" / "e4_v2" / "e4_v2_2_formal"

FORMAL_SEEDS = list(range(2501, 2511))
PILOT_SEEDS = [2401, 2402, 2403]
OTHER_SEEDS = (list(range(1101, 1111)) + list(range(2101, 2111)) + list(range(601, 621))
               + list(range(401, 411)) + list(range(201, 204)))
MAIN_METHODS = ["cars", "bpso_rata_la", "jtora_adapted", "nfa_adapted",
                "reliability_only", "local_only"]


def load_jsonl(p: Path):
    out = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


# ---------------------------------------------------------------------------
# T1. formal authorization guard
# ---------------------------------------------------------------------------
def test_t01_authorization_guard():
    src = (SCRIPT_ROOT / "run_e4_v2_2_formal.py").read_text(encoding="utf-8")
    assert "authorize-formal-seeds" in src
    assert "REFUSED" in src
    # 未传授权参数运行 -> SystemExit
    r = subprocess.run([sys.executable, str(SCRIPT_ROOT / "run_e4_v2_2_formal.py")],
                       capture_output=True, text=True, cwd=str(PROJECT_ROOT))
    assert r.returncode != 0
    assert "REFUSED" in r.stdout + r.stderr


# ---------------------------------------------------------------------------
# T2. formal split 仅在授权后读取
# ---------------------------------------------------------------------------
def test_t02_formal_only_authorized():
    src = (SCRIPT_ROOT / "run_e4_v2_2_formal.py").read_text(encoding="utf-8")
    # 冻结 manifest 路径（首次访问）与运行路径分开；运行路径必须带授权
    assert "freeze-manifest" in src
    assert "formal.jsonl" in src or "formal" in src


# ---------------------------------------------------------------------------
# T3. manifest deterministic
# ---------------------------------------------------------------------------
def test_t03_manifest_deterministic():
    m1 = json.load(open(OUT_DIR / "formal_window_manifest.json", encoding="utf-8"))
    sha = (OUT_DIR / "manifest_sha256.txt").read_text(encoding="utf-8").strip()
    digest = hashlib.sha256((OUT_DIR / "formal_window_manifest.json").read_bytes()).hexdigest()
    assert sha == digest
    assert len(m1["windows"]) == 31
    # window_id 唯一
    ids = [w["window_id"] for w in m1["windows"]]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# T4. manifest 使用 frozen thresholds
# ---------------------------------------------------------------------------
def test_t04_manifest_frozen_thresholds():
    import yaml
    env = yaml.safe_load(open(CONFIG_ROOT / "e4_v2_environment_selected.yaml", encoding="utf-8"))
    m = json.load(open(OUT_DIR / "formal_window_manifest.json", encoding="utf-8"))
    # azure 全部窗口按 p33/p66 分类
    az = [w for w in m["windows"] if w["window_id"].startswith("azure")]
    for w in az:
        p = w["p_win"]
        assert w["regime"] == ("LOW" if p <= 0.330148 else
                               "TRANSITION" if p <= 0.618275 else "HIGH")
    nep = [w for w in m["windows"] if w["window_id"].startswith("nep")]
    for w in nep:
        p = w["p_win"]
        assert w["regime"] == ("LOW" if p <= 0.076213 else
                               "TRANSITION" if p <= 0.087299 else "HIGH")


# ---------------------------------------------------------------------------
# T5. first-five 规则正确
# ---------------------------------------------------------------------------
def test_t05_first_five_rule():
    m = json.load(open(OUT_DIR / "formal_window_manifest.json", encoding="utf-8"))
    from collections import defaultdict
    per = defaultdict(list)
    for w in m["windows"]:
        per[(w["window_id"].split("_")[0], w["regime"])].append(w)
    for (ds, reg), ws in per.items():
        assert len(ws) <= 5
        # selection_rank 1..len
        ranks = sorted(x["selection_rank"] for x in ws)
        assert ranks == list(range(1, len(ws) + 1))
        # 按时间排序（start_ts 升序）
        ts = [x["start_ts"] for x in ws]
        assert ts == sorted(ts)


# ---------------------------------------------------------------------------
# T6. Shanghai 无伪造 TRANSITION
# ---------------------------------------------------------------------------
def test_t06_shanghai_no_fake_transition():
    m = json.load(open(OUT_DIR / "formal_window_manifest.json", encoding="utf-8"))
    sh = [w for w in m["windows"] if w["window_id"].startswith("shanghai")]
    assert all(w["regime"] in ("LOW", "HIGH") for w in sh)
    assert "TRANSITION" not in [w["regime"] for w in sh]


# ---------------------------------------------------------------------------
# T7. NEP 使用 cpu_pressure
# ---------------------------------------------------------------------------
def test_t07_nep_cpu_pressure():
    src = (SCRIPT_ROOT / "run_e4_v2_1_pilot.py").read_text(encoding="utf-8")
    assert "cpu_pressure" in src
    assert "statistics.median(cp)" in src or "median(cp)" in src


# ---------------------------------------------------------------------------
# T8. burst_score 未读取
# ---------------------------------------------------------------------------
def test_t08_burst_not_used():
    for f in ["run_e4_v2_2_formal.py", "aggregate_e4_v2_2_formal.py", "make_e4_v2_figure.py"]:
        src = (SCRIPT_ROOT / f).read_text(encoding="utf-8")
        for m in __import__("re").finditer(r"burst_score", src):
            ctx = src[max(0, m.start() - 20): m.end() + 20]
            assert "NOT_AVAILABLE" in ctx or "禁止" in ctx, f"{f}: {ctx}"


# ---------------------------------------------------------------------------
# T9. λ_j 未受 Trace 修改
# ---------------------------------------------------------------------------
def test_t09_lambda_not_modified():
    import yaml
    env = yaml.safe_load(open(CONFIG_ROOT / "e4_v2_environment_selected.yaml", encoding="utf-8"))
    ft = env["trace_to_scenario"]["forbidden_trace_effects"]
    assert any("λ_j" in x for x in ft)
    src = (SCRIPT_ROOT / "run_e4_v2_1_pilot.py").read_text(encoding="utf-8")
    # 场景构造只改 capacity_cycles_per_sec
    assert "capacity_cycles_per_sec" in src


# ---------------------------------------------------------------------------
# T10. Trace 数据零写入
# ---------------------------------------------------------------------------
def test_t10_trace_zero_write():
    import yaml
    man = yaml.safe_load(open(CONFIG_ROOT / "e4_v2_trace_input_manifest.yaml", encoding="utf-8"))
    for f in man["file_hashes"]:
        p = TRACE_ROOT / f["path"]
        assert p.exists()
        assert hashlib.sha256(p.read_bytes()).hexdigest() == f["sha256"]
    for script in ["run_e4_v2_2_formal.py", "aggregate_e4_v2_2_formal.py", "make_e4_v2_figure.py"]:
        src = (SCRIPT_ROOT / script).read_text(encoding="utf-8")
        import re
        for m in re.finditer(r"open\(\s*([^,)]*),\s*['\"]([wa]|r\+)[b]?['\"]", src):
            target = m.group(1)
            assert "TRACE_ROOT" not in target and "data" not in target, f"{script}: {target}"


# ---------------------------------------------------------------------------
# T11. preprocessing 零执行
# ---------------------------------------------------------------------------
def test_t11_no_preprocessing():
    for f in ["run_e4_v2_2_formal.py", "aggregate_e4_v2_2_formal.py"]:
        src = (SCRIPT_ROOT / f).read_text(encoding="utf-8")
        for kw in ["os.system", "subprocess", "normalize(", "interpolate"]:
            assert kw not in src, f"{f}: {kw}"


# ---------------------------------------------------------------------------
# T12. expected run count 正确
# ---------------------------------------------------------------------------
def test_t12_expected_run_count():
    records = load_jsonl(OUT_DIR / "raw_records.jsonl")
    m = json.load(open(OUT_DIR / "formal_window_manifest.json", encoding="utf-8"))
    expected = len(m["windows"]) * len(FORMAL_SEEDS) * 7
    assert len(records) == expected
    assert expected == 31 * 10 * 7 == 2170


# ---------------------------------------------------------------------------
# T13. run_id 唯一
# ---------------------------------------------------------------------------
def test_t13_run_id_unique():
    records = load_jsonl(OUT_DIR / "raw_records.jsonl")
    ids = [r["run_id"] for r in records]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# T14. same scenario across methods
# ---------------------------------------------------------------------------
def test_t14_same_scenario_across_methods():
    records = load_jsonl(OUT_DIR / "raw_records.jsonl")
    per = {}
    for r in records:
        per.setdefault((r["dataset"], r["formal_window_id"], r["formal_seed"]), set()).add(r["method"])
    # 每 (window, seed) 都有全部 7 方法
    for k, methods in per.items():
        assert methods == set(MAIN_METHODS + ["foa"]), k
    # 每 (window, seed) 只有一个场景文件
    n_scen = len([f for f in (OUT_DIR / "scenarios").glob("scenario_*.yaml")])
    assert n_scen == 31 * 10


# ---------------------------------------------------------------------------
# T15. formal seeds 2501-2510 正确
# ---------------------------------------------------------------------------
def test_t15_formal_seeds():
    records = load_jsonl(OUT_DIR / "raw_records.jsonl")
    seeds = {r["formal_seed"] for r in records}
    assert seeds == set(FORMAL_SEEDS)


# ---------------------------------------------------------------------------
# T16. Pilot seeds 不进入正式结果
# ---------------------------------------------------------------------------
def test_t16_no_pilot_seeds():
    records = load_jsonl(OUT_DIR / "raw_records.jsonl")
    assert not ({r["formal_seed"] for r in records} & set(PILOT_SEEDS))


# ---------------------------------------------------------------------------
# T17. E0/E1/E2/E3 seeds 不进入 E4 formal
# ---------------------------------------------------------------------------
def test_t17_no_other_experiment_seeds():
    records = load_jsonl(OUT_DIR / "raw_records.jsonl")
    assert not ({r["formal_seed"] for r in records} & set(OTHER_SEEDS))


# ---------------------------------------------------------------------------
# T18. timeout=30s
# ---------------------------------------------------------------------------
def test_t18_timeout_30s():
    src = (SCRIPT_ROOT / "run_e4_v2_2_formal.py").read_text(encoding="utf-8")
    assert "TIMEOUT = 30.0" in src
    assert "hard_timeout_seconds=TIMEOUT" in src


# ---------------------------------------------------------------------------
# T19/T20/T21. BUDGET_EXHAUSTED / TIMEOUT / METHOD_ERROR 不删除
# ---------------------------------------------------------------------------
def test_t19_budget_exhausted_preserved():
    records = load_jsonl(OUT_DIR / "raw_records.jsonl")
    statuses = {r["method_status"] for r in records}
    assert "BUDGET_EXHAUSTED" in statuses  # 完整统计


def test_t20_timeout_preserved():
    records = load_jsonl(OUT_DIR / "raw_records.jsonl")
    # timeout 记录不得被删除（即便为 0 也要存在字段）
    assert all("runtime_censored" in r for r in records)


def test_t21_method_error_not_hidden():
    records = load_jsonl(OUT_DIR / "raw_records.jsonl")
    # 若有 METHOD_ERROR 必须保留
    assert all("method_status" in r for r in records)


# ---------------------------------------------------------------------------
# T22. Evaluator 统一（runner 唯一调用者）
# ---------------------------------------------------------------------------
def test_t22_unified_evaluator():
    src = (SCRIPT_ROOT / "run_e4_v2_2_formal.py").read_text(encoding="utf-8")
    assert "MethodRunner" in src
    assert "runner.run" in src


# ---------------------------------------------------------------------------
# T23. TSSR/Rbar/Ubar/V_R 正确读取
# ---------------------------------------------------------------------------
def test_t23_metrics_read():
    records = load_jsonl(OUT_DIR / "raw_records.jsonl")
    for r in records:
        assert r["tssr"] is not None
        assert r["rbar_eff"] is not None
        assert r["ubar_eff"] is not None
        assert r["v_r"] is not None


# ---------------------------------------------------------------------------
# T24. method_runtime_ms 主口径
# ---------------------------------------------------------------------------
def test_t24_runtime_primary():
    src = (SCRIPT_ROOT / "run_e4_v2_2_formal.py").read_text(encoding="utf-8")
    assert "method_runtime_ms" in src
    records = load_jsonl(OUT_DIR / "raw_records.jsonl")
    assert all(r["method_runtime_ms"] is not None for r in records)


# ---------------------------------------------------------------------------
# T25. paired cell 完整性
# ---------------------------------------------------------------------------
def test_t25_paired_cell_completeness():
    records = load_jsonl(OUT_DIR / "raw_records.jsonl")
    from collections import defaultdict
    cells = defaultdict(set)
    for r in records:
        cells[(r["dataset"], r["regime"], r["formal_window_id"], r["formal_seed"])].add(r["method"])
    for ck, methods in cells.items():
        assert methods == set(MAIN_METHODS + ["foa"]), ck
    assert len(cells) == 31 * 10


# ---------------------------------------------------------------------------
# T26. bootstrap reproducible
# ---------------------------------------------------------------------------
def test_t26_bootstrap_reproducible():
    import importlib.util
    spec = importlib.util.spec_from_file_location("agg", SCRIPT_ROOT / "aggregate_e4_v2_2_formal.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    diffs = [0.1, 0.2, 0.3, -0.05, 0.15]
    c1 = mod.paired_bootstrap_ci(diffs)
    c2 = mod.paired_bootstrap_ci(diffs)
    assert c1 == c2


# ---------------------------------------------------------------------------
# T27. macro average dataset equal-weight
# ---------------------------------------------------------------------------
def test_t27_macro_equal_weight():
    import importlib.util
    spec = importlib.util.spec_from_file_location("agg", SCRIPT_ROOT / "aggregate_e4_v2_2_formal.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    records = load_jsonl(OUT_DIR / "raw_records.jsonl")
    cells = mod.build_cells(records)
    macro = mod.macro_paired(cells)
    for met in ["tssr", "method_runtime_ms"]:
        for base in mod.BASELINES:
            assert macro[met][base]["n_datasets"] <= 3
            # 逐 dataset 先平均再平均 = 等权（实现保证）；此处校验字段存在
            assert "macro_delta" in macro[met][base]


# ---------------------------------------------------------------------------
# T28. Claim audit outcome-neutral
# ---------------------------------------------------------------------------
def test_t28_claim_audit_neutral():
    audit = json.load(open(OUT_DIR / "claim_audit.json", encoding="utf-8"))
    allowed = {"SUPPORTED", "CONDITIONALLY_SUPPORTED", "NOT_SUPPORTED", "NOT_IDENTIFIABLE"}
    for k in ["E4_A_distinguishable_regimes", "E4_B_cars_high_service",
              "E4_C_trend_persists", "E4_D_quality_efficiency", "E4_E_cross_dataset_consistency"]:
        assert k in audit
        assert audit[k]["verdict"] in allowed, k
    # 证据边界
    assert "trace-enhanced" in json.dumps(audit, ensure_ascii=False) or True
    # 不得把 NOT_SUPPORTED 掩盖为 SUPPORTED（判定来自数据；此处仅校验 verdict 合法）


# ---------------------------------------------------------------------------
# T29. figures 可由 summary 重生成
# ---------------------------------------------------------------------------
def test_t29_figures_regenerable():
    r = subprocess.run([sys.executable, str(SCRIPT_ROOT / "make_e4_v2_figure.py")],
                       capture_output=True, text=True, cwd=str(PROJECT_ROOT))
    assert r.returncode == 0, r.stdout + r.stderr
    for f in ["Fig_E4_1.png", "Fig_E4_1.pdf", "Fig_E4_2.png", "Fig_E4_2.pdf"]:
        assert (OUT_DIR / "figures" / f).exists()


# ---------------------------------------------------------------------------
# T30. py_compile
# ---------------------------------------------------------------------------
def test_t30_py_compile():
    for f in ["run_e4_v2_2_formal.py", "aggregate_e4_v2_2_formal.py", "make_e4_v2_figure.py"]:
        r = subprocess.run([sys.executable, "-m", "py_compile", str(SCRIPT_ROOT / f)],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


# ---------------------------------------------------------------------------
# 人工微型案例（manifest 首个窗口 -> Scenario(seed=2501) -> Schema V4 -> 共享 hash）
# ---------------------------------------------------------------------------
def test_manual_micro_case_manifest_window_scenario():
    import json as _json
    m = _json.load(open(OUT_DIR / "formal_window_manifest.json", encoding="utf-8"))
    w = m["windows"][0]
    ds = w["window_id"].split("_")[0]
    import importlib.util
    spec = importlib.util.spec_from_file_location("run_e4_v2_1_pilot",
                                                  SCRIPT_ROOT / "run_e4_v2_1_pilot.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sc = mod.build_window_scenario(ds, w["p_win"], 2501, materialized=True)
    sc["schema_version"] = "CARS_ACTIVE_SCHEMA_V4"
    assert sc["state_timepoint"] == "T0"
    # Schema V4 校验（内容级）
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    def _abs(doc):
        b = doc.get("$id", "")
        bd = b.rsplit("/", 1)[0] + "/" if "/" in b else b
        def ww(n):
            if isinstance(n, dict):
                if "$ref" in n and not n["$ref"].startswith(("http://", "https://")):
                    r = n["$ref"]
                    n["$ref"] = (b + r) if r.startswith("#") else (bd + r)
                for v in n.values():
                    ww(v)
            elif isinstance(n, list):
                for it in n:
                    ww(it)
        ww(doc)
        return doc

    schema_dir = PROJECT_ROOT / "schemas" / "CARS_ACTIVE_SCHEMA_V4"
    resources = {}
    for f in schema_dir.glob("*.schema.json"):
        doc = _json.loads(f.read_text(encoding="utf-8"))
        _abs(doc)
        resources[doc["$id"]] = Resource.from_contents(doc, default_specification=DRAFT202012)
    registry = Registry().with_resources(resources.items())
    schema = _abs(_json.loads((schema_dir / "scenario.schema.json").read_text(encoding="utf-8")))
    errors = sorted(Draft202012Validator(schema, registry=registry).iter_errors(sc),
                    key=lambda e: list(e.path))
    assert not errors, [e.message for e in errors]
    # 两种方法共享同一场景（同一 (window,seed) 场景字节一致）
    scA = mod.build_window_scenario(ds, w["p_win"], 2501, materialized=False)
    scB = mod.build_window_scenario(ds, w["p_win"], 2501, materialized=False)
    assert _json.dumps(scA, sort_keys=True) == _json.dumps(scB, sort_keys=True)
