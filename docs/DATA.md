# Data Availability

## 1. 本仓库不随附第三方原始数据

本公开仓库**不分发任何第三方原始/处理 Trace 数据**。`data/` 目录在本仓库中仅包含说明文件（本文件），不包含数据文件。

CARS 论文实验使用了以下外部 Trace（来源与官方获取方式需由论文作者提供并经官方核验；**本仓库不提供未经核验的下载 URL**）：

| 数据集 | 在论文实验中的角色 |
|--------|-------------------|
| Microsoft Azure Functions Trace 2019 | 工作负载动态结构（workload dynamics）驱动 |
| NEP Edge Workloads Traces | 后台 CPU 压力（background CPU pressure）驱动（其 workload 字段全 0，真实信号为 cpu_pressure） |
| Shanghai Telecom Mobile Internet Access Trace | 时间维度工作负载动态（temporal workload dynamics）驱动 |

## 2. 数据在论文中的证据地位

Trace 增强实验属于 **trace-enhanced / semi-synthetic 证据**：Trace 只提供外生动态结构，场景在共享物理模型上由确定性生成器构造（容量缩放等映射在论文实验设置中说明）。本实验**不构成**真实 MEC 生产部署或真实系统验证。

## 3. 期望数据目录结构

复现 Trace 增强实验时，用户需自行从原始提供方取得数据，并按如下结构放置（可用环境变量 `CARS_DATA_ROOT` 指向数据根目录；配置中的 `${CARS_DATA_ROOT}` 占位符表示该根目录）：

```text
<CARS_DATA_ROOT>/
├── Microsoft Azure Functions Trace 2019/
├── NEP EdgeWorkloadsTraces/
└── Shanghai Telecom Mobile Internet Access Trace/
```

- processed Trace（预处理产物）当前**不随源码分发**；
- 预处理/字段映射规则见 `configs/e4_v2/e4_v2_trace_field_mapping.yaml` 与 `e4_v2_trace_input_manifest.yaml`（manifest 中记录各数据集文件清单与字段语义状态）。

## 4. 数据使用边界

- 未经数据集提供方许可，不得将原始数据再分发；
- 复现结果仅作为 trace-enhanced / semi-synthetic 证据，不得表述为真实系统验证；
- 正式实验的 formal-test 数据划分规则冻结于各实验协议中（`configs/e4_v2/`、`configs/e3_v2/` 等），复现时必须遵守训练/校准/正式测试分区互斥。

## 5. 无 Trace 数据的复现范围

不依赖外部 Trace 的正式实验（E0 负载扩展、E1 任务规模与异构资源、E2 组件消融、E4 Exact-Oracle 参照）不要求外部数据，可完整复现；依赖 Trace 的实验（Trace 增强外部有效性评估）需要按上文获取数据。
