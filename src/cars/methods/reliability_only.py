# -*- coding: utf-8 -*-
"""reliability_only 弱 Baseline（PROJECT_DEFINED_WEAK_BASELINE）。

动态顺序可靠性基线（CARS_R3_RELIABILITY_ONLY_CONTRACT_V1）：
  任务可靠性敏感度排序
  -> 逐任务比较本地与边缘预计可靠性
  -> 指派后更新服务器预计共享算力
  -> 最终等份资源分配
  -> 一次 EDGE->LOCAL 可靠性一致性回退
  -> 输出 X/A/F

只优化名义路径可靠性；不使用 deadline、效用、能耗、任务成功层级、RUAD 压力、
CALA 权重或 Repair。确定性：无随机过程（method seed 不影响结果）。
只读取合同允许的输入字段（task_id/c_i/nu_i/f_loc/lambda_loc/F_j/lambda_j/
R_tx/e_phy/eps_cmp）；禁止读取字段存在性由变形测试验证。
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional

from cars.methods.protocol import MethodContext, MethodProposal
from cars.methods.registry import get_registry
from cars.simulator import physical_models as pm

METHOD_ID = "reliability_only"

# 与 R2 冻结 eps_cmp 一致的默认值（evaluator_contract.yaml §5；配置可显式给出）
DEFAULT_EPS_CMP = 1.0e-9


def _validate_config(config: Dict) -> Dict:
    """校验并归一化配置。白名单：method_id/config_label/scenario_config/
    eps_cmp/method_seed/hard_timeout_seconds。"""
    if not isinstance(config, dict):
        raise ValueError("reliability_only config must be a dict")
    method_id = config.get("method_id")
    if method_id != METHOD_ID:
        raise ValueError("method_id mismatch: %r" % (method_id,))
    eps = config.get("eps_cmp", DEFAULT_EPS_CMP)
    if not isinstance(eps, (int, float)) or not (0.0 < eps < 1.0):
        raise ValueError("eps_cmp must be in (0,1)")
    seed = config.get("method_seed", 0)
    if not isinstance(seed, int) or seed < 0:
        raise ValueError("method_seed must be a non-negative int")
    hard = config.get("hard_timeout_seconds", 10.0)
    if not isinstance(hard, (int, float)) or hard <= 0:
        raise ValueError("hard_timeout_seconds must be positive")
    return {
        "method_id": METHOD_ID,
        "config_label": config.get("config_label", ""),
        "scenario_config": config.get("scenario_config", ""),
        "eps_cmp": float(eps),
        "method_seed": int(seed),
        "hard_timeout_seconds": float(hard),
    }


class ReliabilityOnlyMethod:
    """动态顺序可靠性弱 Baseline（确定性）。"""

    method_id = METHOD_ID

    def __init__(self, config: Dict) -> None:
        self.config = _validate_config(config)

    # ------------------------------------------------------------------
    # 辅助读取（只访问合同允许字段）
    # ------------------------------------------------------------------

    def _task_vars(self, scenario: Dict, derived, i: int):
        """返回任务 i 的决策所需字段（合同 §1 allowed_inputs）。"""
        task = scenario["tasks"][i]
        device = next(d for d in scenario["devices"] if d["device_id"] == task["device_id"])
        loc = derived.task_local[i]
        return {
            "task_id": task["task_id"],
            "c": float(task["cpu_cycles"]),
            "nu": float(task["fragility"]),
            "f_loc": float(device["local_cpu_rate"]),
            "lambda_loc": float(device["local_failure_rate"]),
            "R_loc": float(loc["R_loc"]),  # [F-10] T0 预计算（复用 R2）
        }

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------

    def run(self, ctx: MethodContext) -> MethodProposal:
        t0 = time.monotonic()
        scenario = ctx.scenario
        derived = ctx.derived
        eps = self.config["eps_cmp"]
        n = len(derived.task_ids)
        m = len(derived.server_ids)

        # ---- 诊断容器 ----
        diag = {
            "method": METHOD_ID,
            "vulnerability_score_by_task": {},
            "local_reliability_by_task": {},
            "projected_edge_reliability_by_task_server": {},
            "projected_share_by_task_server": {},
            "server_count_before_selection": {},
            "selected_action_by_task": {},
            "selected_projected_reliability": {},
            "initial_server_task_counts": {},
            "fallback_task_ids": [],
            "fallback_count": 0,
            "final_server_task_counts": {},
            "final_reliability_margin_by_edge_task": {},
        }

        # ---- 1. 任务数据与可靠性敏感度排序（K_i = (-chi, R_loc, task_id) 升序）----
        vars_by_idx: Dict[int, Dict] = {}
        order_keys = []
        for i in range(n):
            v = self._task_vars(scenario, derived, i)
            vars_by_idx[i] = v
            chi = v["nu"] * v["c"]
            diag["vulnerability_score_by_task"][v["task_id"]] = chi
            diag["local_reliability_by_task"][v["task_id"]] = v["R_loc"]
            order_keys.append((-chi, v["R_loc"], v["task_id"], i))
        # 确定性排序：键升序（-chi 升序 = chi 降序；R_loc 升序；task_id 升序；i 最终保底）
        order = [k[3] for k in sorted(order_keys)]

        # ---- 2. 动态顺序指派（n_j 随指派更新）----
        n_j = [0] * m
        X = [0] * n
        A = [[0] * m for _ in range(n)]

        for i in order:
            v = vars_by_idx[i]
            # 本地候选（初始最优 = LOCAL）
            best_kind = "local"
            best_j = -1
            best_rel = v["R_loc"]
            diag["server_count_before_selection"][v["task_id"]] = {derived.server_ids[j]: n_j[j] for j in range(m)}
            # 边缘候选：eps 感知选择（合同 §5.4：浮点相等按 eps_cmp 判断；
            # tie-break：LOCAL -> server_id 较小的 EDGE）
            for j in range(m):
                ls = derived.link(i, j)
                if ls is None or ls["e_phy"] != 1:
                    continue
                F_j = derived.server_state[j]["F_j"]
                lambda_j = derived.server_state[j]["lambda_j"]
                f_hat = F_j / (n_j[j] + 1)
                R_off = pm.offloading_reliability(
                    ls["R_tx"],
                    pm.edge_exec_reliability(lambda_j, v["nu"], v["c"], f_hat),
                )
                diag.setdefault("projected_share_by_task_server", {}).setdefault(v["task_id"], {})[derived.server_ids[j]] = f_hat
                diag.setdefault("projected_edge_reliability_by_task_server", {}).setdefault(v["task_id"], {})[derived.server_ids[j]] = R_off
                if R_off > best_rel + eps:
                    # 严格优于（超出容差）：边缘胜出
                    best_kind = "edge"
                    best_j = j
                    best_rel = R_off
                elif abs(R_off - best_rel) <= eps and best_kind == "edge" and j < best_j:
                    # 边缘间 tie：server_id 较小者胜出（本地在 tie 时保持胜出）
                    best_j = j
            if best_kind == "edge":
                X[i] = 1
                A[i][best_j] = 1
                n_j[best_j] += 1
            else:
                X[i] = 0
            diag["selected_action_by_task"][v["task_id"]] = (
                "LOCAL" if best_kind == "local" else "EDGE:%s" % derived.server_ids[best_j]
            )
            diag["selected_projected_reliability"][v["task_id"]] = best_rel

        diag["initial_server_task_counts"] = {derived.server_ids[j]: n_j[j] for j in range(m)}

        # ---- 3. 最终等份资源分配（f_ij = F_j/|Gamma_j|）----
        F = [[0.0] * m for _ in range(n)]
        for j in range(m):
            members = [i for i in range(n) if A[i][j] == 1]
            if not members:
                continue
            share = derived.server_state[j]["F_j"] / len(members)
            for i in members:
                F[i][j] = share

        # ---- 4. 一次 EDGE->LOCAL 一致性回退（按原任务排序顺序，单次扫描）----
        for i in order:
            if X[i] == 0:
                continue
            j = next(jj for jj in range(m) if A[i][jj] == 1)
            v = vars_by_idx[i]
            members = [k for k in range(n) if A[k][j] == 1]
            share = derived.server_state[j]["F_j"] / len(members)
            lambda_j = derived.server_state[j]["lambda_j"]
            ls = derived.link(i, j)
            R_final = pm.offloading_reliability(
                ls["R_tx"],
                pm.edge_exec_reliability(lambda_j, v["nu"], v["c"], share),
            )
            if R_final < v["R_loc"] - eps:
                # 回退本地
                X[i] = 0
                A[i][j] = 0
                F[i][j] = 0.0
                diag["fallback_task_ids"].append(v["task_id"])
                diag["fallback_count"] += 1
                # 立即重新等份分配服务器 j 剩余容量
                members2 = [k for k in range(n) if A[k][j] == 1]
                if members2:
                    share2 = derived.server_state[j]["F_j"] / len(members2)
                    for k in members2:
                        F[k][j] = share2
            else:
                diag["final_reliability_margin_by_edge_task"][v["task_id"]] = R_final - v["R_loc"]

        # ---- 5. 输出决策 ----
        decision = {
            "schema_version": "CARS_ACTIVE_SCHEMA_V1",
            "offloading_decision": X,
            "assignment_matrix": A,
            "resource_allocation": F,
        }

        diag["task_order"] = [vars_by_idx[i]["task_id"] for i in order]
        diag["final_server_task_counts"] = {
            derived.server_ids[j]: sum(1 for i in range(n) if A[i][j] == 1) for j in range(m)
        }
        diag["cleanup_completed"] = True
        diag["elapsed_method_seconds"] = time.monotonic() - t0

        return MethodProposal(
            decision=decision,
            method_status="SUCCESS",
            timed_out=False,
            runtime_seconds=time.monotonic() - t0,
            diagnostics=diag,
        )


def _factory(config: Dict) -> ReliabilityOnlyMethod:
    return ReliabilityOnlyMethod(config)


get_registry().register(METHOD_ID, _factory)
