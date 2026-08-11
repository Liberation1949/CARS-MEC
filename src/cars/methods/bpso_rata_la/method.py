# -*- coding: utf-8 -*-
"""BPSO-RATA-LA 生产实现（性能优化：粒子评价缓存 + 共享确定性组件）。

优化内容（仅精确等价优化，适配合同允许）：
- 按卸载决策 X 元组缓存 RATA+LA+fitness/R_sys（X 的纯函数）；
- 静态任务/链路/服务器量由 DerivedState 预计算（R2 底座）；
- RATA/LA/fitness 为 O(N*M) 轻量操作。

所有缓存与优化必须与 reference 数值等价（cache 开/关、reference/optimized
测试断言）。
"""

from __future__ import annotations

from cars.methods.bpso_rata_la.bpso import run_bpso
from cars.methods.bpso_rata_la import config as bpso_config
from cars.methods.protocol import MethodContext, MethodProposal

METHOD_ID = "bpso_rata_la"


class BpsoRataLaMethod:
    """BPSO-RATA-LA 生产版（启用粒子评价缓存）。"""

    method_id = METHOD_ID

    def __init__(self, config: dict, use_cache: bool = True) -> None:
        bpso_config.validate_config(config)
        self.config = config
        self.use_cache = bool(use_cache)

    def run(self, ctx: MethodContext) -> MethodProposal:
        return run_bpso(ctx, use_cache=self.use_cache)
