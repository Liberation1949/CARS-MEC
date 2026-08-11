# -*- coding: utf-8 -*-
"""CarsMethod（CR-CARS-PROMOTION-E1；MethodProtocol 适配）。

method_id="cars"；run(ctx) -> MethodProposal。
- 读取 T0 Scenario + DerivedState（MethodContext，只读）；
- 运行正式 CARS Pipeline（AADA → RCLA，默认 aada_variant=full +
  allocation_mode=rcla；无 Repair 层）；
- 返回最终 {X,A,F} 与 CARS 诊断（Schema V4）。

正式 CARS 实现（AADA → RCLA）位于本包；算法与 E0-V2/E3-V2 正式结果
所依赖的实现一致。

Method 不调用统一 Evaluator（Runner 唯一调用，T5）；不修改 scenario/derived。
异常由 worker 捕获并记为 METHOD_ERROR。
"""

from __future__ import annotations

import time
from typing import Dict

from cars.methods.cars.config import METHOD_ID, _validate_config, rcla_cfg_from_config
from cars.methods.cars.pipeline import run_cars_pipeline
from cars.methods.protocol import MethodContext, MethodProposal


class CarsMethod:
    """CARS 方法（无 GNN 确定性核心；CARS = AADA → RCLA，无 Repair）。"""

    method_id = METHOD_ID

    def __init__(self, config: Dict) -> None:
        self.config = _validate_config(config)

    def run(self, ctx: MethodContext) -> MethodProposal:
        t0 = time.monotonic()

        # 仅测试钩子：timeout 注入测试使用（非参数预算成员）
        hook = self.config.get("_test_hook_sleep_seconds", 0.0)
        if hook > 0.0:
            time.sleep(hook)

        rcla_cfg = rcla_cfg_from_config(self.config)
        result = run_cars_pipeline(
            ctx.scenario,
            ctx.derived,
            rcla_cfg,
            self.config["eps_cmp"],
            aada_variant=self.config.get("aada_variant", "full"),
            allocation_mode=self.config.get("allocation_mode", "rcla"),
        )
        return MethodProposal(
            decision=result["decision"],
            method_status=result["method_status"],
            timed_out=False,
            runtime_seconds=time.monotonic() - t0,
            diagnostics=result["diagnostics"],
        )
