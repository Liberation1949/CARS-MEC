# -*- coding: utf-8 -*-
"""NFA-adapted 参考实现（tiny-case 对照用；无目标评价缓存）。

与 optimized 共用全部确定性组件（映射/移动/解码/目标/composite heuristic 与
主循环）；唯一差异：use_cache=False（每次目标评价都实际解码+计算）。
"""

from __future__ import annotations

from cars.methods.nfa_adapted.core import run_nfa
from cars.methods.nfa_adapted import config as nfa_config
from cars.methods.protocol import MethodContext, MethodProposal

METHOD_ID = "nfa_adapted"


class ReferenceNfaAdapted:
    """NFA-adapted 参考版（无缓存）。"""

    method_id = METHOD_ID

    def __init__(self, config: dict) -> None:
        nfa_config.validate_config(config)
        self.config = config

    def run(self, ctx: MethodContext) -> MethodProposal:
        return run_nfa(ctx, use_cache=False)
