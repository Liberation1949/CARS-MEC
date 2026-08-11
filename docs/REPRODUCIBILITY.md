# Reproducibility 复现说明

本文档说明如何复现 CARS 正式实验，以及复现的范围与边界。

This document explains how to reproduce the CARS formal experiments, and the scope and boundaries of reproduction.

## 1. 环境 Environment

- Python ≥ 3.9（开发与正式验证使用 Python 3.9）； / Python ≥ 3.9 (development and formal verification used Python 3.9);
- 运行时依赖：PyYAML、jsonschema（见 `requirements.txt` / `pyproject.toml`）； / runtime dependencies: PyYAML, jsonschema (see `requirements.txt` / `pyproject.toml`);
- 测试与出图依赖：pytest、matplotlib（可选，`[project.optional-dependencies] test/reproduce`）。 / testing and plotting dependencies: pytest, matplotlib (optional, `[project.optional-dependencies] test/reproduce`).

```bash
python -m pip install -e .
```

## 2. 确定性 Determinism

所有随机过程显式接收 seed。同一「代码版本 + 配置 + 数据划分 + seed + 环境」应产生相同的离散决策、状态与规范化结果记录；浮点结果按契约冻结容差比较。正式实验中 training / validation(pilot) / formal-test 数据划分互斥；formal-test 禁止用于选参。

All stochastic processes explicitly take a seed. The same combination of code version + config + data split + seed + environment must produce identical discrete decisions, states, and normalized result records; floating-point results are compared using the contract-frozen tolerance. In formal experiments the training / validation (pilot) / formal-test splits are mutually exclusive; formal-test must not be used for parameter selection.

## 3. 快速验证 Quick Verification

```bash
python scripts/quick_start.py
```

输出单实例决策与 TSSR / Rbar_eff / Ubar_eff / runtime / 确定性指纹。

Outputs a single-instance decision with TSSR / Rbar_eff / Ubar_eff / runtime / deterministic fingerprint.

## 4. 正式实验复现 Formal Experiment Reproduction

正式实验脚本位于 `scripts/reproduce/<experiment>/`。每个实验包含：环境构建（`build_*_environment.py`）、Pilot/Formal 运行（`run_*_pilot.py` / `run_*_formal.py`）、聚合与统计（`aggregate_*.py`）、完整性检查（`check_*_integrity.py`）。

Formal experiment scripts live under `scripts/reproduce/<experiment>/`. Each experiment includes: environment construction (`build_*_environment.py`), pilot/formal runs (`run_*_pilot.py` / `run_*_formal.py`), aggregation and statistics (`aggregate_*.py`), and integrity checks (`check_*_integrity.py`).

| 实验 Experiment | 脚本目录 Script directory | 是否需要外部 Trace External Trace needed |
|------|---------|-------------------|
| E0 负载诱导服务退化与机制表征 / load-induced degradation & mechanism | `scripts/reproduce/e0_v2/` | 否 / No |
| E1 任务规模与异构资源下的性能评估 / performance vs scale & heterogeneity | `scripts/reproduce/e1_v2/`（规模）+ `e2_v2/`（异构） | 否 / No |
| E2 组件消融与机制分析 / component ablation | `scripts/reproduce/e3_v2/` | 否 / No |
| E3 Trace 增强外部有效性评估 / Trace-enhanced external validity | `scripts/reproduce/e4_v2/` | 是 / Yes（见 docs/DATA.md） |
| E4 小规模精确最优参照（Exact Oracle）/ small-scale exact reference | `scripts/reproduce/e4_exact/` | 否 / No |

**formal-test seed 守卫**：正式运行脚本带有 `--authorize-formal-seeds` 授权守卫（例如 `run_e4_exact_3_formal.py`、`run_e4_v2_2_formal.py`）。只有显式授权后才访问 formal-test seed 分区；Pilot/校准使用独立 seed 分区。

**formal-test seed guard**: formal run scripts carry an `--authorize-formal-seeds` authorization guard (e.g. `run_e4_exact_3_formal.py`, `run_e4_v2_2_formal.py`). The formal-test seed partition is only accessed after explicit authorization; pilot/calibration use a separate seed partition.

## 5. 配置 Configuration

正式协议与环境冻结位于 `configs/`：

Formal protocols and environment freezes live under `configs/`:

- `cars_v4/`：正式 CARS 方法配置（AADA→RCLA）； / formal CARS method config (AADA→RCLA);
- `e0_v2/`、`e1_v2/`、`e2_v2/`、`e3_v2/`、`e3_formal/`：E0–E2 与消融环境/协议； / E0–E2 and ablation environments/protocols;
- `e4_v2/`：Trace 增强协议、字段映射、环境选择（含 `${CARS_DATA_ROOT}` 占位）； / Trace-enhanced protocol, field mapping, environment selection (with the `${CARS_DATA_ROOT}` placeholder);
- `e4_exact/`：Exact Oracle 求解器与正式协议（N-grid、timeout、预算）； / Exact Oracle solver and formal protocol (N-grid, timeout, budget);
- `r6/frozen_method_configs/`：六个 Baseline 的 frozen 配置。 / frozen configs of the six baselines.

## 7. 复现层级 Reproduction Levels

复现分为三个层级：

Reproduction is organized into three levels:

- **Level A — Fully self-contained（无需任何外部数据 / no external data needed）**：Quick Start（`python scripts/quick_start.py`）、合成场景、CARS（AADA→RCLA）、六个 Baseline、Schema V4 验证、微型 Exact Oracle——全部可直接复现；
- **Level B — Public-code reproducible**：代表性实验管线（`scripts/reproduce/` 中各 run/aggregate/check 脚本）可直接运行，不依赖外部数据；
- **Level C — External-data dependent**：Trace 增强实验（`scripts/reproduce/e4_v2/`）需要第三方 Trace 数据（见 docs/DATA.md），数据缺失时入口返回 `DATA_NOT_AVAILABLE`。

## 8. 测试套件 Test Suite

```bash
pytest -q
```

干净公开环境（fresh clone + fresh venv）实测：**217 passed / 152 skipped / 0 failed**。152 个 skip 为已解释的外部资产依赖（第三方 Trace 数据、全量正式结果归档、内部正文/合同完整性资产不随本公开仓库分发）；核心 CARS / Baseline / Schema / Quick Start / Oracle 测试均实际运行通过。

Measured in a clean public environment (fresh clone + fresh venv): **217 passed / 152 skipped / 0 failed**. The 152 skips are explained external-asset dependencies (third-party Trace data, full formal-result archives, and internal manuscript/contract integrity assets are not distributed with this public repository); all core CARS / Baseline / Schema / Quick Start / Oracle tests have actually run and passed.

## 9. 参考结果 Reference Results

`reference_results/` 提供各正式实验的轻量机器可读聚合摘要（数值全部来自既有正式结果，不重新计算 Claim、不重跑实验），**不是全量 raw formal archive**。完整逐实例结果不随本公开仓库分发；不建议把 reference_results 作为实验输入数据。

`reference_results/` provides lightweight machine-readable aggregate summaries of each formal experiment (all values come from existing formal results; claims are not recomputed and experiments are not rerun). It is **not a full raw formal archive**. Full per-instance results are not distributed with this public repository; reference_results should not be used as experiment input data.

## 10. 复现范围与限制 Reproduction Scope and Limitations

- CARS 由 AADA（离散指派）与 RCLA（连续资源分配）两个模块组成，任务成功仅取决于可靠性、不引入 deadline 模型； / CARS consists of two modules, AADA (discrete assignment) and RCLA (continuous resource allocation); task success depends only on reliability, with no deadline model;
- Exact Oracle 仅适用于极小规模（论文正式评估实例 N∈{4,5,6}、M=4），不声称对大规模实例可计算，不是在线 CARS 或可扩展通用求解器； / The Exact Oracle applies only to very small instances (the paper's formal evaluation N∈{4,5,6}, M=4), makes no claim of computability at large scale, and is not the online CARS nor a scalable general-purpose solver;
- Trace 增强实验为 semi-synthetic / trace-enhanced 证据，非真实 MEC 生产部署验证； / Trace-enhanced experiments are semi-synthetic / trace-enhanced evidence, not real MEC production-deployment validation;
- 负载通过有限资源竞争影响任务可获得资源、时延与可靠性，不直接改变服务器物理故障率；本文结论仅对评估的场景范围有效； / Load affects a task's available resources, latency, and reliability through competition for finite computational resources, without directly changing server physical failure rates; the paper's conclusions hold only within the evaluated scenario scope;
- 硬件/环境差异可能影响运行时间，但不影响确定性决策与规范化结果（浮点按契约容差比较）；同 seed 的 `fingerprint`（决策 (X,A,F) 的确定性 SHA-256 摘要）应完全一致。 / Hardware/environment differences may affect runtime but not deterministic decisions and normalized results (floating point is compared at contract tolerance); the `fingerprint` for the same seed (deterministic SHA-256 digest of decision (X,A,F)) must be identical.
