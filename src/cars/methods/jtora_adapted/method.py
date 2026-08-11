# -*- coding: utf-8 -*-
"""JTORA-adapted 生产实现（性能优化：源目标评价缓存 + 共享确定性组件）。

优化内容（仅精确等价优化，适配合同允许）：
- 按卸载集 frozenset 缓存 J*(Y)（Eq.29 为 Y 的纯函数）；
- 源代价量（SourceCosts）由 T0 DerivedState 预计算；
- CRA 闭式 O(|Y|)。

所有缓存与优化必须与 reference 数值等价（cache 开/关、reference/optimized
测试断言）。
"""

from __future__ import annotations

from cars.methods.jtora_adapted import config_validator
from cars.methods.jtora_adapted.offloading import run_jtora
from cars.methods.protocol import MethodContext, MethodProposal

METHOD_ID = "jtora_adapted"


class JtoraAdaptedMethod:
    """JTORA-adapted 生产版（启用源目标评价缓存）。"""

    method_id = METHOD_ID

    def __init__(self, config: dict, use_cache: bool = True) -> None:
        config_validator.validate_config(config)
        self.config = config
        self.use_cache = bool(use_cache)

    def run(self, ctx: MethodContext) -> MethodProposal:
        return run_jtora(ctx, use_cache=self.use_cache)
