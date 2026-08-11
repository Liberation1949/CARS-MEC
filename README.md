# CARS — Capacity-Aware Reliability Stabilization Framework

面向多用户移动边缘计算（MEC）的可靠性感知在线调度框架，核心方法链为 **AADA → RCLA**。

本仓库是论文的公开复现实现（Release Candidate），包含：正式算法实现（AADA + RCLA）、统一模拟器与评价器、六个对比 Baseline、Small-Scale Exact Oracle、V4 Active Schema、正式实验协议与脚本、以及轻量机器可读的参考结果摘要。

---

## 1. CARS 简介

CARS（Capacity-Aware Reliability Stabilization Framework）面向多用户 MEC 中任务卸载、任务—服务器指派与计算资源分配三类决策的耦合问题。其核心洞察是：可靠性感知调度不应只依据服务器名义可靠性或静态匹配关系作出指派，而应在离散指派阶段感知其对下游资源竞争的影响，并在连续资源分配阶段显式保障任务级可靠性资源需求。

CARS 是面向 TSSR 优先字典序问题的**确定性快照式在线调度启发式**，不是问题的全局精确求解器。

## 2. Paper / Research Scope

- 问题：有限共享容量下多用户 MEC 的可靠性感知卸载、指派与资源分配耦合；
- 语义：任务成功只取决于可靠性（无 deadline 模型）；负载通过有限资源竞争影响任务可获得资源、时延与可靠性，不改变服务器名义故障率 λ_j；
- 目标：TSSR 优先的三层字典序优化问题 P0（TSSR, Rbar_eff, Ubar_eff），并证明其至少为 NP-hard；
- 现象：负载诱导服务退化（LISC 为可能出现的经验形态，非理论前提）。

## 3. Method Overview: AADA → RCLA

- **AADA（Allocation-Aware Dynamic Assignment，分配感知动态指派）**：离散指派阶段维护动态服务器状态，通过分配感知边际代价感知下游资源竞争，以可执行成功下限准入避免接纳容量无法承接的任务，优先救援本地可靠性不足的任务，并对本地已成功任务执行保持成功的字典序精化；
- **RCLA（Reliability-Constrained Lagrangian Allocation，可靠性约束拉格朗日分配）**：固定指派下求解连续资源分配，显式引入任务级可执行可靠性下限，通过 KKT/active-set 结构确定资源分配，在可靠性下限不激活时退化为普通拉格朗日分配。

```text
T0 Scenario + DerivedState
        → AADA (assignment: X, A)
        → RCLA (allocation: F)
        → full plan Π = (X, A, F)
        → unified Evaluator (TSSR, Rbar_eff, Ubar_eff, ...)
```

- 无 GNN、无训练、无 Repair 层、无 deadline 模型；
- 服务器可靠性为固定名义故障率 λ_j（负载不直接改变物理故障率）。

## 4. Repository Structure

```text
CARS_Public/
├── README.md
├── LICENSE
├── CITATION.cff.template
├── pyproject.toml
├── requirements.txt
├── .gitignore
├── src/cars/
│   ├── common/          # 确定性工具（哈希、比较）
│   ├── evaluator/       # 统一 Evaluator（TSSR/Rbar_eff/Ubar_eff/V_R 等）
│   ├── simulator/       # 物理模型、场景 materializer、T0 派生状态
│   ├── runner/          # MethodRunner / worker（统一执行边界与超时）
│   ├── results/         # Canonical Result
│   ├── exact_oracle/    # Small-Scale Exact Oracle（评估支持工具）
│   └── methods/
│       ├── cars/        # 正式 CARS：AADA + RCLA
│       ├── bpso_rata_la/  # 强 Baseline（重实现）
│       ├── jtora_adapted/ # 强 Baseline（重实现）
│       ├── nfa_adapted/   # 强 Baseline（重实现）
│       ├── reliability_only.py / local_only.py / foa.py
├── configs/             # 正式实验协议与环境冻结（cars_v4 / e0_v2–e4_v2 / e4_exact / frozen baselines）
├── schemas/CARS_ACTIVE_SCHEMA_V4/   # Active Schema V4
├── scripts/
│   ├── quick_start.py
│   └── reproduce/       # 各实验的 run/aggregate/check 脚本
├── tests/               # 正式阶段冻结测试
├── docs/                # REPRODUCIBILITY / DATA / BASELINES
├── reference_results/   # 轻量机器可读参考结果摘要
└── data/                # 数据说明（本仓库不随附第三方数据）
```

## 5. Installation

要求 Python ≥ 3.9（开发与验证使用 Python 3.9）。

```bash
python -m pip install -e .
# 或仅运行时依赖
python -m pip install -r requirements.txt
```

## 6. Quick Start

```bash
python -m pip install -e .
python scripts/quick_start.py
```

`quick_start.py` 使用仓库内置的确定性微型场景，运行 CARS 主流程并经统一 Evaluator 评价，输出 seed / status / TSSR / Rbar_eff / Ubar_eff / runtime 与确定性结果指纹。

## 7. Reproducing Experiments

正式实验按实验编号组织于 `scripts/reproduce/<experiment>/`（run 脚本 + aggregate + integrity check）。完整复现流程、环境说明与范围见 [docs/REPRODUCIBILITY.md](docs/REPRODUCIBILITY.md)。复现需要外部数据集的实验见 [docs/DATA.md](docs/DATA.md)。

## 8. Baselines

六个 Baseline 与详细说明见 [docs/BASELINES.md](docs/BASELINES.md)：

- 强 Baseline：BPSO-RATA-LA、JTORA-adapted、NFA-adapted（独立重实现，非第三方源码复制）；
- 弱 Baseline：reliability_only、local_only；
- 边界诊断：FOA。

## 9. Data Availability

本仓库**不随附任何第三方原始/处理 Trace 数据**（Azure Functions Trace 2019、NEP Edge Workloads Traces、Shanghai Telecom Mobile Internet Access Trace）。数据获取说明与期望目录结构见 [docs/DATA.md](docs/DATA.md)。Trace 增强实验属于 trace-enhanced / semi-synthetic 证据。

## 10. Exact Oracle

`src/cars/exact_oracle/` 提供小规模实例的可审计精确最优参照（Route A：有限离散枚举 + 每服务器 KKT/active-set 连续求解，输出数值精确证书）。**Exact Oracle 是评估支持工具，不是 CARS 在线管线的一部分**；它只适用于极小规模实例（正式评估 N∈{4,5,6}, M=4），不声称对大规模实例可计算。

## 11. Expected Outputs

- `quick_start.py`：单实例决策与指标；
- `reference_results/`：各正式实验的轻量聚合摘要（数值全部来自既有正式结果，不重新计算 Claim）；
- 复现脚本：按 `scripts/reproduce/<experiment>/` 生成完整逐实例结果。

## 12. Citation

作者信息与论文引用待作者确认后填入 `CITATION.cff.template`（见 [CITATION.cff.template](CITATION.cff.template)）。

## 13. License

MIT License，见 [LICENSE](LICENSE)。

## 14. Reproducibility Scope / Limitations

- 无 GNN、无 Repair、无 deadline 模型；
- Exact Oracle 仅覆盖 N∈{4,5,6}、M=4、LOW/TRANSITION、固定 formal seeds 包络，不外推更大规模；
- Trace 数据不随仓库分发；Trace 增强实验为 semi-synthetic / trace-enhanced 证据，非真实 MEC 生产部署验证；
- 全量结果与阶段内部报告不随本公开仓库分发；`reference_results/` 仅含轻量摘要。
