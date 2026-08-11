# -*- coding: utf-8 -*-
"""BPSO-RATA-LA 参考实现（tiny-case 对照用；无粒子评价缓存）。

与 optimized 共用全部确定性组件（rata/la/source_objective/bpso 主循环）；
唯一差异：use_cache=False（每次评价都实际 RATA+LA+计算）。
"""

from __future__ import annotations

from cars.methods.bpso_rata_la.bpso import run_bpso
from cars.methods.bpso_rata_la import config as bpso_config
from cars.methods.protocol import MethodContext, MethodProposal

METHOD_ID = "bpso_rata_la"


class ReferenceBpsoRataLa:
    """BPSO-RATA-LA 参考版（无缓存）。"""

    method_id = METHOD_ID

    def __init__(self, config: dict) -> None:
        bpso_config.validate_config(config)
        self.config = config

    def run(self, ctx: MethodContext) -> MethodProposal:
        return run_bpso(ctx, use_cache=False)
