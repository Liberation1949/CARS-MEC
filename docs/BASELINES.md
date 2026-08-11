# Baselines 基线

本文档说明公开仓库中六个对比 Baseline 的来源、重实现性质、忠实组件、项目适配、省略部分、参数/搜索预算与公平边界。所有信息基于项目内部记录的 adaptation contracts 与正式代码。

This document explains the sources, reimplementation nature, faithful components, project adaptations, omitted parts, parameter/search budgets, and fairness boundaries of the six comparison baselines in the public repository. All information is based on the project's internal adaptation-contract records and the formal code.

三个强 Baseline 均为**独立重实现**（source-aligned, project-adapted），不是第三方源码的直接复制；三个强 Baseline 的原始论文 PDF（`references/*.pdf`）受版权保护，**不随本公开仓库分发**（仅保留书目引用）。

The three strong baselines are all **independent reimplementations** (source-aligned, project-adapted), not direct copies of third-party source code; the original paper PDFs of the three strong baselines (`references/*.pdf`) are copyrighted and **not distributed with this public repository** (only bibliographic citations are kept).

---

## 1. 强 Baseline：BPSO-RATA-LA Strong Baseline

- **Reference 参考文献**：BPSO-RATA-LA 论文（MU-MEC 卸载与调度；BPSO 搜索卸载决策 + RATA 指派 + LA 资源分配）。 / BPSO-RATA-LA paper (MU-MEC offloading and scheduling; BPSO searches offloading decisions + RATA assigns + LA allocates resources).
- **Independent reimplementation 独立重实现**：是 / Yes（source-aligned, project-adapted；依据项目内部 adaptation contract 记录）。
- **Source-faithful components 忠实组件**：
  - 三阶段分解：BPSO 搜索卸载决策 X（Algorithm 3）→ RATA 固定 X 生成指派 A（Algorithm 1）→ LA 固定 (X,A) 生成分配 F（Algorithm 2 / Eq.25）；fitness 只用于选择 X； / three-stage decomposition: BPSO searches offloading decision X (Algorithm 3) → RATA generates assignment A for fixed X (Algorithm 1) → LA generates allocation F for fixed (X,A) (Algorithm 2 / Eq.25); fitness is used only to select X;
  - BPSO 速度方程 Eq.34/37/38、V 型转移函数； / BPSO velocity equations Eq.34/37/38, V-shaped transfer function;
  - RATA 指派：按任务脆弱性指标与服务器脆弱性排序（Theorem 1 方向）； / RATA assignment: ordering by task fragility metric and server fragility (direction of Theorem 1);
  - LA 闭式分配：$f^\*_{ij} = F_j \sqrt{\alpha_i f_i^{loc}} / \sum_{k \in \Gamma_j} \sqrt{\alpha_k f_k^{loc}}$。 / LA closed-form allocation.
- **Project adaptations 项目适配**：
  - 传输速率使用项目共享链路原语（逐链路独立无线信道，无跨链路干扰模型）；内部 fitness 的 $t_i^{off}/E_i^{trans}$ 使用项目共享的物理模型原语； / transmission rate uses the project's shared link primitives (per-link independent wireless channels, no cross-link interference model); $t_i^{off}/E_i^{trans}$ in the internal fitness uses the project's shared physical primitives;
  - 原文 Table II 数值默认（图片不可提取）以测试预算内默认值替代； / the paper's Table II numeric defaults (image, not extractable) are replaced by defaults within the test budget;
  - Algorithm 1 精确指派循环（原文为图片）依据 Theorem 1 排序目标与论文正文描述确定（一个基于原文的合理解释）。 / the exact assignment loop of Algorithm 1 (an image in the paper) is reconstructed from the Theorem 1 ordering objective and the manuscript prose (a reasonable interpretation of the original).
- **Omitted 省略**：用户间干扰项、硬件 testbed、JTSP/ILRM 对比、多 MD 竞争带宽的 B/n 归一化。 / inter-user interference terms, hardware testbed, JTSP/ILRM comparison, B/n normalization for multiple MDs contending for bandwidth.
- **Parameter / search budget 参数/搜索预算**（仅测试/复现用，非正式调参 / test-only, not tuning）：`population_size_max`、`max_iterations_max`、`particle_evaluation_cap_max`、`reliability_threshold`、`inertia_weight`、`cognitive_coefficient`、`social_coefficient`；正式配置见 `configs/r6/frozen_method_configs/bpso_frozen.yaml`。
- **Fairness boundary 公平边界**：与全部方法共享 scenario、seed、数据划分、派生数据规则、硬约束（统一 Evaluator C1–C6）、formal-test、timeout policy、failure accounting；不使用 CARS 私有状态；内部目标为原文系统卸载效用（最大化）；最终结果由统一 Evaluator 唯一正式评价。 / shares scenario, seed, data split, derived-data rules, hard constraints (unified Evaluator C1–C6), formal-test, timeout policy, and failure accounting with all methods; does not use CARS-private state; the internal objective is the paper's system offloading utility (maximization); final results are formally evaluated only by the unified Evaluator.

## 2. 强 Baseline：JTORA-adapted

- **Reference**：JTORA 论文（联合任务卸载与资源分配；TO 卸载 + RA 资源分配分解）。 / JTORA paper (joint task offloading and resource allocation; TO offloading + RA allocation decomposition).
- **Independent reimplementation**：是 / Yes（source-aligned, project-adapted；依据项目内部 adaptation contract 记录）。
- **Source-faithful components**：
  - 卸载效用 $J_u$（Eq.10）与系统目标 $J=\sum_u \lambda_u J_u$（Eq.11）方向与结构保留（$\lambda_u$ 冻结为 1）； / offloading utility $J_u$ (Eq.10) and system objective $J=\sum_u \lambda_u J_u$ (Eq.11) keep their direction and structure ($\lambda_u$ frozen to 1);
  - TO(14) + RA(15) 分解；RA 中 CRA(25) 完整保留（凸性、KKT、闭式 (27)/(41)、开销 (28)/(42)）； / TO(14) + RA(15) decomposition; CRA(25) within RA fully retained (convexity, KKT, closed forms (27)/(41), costs (28)/(42));
  - TO 启发式 Algorithm 2（best-single 初始化 + remove/exchange 局部改进，(1+δ) 改进因子）； / TO heuristic Algorithm 2 (best-single initialization + remove/exchange local improvements, (1+δ) improvement factor);
  - $J_u<0$ 不卸载的原文规则保留。 / the paper's rule of not offloading when $J_u<0$ is retained.
- **Project adaptations**：
  - 传输模型物化为项目共享时延/能耗原语（固定发射功率；通信量在 CRA 子问题中为常数）； / the transmission model is realized with the project's shared latency/energy primitives (fixed transmit power; communication quantities are constants in the CRA subproblem);
  - 无 OFDMA 子带维度（逐链路独立带宽）；约束 (30d) 省略； / no OFDMA subband dimension (per-link independent bandwidth); constraint (30d) omitted;
  - 服务器选择 ground set = 物理有效边；A 由最终执行位置唯一提取； / server-selection ground set = physically valid edges; A is uniquely derived from the final execution location;
  - Algorithm 2 迭代上界 `max_outer_iterations` 封顶（原文未给出显式上界，项目为此设置了上限）。 / Algorithm 2 iteration bound is capped by `max_outer_iterations` (the paper gives no explicit bound, so a project-side cap was set).
- **Omitted**：UPA 功率优化（生产路径 `binary_search_calls=0`，发射功率固定）、子带调度维度、小区间干扰、服务商偏好参数。 / UPA power optimization (production path `binary_search_calls=0`, fixed transmit power), subband scheduling dimension, inter-cell interference, operator preference parameters.
- **Parameter / search budget**（仅测试/复现用）：`max_outer_iterations`（tiny 5 / small 30）、`max_binary_search_iterations`（32/64）、`absolute_tolerance`（1e-8）、`relative_tolerance`（1e-7）、`improvement_factor_delta`、`soft_deadline_margin`、`hard_timeout_seconds`。
- **Fairness boundary**：共享全部执行边界；不读取可靠性阈值/服务器故障率/Q/Z/ρ；不调用统一 Evaluator 作为内部目标；内部目标 = 原文时延-能耗（Eq.10/29）；最终结果由统一 Evaluator 唯一正式评价。 / shares all execution boundaries; does not read reliability thresholds/server failure rates/Q/Z/ρ; does not call the unified Evaluator as an internal objective; internal objective = the paper's latency-energy (Eq.10/29); final results are formally evaluated only by the unified Evaluator.

## 3. 强 Baseline：NFA-adapted

- **Reference**：NFA 论文（萤火虫算法 + 复合启发式的任务调度）。 / NFA paper (firefly algorithm + composite heuristics for task scheduling).
- **Independent reimplementation**：是 / Yes（source-aligned, project-adapted；依据项目内部 adaptation contract 记录）。
- **Source-faithful components**：
  - 萤火虫位置为 N 维实数元组；距离型映射算子 Algorithm 1（$p=\min(e^{-r^\*_i},0.95)$，Step1 继承 + Step2 均匀插入）； / firefly position is an N-dimensional real tuple; distance-based mapping operator Algorithm 1 ($p=\min(e^{-r^\*_i},0.95)$, Step1 inherit + Step2 uniform insertion);
  - 移动方程 Eq.(14)（β₀, γ, 欧氏距离, 随机化），逐维应用； / movement equation Eq.(14) (β₀, γ, Euclidean distance, randomization), applied per dimension;
  - 亮度方向：解越好亮度越高（原文 $I_i=1/f(\pi_i)$，f=最小化 makespan；项目适配为 P0 字典序元组）； / brightness direction: better solutions are brighter (paper $I_i=1/f(\pi_i)$, f = minimizing makespan; project-adapted to the P0 lexicographic tuple);
  - Algorithm 3 控制流（随机选最亮 → 初始评价 → while 代循环双循环 i,j → 移动+重映射+重评价+更新 best-so-far）； / Algorithm 3 control flow (randomly pick brightest → initial evaluation → while generation loop with double loop i,j → move + remap + re-evaluate + update best-so-far);
  - Composite heuristic Algorithm 2（LTF → IRM → SSM，while Improved）；参数 β₀=1、γ=2、position_bounds=[-2,2]、p≤0.95。 / composite heuristic Algorithm 2 (LTF → IRM → SSM, while Improved); parameters β₀=1, γ=2, position_bounds=[-2,2], p≤0.95.
- **Project adaptations**：
  - FTA 无伪代码（原文仅引用 [5]）→ 以"确定性贪心 QoS 感知列表调度"替代其"任务序列→调度方案"角色； / FTA has no pseudocode in the paper (only a citation to [5]) → its "task sequence → schedule" role is replaced by a deterministic greedy QoS-aware list scheduler;
  - 内部目标由 makespan 标量适配为 MU-MEC 的 P0 字典序元组 (z_count, ΣRⁱᵛᵃˡⁱᵈ, ΣUⁱᵉᶠᶠ)（保持"更亮=更优"身份）； / the internal objective is adapted from the makespan scalar to the MU-MEC P0 lexicographic tuple (z_count, ΣRⁱᵛᵃˡⁱᵈ, ΣUⁱᵉᶠᶠ) (keeping the "brighter = better" identity);
  - LTF 排序依据：任务本地执行时延 $T_i^{loc}$ 降序（并列按任务编号升序）； / LTF ordering: task local execution latency $T_i^{loc}$ descending (ties by task id ascending);
  - 位置移动后逐维 clamp 到 position_bounds。 / positions are clamped per dimension to position_bounds after movement.
- **Omitted**：FTA 具体内部算法、原文预算/私有云资源约束、移动随机化参数 α（原文 IV-D 同，仅登记）。 / FTA's specific internal algorithm, the paper's budget/private-cloud resource constraints, and the movement randomization parameter α (same as the paper's IV-D, recorded only).
- **Parameter / search budget**（仅测试/复现用）：`population_size`（tiny 4 / small 8）、`max_generations`（3/10）、`beta_0`（1）、`gamma`（2）、`position_bounds`（[-2,2]）、`objective_evaluation_cap`（128/2048）、`soft_deadline_margin`、`hard_timeout_seconds`。
- **Fairness boundary**：共享全部执行边界；不使用 CARS 私有状态；不使用 CARS 内部辅助机制；不加额外可行性信息；最终结果由统一 Evaluator 产生。 / shares all execution boundaries; does not use CARS-private state; no hidden internal CARS mechanisms; no extra feasibility information; final results are produced by the unified Evaluator.

## 4. 弱 Baseline 与边界诊断 Weak Baselines and Boundary Diagnostics

- **reliability_only**：仅依据可靠性导向的保守决策（弱 Baseline）。 / conservative decisions guided only by reliability (weak baseline).
- **local_only**：全部任务本地执行（negative control；用于反证环境存在边缘资源异构性）。 / all tasks executed locally (negative control; used to show the environment has edge-resource heterogeneity).
- **FOA**：边界诊断方法（非正式对比对象）。 / boundary diagnostic method (not a formal comparison target).

## 5. 公共公平边界 Common Fairness Boundary

所有方法共享：scenario、seed、raw-data split、derived-data rules、硬约束（统一 Evaluator C1–C6）、formal-test、timeout policy、hardware budget、failure accounting。禁止只调优 CARS、给 CARS 单独预处理或额外可行性信息、隐藏 timeout/异常/不可行结果、使用不同 formal-test 或资源预算。

All methods share: scenario, seed, raw-data split, derived-data rules, hard constraints (unified Evaluator C1–C6), formal-test, timeout policy, hardware budget, and failure accounting. It is prohibited to tune only CARS, give CARS separate preprocessing or extra feasibility information, hide timeout/exception/infeasible results, or use different formal-test or resource budgets.
