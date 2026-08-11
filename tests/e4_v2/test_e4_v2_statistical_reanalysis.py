# -*- coding: utf-8 -*-
"""E4-V2 Statistical Reanalysis 冻结测试（T1..T15 + 人工微型案例）。

验证 window-level / hierarchical 统计重分析的：
- 正式 raw results / manifest / Trace 数据不可变性（T1/T2/T15）；
- 配对完整性与统计单位正确性（T3/T4/T5/T6）；
- 小窗口特殊规则（T7 Shanghai-HIGH CASE_LEVEL；T8 Azure-LOW N/A）；
- 可复现性与结构（T9 bootstrap determinism；T10 hierarchical 两层；T11 Holm）；
- 正文编号一致性与 Claim 边界（T12/T13）；
- 无 formal 重跑（T14）。

工程标识：e4_v2（保留）；正文映射：当前 III_VII.md 实验 E3（Trace-Enhanced）。
测试只读；不修改任何正式结果。
"""

import csv
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_ROOT = PROJECT_ROOT / "scripts" / "reproduce" / "e4_v2"
FORMAL_DIR = PROJECT_ROOT / "results" / "e4_v2" / "e4_v2_2_formal"
REANA_DIR = PROJECT_ROOT / "results" / "e4_v2" / "e4_v2_statistical_reanalysis"
MANUSCRIPT = PROJECT_ROOT / "experiment_docs" / "III_VII.md"
TRACE_ROOT = PROJECT_ROOT / "data" / "processed" / "e4_trace_enhanced"

# 重分析脚本位于 scripts/reproduce/e4_v2/ 子目录（conftest 仅加入 scripts/），
# 此处显式加入以支持核心纯函数导入。
sys.path.insert(0, str(SCRIPT_ROOT))

MAIN_METHODS = ["cars", "bpso_rata_la", "jtora_adapted", "nfa_adapted",
                "reliability_only", "local_only"]
ALL_METHODS = MAIN_METHODS + ["foa"]
BASELINES = ["bpso_rata_la", "jtora_adapted", "nfa_adapted", "reliability_only", "local_only"]
FORMAL_SEEDS = list(range(2501, 2511))
EXPECTED_WINDOWS = 31
EXPECTED_RUNS = 2170


def load_jsonl(p):
    out = []
    with open(p, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_csv(p):
    with open(p, "r", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def pre_state_hash(key):
    d = json.load(open(REANA_DIR / "pre_state_hashes.json", encoding="utf-8"))
    return d["hashes"][key]


# ---------------------------------------------------------------------------
# T1. Raw immutability
# ---------------------------------------------------------------------------
def test_t01_raw_records_immutable():
    assert sha256_file(FORMAL_DIR / "raw_records.jsonl") == pre_state_hash("e4_v2_2_formal/raw_records.jsonl")


# ---------------------------------------------------------------------------
# T2. Manifest immutability
# ---------------------------------------------------------------------------
def test_t02_manifest_immutable():
    assert sha256_file(FORMAL_DIR / "formal_window_manifest.json") == pre_state_hash("e4_v2_2_formal/formal_window_manifest.json")


# ---------------------------------------------------------------------------
# T3. Pair completeness（同一 (window,seed) 内主方法配对完整）
# ---------------------------------------------------------------------------
def test_t03_pair_completeness():
    recs = load_jsonl(FORMAL_DIR / "raw_records.jsonl")
    cells = {}
    for r in recs:
        cells.setdefault((r["dataset"], r["regime"], r["formal_window_id"], r["formal_seed"]), set()).add(r["method"])
    assert len(cells) == 310
    for ck, methods in cells.items():
        missing = [m for m in ALL_METHODS if m not in methods]
        assert not missing, "cell %s missing %s" % (ck, missing)


# ---------------------------------------------------------------------------
# T4. Window count（独立窗口数量 = manifest 完全一致）
# ---------------------------------------------------------------------------
def test_t04_window_count_matches_manifest():
    recs = load_jsonl(FORMAL_DIR / "raw_records.jsonl")
    wins_raw = {(r["dataset"], r["regime"], r["formal_window_id"]) for r in recs}
    man = json.load(open(FORMAL_DIR / "formal_window_manifest.json", encoding="utf-8"))
    wins_man = {(w["window_id"].split("_")[0], w["regime"], w["window_id"]) for w in man["windows"]}
    assert len(wins_man) == EXPECTED_WINDOWS
    assert len(wins_raw) == len(wins_man) == EXPECTED_WINDOWS
    # window_id 集合一致
    raw_ids = {w[2] for w in wins_raw}
    man_ids = {w[2] for w in wins_man}
    assert raw_ids == man_ids


# ---------------------------------------------------------------------------
# T5. Seed count（每个合法窗口 formal seed 数符合协议 = 10）
# ---------------------------------------------------------------------------
def test_t05_seed_count_per_window():
    recs = load_jsonl(FORMAL_DIR / "raw_records.jsonl")
    per_win = {}
    for r in recs:
        per_win.setdefault((r["dataset"], r["regime"], r["formal_window_id"]), set()).add(r["formal_seed"])
    for win, seeds in per_win.items():
        assert seeds == set(FORMAL_SEEDS), "window %s seeds %s" % (win, sorted(seeds))


# ---------------------------------------------------------------------------
# T6. No pseudo-replication（主要 bootstrap 输入观测数 = 窗口数，不是窗口×种子）
# ---------------------------------------------------------------------------
def test_t06_no_pseudo_replication_all():
    rows = load_csv(REANA_DIR / "window_level_bootstrap.csv")
    all_tssr = [r for r in rows if r["dataset"] == "ALL" and r["regime"] == "ALL" and r["metric"] == "tssr"]
    assert len(all_tssr) == len(BASELINES)
    for r in all_tssr:
        assert int(r["n_windows"]) == EXPECTED_WINDOWS, "bootstrap unit must be independent window, got %s" % r["n_windows"]
        assert int(r["n_windows"]) != EXPECTED_RUNS // 7  # 防止 window×seed 伪复制


# ---------------------------------------------------------------------------
# T7. Shanghai-HIGH guard（independent windows=1 -> CASE_LEVEL，不做推断）
# ---------------------------------------------------------------------------
def test_t07_shanghai_high_case_level():
    rows = load_csv(REANA_DIR / "window_level_bootstrap.csv")
    sub = [r for r in rows if r["dataset"] == "shanghai" and r["regime"] == "HIGH" and r["metric"] == "tssr"]
    assert sub and all(int(r["n_windows"]) == 1 for r in sub)
    assert all(r["evidence_level"] == "CASE_LEVEL_ONLY" for r in sub)
    # case-level：不允许 bootstrap CI
    assert all(r["ci_lo"] == "" and r["ci_hi"] == "" for r in sub)


# ---------------------------------------------------------------------------
# T8. Azure-LOW guard（无合法窗口 -> N/A，不得 fallback）
# ---------------------------------------------------------------------------
def test_t08_azure_low_na():
    ev = load_csv(REANA_DIR / "evidence_level_by_regime.csv")
    row = [r for r in ev if r["dataset"] == "azure" and r["regime"] == "LOW"]
    assert row and row[0]["n_windows"] == "0" and row[0]["evidence_level"] == "N/A"
    # 不 fallback：window-level bootstrap 中 azure/LOW 全部为空且 N/A
    rows = load_csv(REANA_DIR / "window_level_bootstrap.csv")
    sub = [r for r in rows if r["dataset"] == "azure" and r["regime"] == "LOW"]
    assert sub and all(r["evidence_level"] == "N/A" for r in sub)
    assert all(r["mean"] == "" for r in sub)


# ---------------------------------------------------------------------------
# T9. Bootstrap determinism（固定 seed 重复运行结果一致）
# ---------------------------------------------------------------------------
def test_t09_bootstrap_deterministic():
    from reanalyze_e4_window_level_statistics import percentile_bootstrap_ci
    sample = [0.2, 0.5, 0.4, 0.6, 0.3]
    a = percentile_bootstrap_ci(sample, resamples=5000, seed=12345)
    b = percentile_bootstrap_ci(sample, resamples=5000, seed=12345)
    assert a == b


# ---------------------------------------------------------------------------
# T10. Hierarchical structure（resample windows -> resample seeds within window）
# ---------------------------------------------------------------------------
def test_t10_hierarchical_two_level_structure():
    from reanalyze_e4_window_level_statistics import hierarchical_bootstrap_ci, percentile_bootstrap_ci
    # toy：2 窗口，窗口内 seeds 有变异
    win_seed = {"w1": [0.0, 0.4], "w2": [0.1, 0.5]}
    h = hierarchical_bootstrap_ci(win_seed, resamples=10000, seed=7)
    assert h is not None
    # window-level（仅窗口均值）bootstrap：hierarchical 额外保留窗口内随机性，CI 不应更窄
    win_means = [0.2, 0.3]
    w = percentile_bootstrap_ci(win_means, resamples=10000, seed=7)
    h_width = h["ci_hi"] - h["ci_lo"]
    w_width = w["ci_hi"] - w["ci_lo"]
    assert h_width >= w_width - 1e-9, "hierarchical must retain within-window variation (CI >= window-level CI)"
    # 必须不等于 flat resample 全部 run records（伪复制）：两层抽样结构与 flat 不同
    flat = [v for vs in win_seed.values() for v in vs]  # 4 个 run-level 观测（伪复制）
    rng_flat = __import__("random").Random(7)
    flat_means = []
    for _ in range(10000):
        s = sum(rng_flat.choice(flat) for _ in range(len(flat))) / len(flat)
        flat_means.append(s)
    flat_means.sort()
    f_lo, f_hi = flat_means[250], flat_means[9750]
    # hierarchical 对窗口内做聚合（抽 10 个平均），其 CI 应窄于把 4 个 run 当独立观测的 flat
    assert (f_hi - f_lo) > h_width, "hierarchical must not equal flat pseudo-replication"


# ---------------------------------------------------------------------------
# T11. Holm correction 可复现（手算对照）
# ---------------------------------------------------------------------------
def test_t11_holm_correction_manual():
    from reanalyze_e4_window_level_statistics import holm_adjust
    # 手算：p=[0.01,0.04,0.03,0.02,0.05]
    # 排序 0.01,0.02,0.03,0.04,0.05；step-down: 5*0.01=0.05, 4*0.02=0.08,
    # 3*0.03=0.09, 2*0.04=0.08, 1*0.05=0.05 -> 保序 max：0.05,0.08,0.09,0.09,0.09
    adj = holm_adjust([0.01, 0.04, 0.03, 0.02, 0.05])
    assert adj == [0.05, 0.09, 0.09, 0.08, 0.09]
    # 全矩阵 TSSR：主基线显著、NFA 不显著（从产物复核）
    rows = load_csv(REANA_DIR / "multiplicity_adjusted_tests.csv")
    all_tssr = [r for r in rows if r["dataset"] == "ALL" and r["regime"] == "ALL" and r["metric"] == "tssr"]
    d = {r["baseline"]: r for r in all_tssr}
    for b in ["bpso_rata_la", "jtora_adapted", "reliability_only", "local_only"]:
        assert float(d[b]["holm_adjusted_p"]) < 0.01
    assert float(d["nfa_adapted"]["holm_adjusted_p"]) >= 0.05


# ---------------------------------------------------------------------------
# T12. Manuscript number consistency（当前 III_VII.md Trace 实验编号全文一致）
# ---------------------------------------------------------------------------
def test_t12_manuscript_trace_experiment_number_consistent():
    text = MANUSCRIPT.read_text(encoding="utf-8")
    # Trace-Enhanced 正文当前编号为 E3（真实 Trace 增强）；E4 为 Exact-Oracle
    assert "## E3. 真实 Trace 增强下的外部有效性评估" in text
    assert "## E4. 小规模精确最优参照" in text
    # E3 章节内的图表引用编号一致
    e3_start = text.index("## E3. 真实 Trace 增强下的外部有效性评估")
    e4_start = text.index("## E4. 小规模精确最优参照")
    e3_body = text[e3_start:e4_start]
    assert "Fig E3-1" in e3_body and "Fig E3-2" in e3_body
    assert "表 E3-1" in e3_body or "Table E3-1" in e3_body
    # 不得残留旧 Trace-Enhanced 编号为 E4 的引用（本实验正文内）
    assert "## E4. 真实 Trace" not in text
    assert "Fig E4-1" not in e3_body and "Fig E4-2" not in e3_body


# ---------------------------------------------------------------------------
# T13. Claim boundary（正文不得出现禁 Claim 表述）
# ---------------------------------------------------------------------------
def test_t13_claim_boundary_no_prohibited():
    text = MANUSCRIPT.read_text(encoding="utf-8")
    e3_start = text.index("## E3. 真实 Trace 增强下的外部有效性评估")
    e4_start = text.index("## E4. 小规模精确最优参照")
    e3_body = text[e3_start:e4_start]
    prohibited = [
        "real MEC deployment", "production deployment", "production validation",
        "real-world MEC validation", "universally superior", "真实 MEC 生产",
        "生产环境验证", "普遍优于", "真实在线平台验证", "真实 MEC 部署验证",
    ]
    for p in prohibited:
        assert p.lower() not in e3_body.lower(), "prohibited claim: %s" % p
    # Trace 定位仍为 semi-synthetic / trace-enhanced
    assert "trace-enhanced" in e3_body.lower() or "trace 增强" in e3_body
    assert "半合成" in e3_body or "semi-synthetic" in e3_body.lower()


# ---------------------------------------------------------------------------
# T14. No formal rerun（本阶段算法 invocation = 0；raw 未被重写）
# ---------------------------------------------------------------------------
def test_t14_no_formal_rerun():
    src = (SCRIPT_ROOT / "reanalyze_e4_window_level_statistics.py").read_text(encoding="utf-8")
    # 脚本不得运行算法 / 调用 runner / subprocess
    assert "subprocess" not in src
    assert "run_e4_v2_2_formal" not in src
    assert "import subprocess" not in src
    integ = json.load(open(REANA_DIR / "integrity.json", encoding="utf-8"))
    assert integ["formal_rerun"] == "NO"
    assert integ["raw_modified"] == "NO"
    assert integ["formal_seeds_rerun"] == "NO"
    # raw 与 manifest hash 与 pre-state 一致（未被脚本触碰）
    assert sha256_file(FORMAL_DIR / "raw_records.jsonl") == pre_state_hash("e4_v2_2_formal/raw_records.jsonl")
    assert sha256_file(FORMAL_DIR / "formal_window_manifest.json") == pre_state_hash("e4_v2_2_formal/formal_window_manifest.json")


# ---------------------------------------------------------------------------
# T15. Data immutability（processed Trace 文件 hash 不变）
# ---------------------------------------------------------------------------
def test_t15_trace_data_immutable():
    pre = json.load(open(REANA_DIR / "pre_state_hashes.json", encoding="utf-8"))["hashes"]
    assert pre.get("e4_trace_enhanced_file_count") == 19
    for k, v in pre.items():
        if k.startswith("trace/"):
            rel = k[len("trace/"):]
            assert sha256_file(TRACE_ROOT / rel) == v, "trace file changed: %s" % rel


# ---------------------------------------------------------------------------
# 人工微型案例（Step 12）
# ---------------------------------------------------------------------------
def test_manual_micro_case_two_windows_three_seeds():
    """2 windows × 3 seeds/window × 2 methods。

    Window A: CARS−baseline Δ = {0.1, 0.2, 0.3} -> mean 0.2
    Window B: Δ = {0.4, 0.5, 0.6} -> mean 0.5
    Overall window-level mean = 0.35
    """
    win_a = [0.1, 0.2, 0.3]
    win_b = [0.4, 0.5, 0.6]
    assert abs(sum(win_a) / 3 - 0.2) < 1e-9
    assert abs(sum(win_b) / 3 - 0.5) < 1e-9
    overall = (sum(win_a) / 3 + sum(win_b) / 3) / 2
    assert abs(overall - 0.35) < 1e-9
    # 用脚本核心函数复核：window-level mean + bootstrap mean 一致
    from reanalyze_e4_window_level_statistics import percentile_bootstrap_ci
    boot = percentile_bootstrap_ci([0.2, 0.5], resamples=10000, seed=99)
    assert abs(boot["mean"] - 0.35) < 1e-9
    assert boot["ci_lo"] == pytest.approx(0.2, abs=0.05)
    assert boot["ci_hi"] == pytest.approx(0.5, abs=0.05)


def test_manual_micro_case_single_window_case_level():
    """1 window × 10 seeds：必须判定 CASE_LEVEL_ONLY，不能输出跨窗口推断 Claim。"""
    from reanalyze_e4_window_level_statistics import run_window_level_analysis
    deltas = {("shanghai", "HIGH", "nfa_adapted", "tssr"): {
        "sh_win_1": [0.0, 0.01, -0.005, 0.0, 0.02, 0.0, 0.01, -0.01, 0.005, 0.0]}}
    rows = run_window_level_analysis(deltas)
    r = [x for x in rows if x["dataset"] == "shanghai" and x["regime"] == "HIGH"
         and x["baseline"] == "nfa_adapted" and x["metric"] == "tssr"][0]
    assert r["n_windows"] == 1
    assert r["evidence_level"] == "CASE_LEVEL_ONLY"
    assert r["ci_lo"] == "" and r["ci_hi"] == ""
    # 手算窗口均值 = 0.003
    assert abs(float(r["mean"]) - 0.003) < 1e-9
