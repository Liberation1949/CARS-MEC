# -*- coding: utf-8 -*-
"""NFA-adapted 生产实现（性能优化：目标评价缓存 + 共享确定性组件）。

优化内容（仅精确等价优化，适配合同允许）：
- 按解码后离散解（任务序列 π）缓存目标评价（decode+fitness 为 π 的纯函数）；
- 静态任务/链路/服务器量由 DerivedState 预计算（R2 底座）；
- 移动/映射为 O(N) 轻量操作，不做深拷贝（列表原地更新）。

所有缓存与优化必须与 reference 数值等价（cache 开/关、reference/optimized
测试断言）。
"""

from __future__ import annotations

from cars.methods.nfa_adapted.core import run_nfa
from cars.methods.nfa_adapted import config as nfa_config
from cars.methods.protocol import MethodContext, MethodProposal

METHOD_ID = "nfa_adapted"


class NfaAdaptedMethod:
    """NFA-adapted 生产版（启用目标评价缓存）。"""

    method_id = METHOD_ID

    def __init__(self, config: dict, use_cache: bool = True) -> None:
        nfa_config.validate_config(config)
        self.config = config
        self.use_cache = bool(use_cache)

    def run(self, ctx: MethodContext) -> MethodProposal:
        return run_nfa(ctx, use_cache=self.use_cache)
