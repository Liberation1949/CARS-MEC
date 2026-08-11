# -*- coding: utf-8 -*-
"""JTORA-adapted 参考实现（tiny-case 对照用；无源目标评价缓存）。

与 optimized 共用全部确定性组件（source_cost/numerical_solver/
server_selection/offloading/resource_allocation 与主管线）；唯一差异：
use_cache=False（每次评价都实际计算 J*(Y)）。
"""

from __future__ import annotations

from cars.methods.jtora_adapted import config_validator
from cars.methods.jtora_adapted.offloading import run_jtora
from cars.methods.protocol import MethodContext, MethodProposal

METHOD_ID = "jtora_adapted"


class ReferenceJtoraAdapted:
    """JTORA-adapted 参考版（无缓存）。"""

    method_id = METHOD_ID

    def __init__(self, config: dict) -> None:
        config_validator.validate_config(config)
        self.config = config

    def run(self, ctx: MethodContext) -> MethodProposal:
        return run_jtora(ctx, use_cache=False)
