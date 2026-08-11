# -*- coding: utf-8 -*-
"""确定性随机工具（R2 公共底座）。

原则（Contract Part 7 / AGENTS.md §13 / 提示词 Step 3.1）：
- 所有随机过程显式接收 seed；
- 使用独立 ``random.Random(seed)`` 实例，不使用全局随机状态（不污染 ``random`` 模块）；
- 同 seed 字节级稳定；不同 seed 产生合法差异。
"""

from __future__ import annotations

import random
from typing import List, Sequence, TypeVar

T = TypeVar("T")


def make_rng(seed: int) -> random.Random:
    """创建独立 seeded RNG。seed 必须为非负整数。"""
    if not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a non-negative integer, got %r" % (seed,))
    return random.Random(seed)


def uniform(rng: random.Random, low: float, high: float) -> float:
    """[low, high) 内确定性均匀抽样。"""
    return rng.uniform(low, high)


def randint(rng: random.Random, low: int, high: int) -> int:
    """[low, high] 闭区间确定性整数抽样。"""
    return rng.randint(low, high)


def choice(rng: random.Random, seq: Sequence[T]) -> T:
    """确定性随机选择；seq 必须非空。"""
    if len(seq) == 0:
        raise ValueError("choice from empty sequence")
    return rng.choice(seq)


def shuffled(rng: random.Random, seq: Sequence[T]) -> List[T]:
    """确定性随机打乱（返回新列表）。"""
    items = list(seq)
    rng.shuffle(items)
    return items
