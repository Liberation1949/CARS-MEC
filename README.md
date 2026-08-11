# CARS

**CARS: Capacity-Aware Reliability Stabilization via Assignment–Allocation Coordination in Multi-User Mobile Edge Computing**

CARS（Capacity-Aware Reliability Stabilization Framework）是面向多用户移动边缘计算（MU-MEC）的可靠性感知在线调度框架：在离散指派阶段感知下游资源竞争，在连续资源分配阶段显式保障任务级可靠性资源需求。核心方法链为 **AADA → RCLA**。

CARS (Capacity-Aware Reliability Stabilization Framework) is a reliability-aware online scheduling framework for multi-user mobile edge computing (MU-MEC): the discrete assignment stage senses downstream resource contention, and the continuous resource-allocation stage explicitly enforces task-level reliability resource requirements. The core method chain is **AADA → RCLA**.

本仓库是论文的公开复现实现（Paper Release, v1.0.1），包含正式算法实现、统一模拟器与评价器、六个对比方法、Small-Scale Exact Oracle、V4 Active Schema、正式实验协议与复现脚本、轻量机器可读参考结果摘要。

This repository is the public reproduction implementation of the paper (Paper Release, v1.0.1), including the formal algorithm implementations, a unified simulator and evaluator, six comparison methods, a Small-Scale Exact Oracle, the V4 Active Schema, formal experiment protocols with reproduction scripts, and lightweight machine-readable reference-result summaries.

---

## Overview 概述

多用户 MEC 中，任务卸载、任务—服务器指派与计算资源分配三类决策紧密耦合。CARS 面向 TSSR 优先的三层字典序优化问题（P0），实现确定性快照式在线调度（snapshot-based online scheduling）与可靠性感知资源分配（reliability-aware resource allocation）：任务成功只取决于可靠性（无 deadline 模型）；负载通过有限资源竞争影响任务可获得资源、时延与可靠性，不改变服务器名义故障率。

In multi-user MEC, task offloading, task–server assignment, and computational resource allocation are tightly coupled decisions. CARS targets the three-level lexicographic optimization problem (P0) with TSSR priority, implementing deterministic snapshot-based online scheduling and reliability-aware resource allocation: task success depends only on reliability (no deadline model); load affects a task's obtainable resources, latency, and reliability through competition for finite computational resources, without changing the nominal server failure rates.

## Method 方法

Current CARS 包含两个核心算法模块：

Current CARS consists of two core algorithmic modules:

1. **AADA（Allocation-Aware Dynamic Assignment，分配感知动态指派）**——离散指派阶段维护动态服务器状态，通过分配感知边际代价感知下游资源竞争，以可执行成功下限准入避免接纳容量无法承接的任务，优先救援本地可靠性不足的任务，并对本地已成功任务执行保持成功的字典序精化；
   **AADA (Allocation-Aware Dynamic Assignment)** — the discrete assignment stage maintains dynamic server states, senses downstream resource competition through allocation-aware marginal costs, admits tasks using an executable success floor to avoid accepting tasks the capacity cannot sustain, prioritizes rescuing tasks with insufficient local reliability, and applies a lexicographic refinement that preserves success for locally successful tasks;

2. **RCLA（Reliability-Constrained Lagrangian Allocation，可靠性约束拉格朗日分配）**——固定指派下求解连续资源分配，显式引入任务级可执行可靠性下限，通过 KKT/active-set 结构确定资源分配，在可靠性下限不激活时退化为普通拉格朗日分配。
   **RCLA (Reliability-Constrained Lagrangian Allocation)** — solves the continuous resource allocation under a fixed assignment, explicitly introduces task-level executable reliability floors, determines the allocation through KKT/active-set structure, and degrades to plain Lagrangian allocation when the reliability floors are not active.

```text
No GNN.
No independent Repair layer.
```

Exact Oracle（小规模精确参照）是评估支持工具，不是在线管线的一部分（见 [Exact Oracle](#exact-oracle)）。

The Exact Oracle (small-scale exact reference) is an evaluation-support tool, not part of the online pipeline (see [Exact Oracle](#exact-oracle)).

## Repository Structure 仓库结构

```text
CARS/
├── README.md
├── LICENSE
├── CHANGELOG.md
├── CITATION.cff.template
├── pyproject.toml
├── requirements.txt
├── .gitignore
├── src/cars/
│   ├── common/          # 确定性工具 / deterministic utilities
│   ├── evaluator/       # 统一 Evaluator（TSSR / Rbar_eff / Ubar_eff / V_R 等）/ unified evaluator
│   ├── simulator/       # 物理模型、场景 materializer、T0 派生状态 / physical models, scenario materializer, T0 derived state
│   ├── runner/          # MethodRunner / worker（统一执行边界与超时）/ unified execution boundary and timeout
│   ├── results/         # Canonical Result
│   ├── exact_oracle/    # Small-Scale Exact Oracle（评估支持工具 / evaluation support）
│   └── methods/
│       ├── cars/        # 正式 CARS：AADA + RCLA / formal CARS
│       ├── bpso_rata_la/  # 强 Baseline（independent reimplementation）
│       ├── jtora_adapted/ # 强 Baseline（independent reimplementation）
│       ├── nfa_adapted/   # 强 Baseline（independent reimplementation）
│       ├── reliability_only.py / local_only.py / foa.py
├── configs/             # 正式实验协议与环境冻结 / formal protocols and environment freezes
├── schemas/CARS_ACTIVE_SCHEMA_V4/   # Active Schema V4
├── scripts/
│   ├── quick_start.py
│   └── reproduce/       # 各实验 run / aggregate / check 脚本
├── tests/               # 测试套件 / test suite
├── docs/                # REPRODUCIBILITY / DATA / BASELINES
├── reference_results/   # 轻量机器可读参考结果摘要 / lightweight reference summaries
└── data/                # 数据说明（本仓库不随附第三方数据）/ data notes (no third-party data bundled)
```

## Installation 安装

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    Unix/macOS: source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

测试/复现可选依赖：`python -m pip install -e ".[test]"`（pytest、matplotlib）。

Optional dependencies for testing/reproduction: `python -m pip install -e ".[test]"` (pytest, matplotlib).

## Quick Start 快速开始

```bash
python scripts/quick_start.py
```

使用仓库内置确定性微型场景运行 CARS 主流程并经统一 Evaluator 评价。典型输出字段：

Runs the CARS main pipeline on a built-in deterministic micro-scenario and evaluates it with the unified evaluator. Typical output fields:

```text
seed           201
status         SUCCESS
TSSR           1.0
Rbar_eff       ...
Ubar_eff       ...
runtime_seconds ...
fingerprint    <deterministic 16-hex hash>
```

`fingerprint` 为完整决策 (X, A, F) 的确定性 SHA-256 摘要；同一 seed 连续运行应产生完全一致的 fingerprint（确定性）。运行时间随硬件变化，不构成性能保证。

`fingerprint` is the deterministic SHA-256 digest of the full decision (X, A, F); repeated runs with the same seed must produce an identical fingerprint (determinism). Runtime varies with hardware and is not a performance guarantee.

## Reproducibility 复现

复现分为三个层级（详见 [docs/REPRODUCIBILITY.md](docs/REPRODUCIBILITY.md)）：

Reproducibility is organized into three levels (see [docs/REPRODUCIBILITY.md](docs/REPRODUCIBILITY.md)):

- **Level A — Fully self-contained（无需任何外部数据 / no external data needed）**：Quick Start、合成场景、CARS、六 Baseline、Schema V4、微型 Exact Oracle；
- **Level B — Public-code reproducible**：代表性实验管线（`scripts/reproduce/`，run/aggregate/check），可直接运行；
- **Level C — External-data dependent**：Trace 增强实验（需要第三方 Trace 数据，见 [Data Availability](#data-availability)）。

## Experiments 实验

正式实验脚本按实验组织于 `scripts/reproduce/<experiment>/`。完整复现说明与范围见 [docs/REPRODUCIBILITY.md](docs/REPRODUCIBILITY.md)。

Formal experiment scripts are organized by experiment under `scripts/reproduce/<experiment>/`. Full reproduction notes and scope are in [docs/REPRODUCIBILITY.md](docs/REPRODUCIBILITY.md).

## Baselines 基线

六个对比方法：BPSO-RATA-LA、JTORA-adapted、NFA-adapted（强 Baseline，**independent reimplementation**，非官方实现）、reliability_only、local_only（弱 Baseline）、FOA（边界诊断）。每个方法的来源、忠实组件、项目适配、省略部分、参数/搜索预算与公平边界见 [docs/BASELINES.md](docs/BASELINES.md)。

Six comparison methods: BPSO-RATA-LA, JTORA-adapted, NFA-adapted (strong baselines, **independent reimplementations**, not official implementations), reliability_only and local_only (weak baselines), and FOA (boundary diagnostic). Per-method source, faithful components, project adaptations, omitted parts, parameter/search budget, and fairness boundary are documented in [docs/BASELINES.md](docs/BASELINES.md).

## Exact Oracle

`src/cars/exact_oracle/` 提供**小规模**实例的可审计精确最优参照（有限离散枚举 + 每服务器 KKT/active-set 连续求解，输出数值精确证书）。**Exact Oracle 不是在线 CARS，也不是可扩展的通用求解器**——仅适用于极小规模实例（论文正式评估包络 N∈{4,5,6}、M=4），不声称对大规模实例可计算。

`src/cars/exact_oracle/` provides an auditable exact-optimal reference for **small-scale** instances (finite discrete enumeration plus per-server KKT/active-set continuous solving, emitting numerical exactness certificates). **The Exact Oracle is not the online CARS, nor a scalable general-purpose solver** — it applies only to very small instances (the paper's formal evaluation envelope N∈{4,5,6}, M=4) and makes no claim of computability at large scale.

## Data Availability 数据可用性

本仓库**不随附任何第三方原始或处理 Trace 数据**（Microsoft Azure Functions Trace 2019、NEP Edge Workloads Traces、Shanghai Telecom Mobile Internet Access Trace）。用户需自行从原始提供方获取（官方获取方式以数据集提供方为准）。期望目录结构与 `CARS_DATA_ROOT` 占位符说明见 [docs/DATA.md](docs/DATA.md)。数据缺失时相关入口会返回明确的 `DATA_NOT_AVAILABLE` 信息。Trace 增强实验属于 trace-enhanced / semi-synthetic 证据，非真实 MEC 生产部署验证。

This repository does **not bundle any third-party raw or processed Trace data** (Microsoft Azure Functions Trace 2019, NEP Edge Workloads Traces, Shanghai Telecom Mobile Internet Access Trace). Users must obtain the data themselves from the original providers (official access follows each dataset provider). Expected directory layout and the `CARS_DATA_ROOT` placeholder are described in [docs/DATA.md](docs/DATA.md). When data is missing, the relevant entry points return an explicit `DATA_NOT_AVAILABLE` message. Trace-enhanced experiments are trace-enhanced / semi-synthetic evidence, not real MEC production-deployment validation.

## Test Suite 测试套件

```bash
pytest -q
```

干净公开环境（fresh clone + fresh venv）下的实测结果：

Measured result in a clean public environment (fresh clone + fresh venv):

```text
217 passed
152 skipped
0 failed
```

**152 skipped 是已解释的、预期的**：公开仓库有意不重新分发第三方 Trace 数据、全量正式结果归档、以及内部正文/合同完整性资产；对应测试在缺少这些资产时明确跳过（见 `tests/conftest.py` 中的说明）。核心 CARS / Baseline / Schema / Quick Start / Oracle 测试均已实际运行通过。禁止将结果表述为 "all 369 tests passed"。

**The 152 skipped are explained and expected**: the public repository intentionally does not redistribute third-party Trace data, full formal-result archives, or internal manuscript/contract integrity assets; the corresponding tests explicitly skip when these assets are absent (see notes in `tests/conftest.py`). All core CARS / Baseline / Schema / Quick Start / Oracle tests have actually run and passed. It is prohibited to report the result as "all 369 tests passed".

## Reference Results 参考结果

`reference_results/` 提供各正式实验的**轻量机器可读聚合摘要**（来源与内容见 [reference_results/README.md](reference_results/README.md)），**不是全量 raw formal archive**，也不应作为实验输入数据。

`reference_results/` provides **lightweight machine-readable aggregate summaries** of each formal experiment (source and content in [reference_results/README.md](reference_results/README.md)); it is **not a full raw formal archive** and should not be used as experiment input data.

## Citation 引用

作者与论文引用信息待作者确认后填入 [CITATION.cff.template](CITATION.cff.template)。

Author and citation information will be filled into [CITATION.cff.template](CITATION.cff.template) once confirmed by the authors.

## License 许可证

MIT License，见 [LICENSE](LICENSE)。

MIT License, see [LICENSE](LICENSE).

## Reproducibility Scope and Limitations 复现范围与限制

- 无 GNN、无独立 Repair 层、无 deadline 模型； / No GNN, no independent Repair layer, no deadline model;
- Exact Oracle 仅覆盖论文正式包络（N∈{4,5,6}、M=4、LOW/TRANSITION、固定 formal seeds），不外推更大规模； / The Exact Oracle covers only the paper's formal envelope (N∈{4,5,6}, M=4, LOW/TRANSITION, fixed formal seeds) and does not extrapolate to larger scales;
- Trace 数据不随仓库分发；Trace 增强实验为 semi-synthetic / trace-enhanced 证据，非真实 MEC 生产部署验证； / Trace data is not distributed with the repository; Trace-enhanced experiments are semi-synthetic / trace-enhanced evidence, not real MEC production-deployment validation;
- 负载诱导服务退化（LISC）为可能出现的经验形态，非本文问题的理论前提；当前评估范围内观察到的是 ordinary degradation； / Load-induced service collapse (LISC) is a possible empirical form, not a theoretical premise of this problem; ordinary degradation is what is observed in the current evaluation scope;
- 全量正式结果与阶段内部报告不随本公开仓库分发；`reference_results/` 仅含轻量摘要。 / Full formal results and internal stage reports are not distributed with this public repository; `reference_results/` contains only lightweight summaries.
