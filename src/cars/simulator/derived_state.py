# -*- coding: utf-8 -*-
"""T0 决策前派生状态（R2 公共底座；正文 V-A.1 Phase 0 预处理）。

构造算法决策前可读取状态，包括：
- 本地执行状态：T_i^loc, E_i^loc, R_i^loc, omega_i^res, b_i^loc,
                 ell_i0^D, ell_i0^R, ell_i0^succ, f_tilde_i0^req（F-53, V-B.4）；
- 边的物理条件：r, T_tx, E_tx, R_tx, ell_D, ell_R, ell_succ,
                 e_phy（F-35）, e_rec（F-50）, f_tilde_req（F-52）, ell_hat_D（F-61）；
- 服务器容量与固定名义故障率：F_j, lambda_j；
- 决策前不可行原因（诊断标记）。

不得包含最终 X/A/F、最终资源竞争结果、任务成功状态或 Evaluator 输出。
本模块不读取跨时隙历史状态；rho_j^alloc 只能在 F 产生后计算（Assumption 2），
因此本模块不计算 rho_alloc。
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from cars.simulator import physical_models as pm


def _build_indexes(scenario: Dict) -> Tuple[Dict, Dict, Dict, Dict]:
    """返回 (task_by_id, device_by_id, server_by_id, link_pairs)。"""
    task_by_id = {t["task_id"]: t for t in scenario["tasks"]}
    device_by_id = {d["device_id"]: d for d in scenario["devices"]}
    server_by_id = {s["server_id"]: s for s in scenario["servers"]}
    link_pairs = {}
    for link in scenario.get("links", []):
        link_pairs[(link["source_device_id"], link["target_server_id"])] = link
    return task_by_id, device_by_id, server_by_id, link_pairs


class DerivedState:
    """T0 决策前派生状态（确定性构造，无随机）。"""

    def __init__(self, scenario: Dict):
        if scenario.get("state_timepoint") != "T0":
            raise ValueError("derived state requires a T0 scenario")
        self.scenario = scenario
        self.task_ids: List[str] = [t["task_id"] for t in scenario["tasks"]]
        self.server_ids: List[str] = [s["server_id"] for s in scenario["servers"]]
        self._task_by_id, self._device_by_id, self._server_by_id, self._link_pairs = (
            _build_indexes(scenario)
        )
        self._build()

    # ------------------------------------------------------------------
    # 构造
    # ------------------------------------------------------------------

    def _build(self) -> None:
        self.task_local: List[Dict] = []
        self.link_state: Dict[Tuple[int, int], Dict] = {}
        self.server_state: List[Dict] = []
        self.predecision_infeasible: List[str] = []

        n = len(self.task_ids)
        m = len(self.server_ids)

        # 服务器
        for s in self.scenario["servers"]:
            self.server_state.append(
                {"server_id": s["server_id"], "F_j": s["capacity_cycles_per_sec"],
                 "lambda_j": s["nominal_failure_rate"]}
            )

        # 任务本地属性 + 本地虚拟节点
        for i, task in enumerate(self.scenario["tasks"]):
            device = self._device_by_id[task["device_id"]]
            c = task["cpu_cycles"]
            f_loc = device["local_cpu_rate"]
            kappa = device["switch_capacitance"]
            lambda_loc = device["local_failure_rate"]
            nu = task["fragility"]
            R_min = task["min_reliability"]

            T_loc = pm.local_exec_delay(c, f_loc)
            E_loc = pm.local_exec_energy(kappa, c, f_loc)
            R_loc = pm.local_reliability(lambda_loc, nu, T_loc)
            # 无 deadline 模型（E1-CR 2026-08-08）：omega_res 用本地设备速率 f_loc
            # 作需求代理（原 c/D 的 deadline 速率无定义；WORKING_ASSUMPTION）
            omega_res = float(f_loc)
            b_loc = 1 if (R_loc >= R_min - 1e-12) else 0

            # F-53 本地虚拟节点（无 deadline：ell_0_succ = ell_0_R，边界取正小量）
            ell_0_R = pm.local_success_demand_R(lambda_loc, nu, c, R_min)
            ell_0_succ = ell_0_R if ell_0_R > 0.0 else 1.0e-9
            f_tilde_0_req = min(ell_0_succ, f_loc)

            self.task_local.append(
                {
                    "task_id": task["task_id"],
                    "device_id": task["device_id"],
                    "T_loc": T_loc,
                    "E_loc": E_loc,
                    "R_loc": R_loc,
                    "omega_res": omega_res,
                    "b_loc": b_loc,
                    "ell_0_R": ell_0_R,
                    "ell_0_succ": ell_0_succ,
                    "f_tilde_0_req": f_tilde_0_req,
                }
            )

        # 链路属性（仅存在 WirelessLink 的 (i,j)）
        for i, task in enumerate(self.scenario["tasks"]):
            dev_id = task["device_id"]
            for j, server in enumerate(self.scenario["servers"]):
                link = self._link_pairs.get((dev_id, server["server_id"]))
                if link is None:
                    continue
                device = self._device_by_id[dev_id]
                c = task["cpu_cycles"]
                d = task["data_bits"]
                nu = task["fragility"]
                R_min = task["min_reliability"]
                p = device["tx_power_watts"]
                B = link["bandwidth_hz"]
                h = link["channel_gain"]
                sigma2 = link["noise_power"]
                p_err = link["error_probability"]
                F_j = server["capacity_cycles_per_sec"]
                lambda_j = server["nominal_failure_rate"]

                r = pm.shannon_rate(B, p, h, sigma2)
                T_tx = pm.transmission_delay(d, r)
                E_tx = pm.transmission_energy(p, T_tx)
                R_tx = pm.transmission_reliability(p_err)

                # 无 deadline 模型（E1-CR 2026-08-08 + f_min^exec 同步 2026-08-11）：
                # ell_succ = max(ell_R, f_min^exec)，f_min^exec = 1.0（§III-D 最小可调度执行速率）；
                # 对 nu>0 任务 ell_R >> 1.0，ell_succ = ell_R；对零脆弱性任务 ell_succ = 1.0
                # （闭合可执行性，非数值 epsilon；正文 E4.1/表 VII-1）
                ell_R = pm.reliability_threshold(lambda_j, nu, c, R_tx, R_min)
                _F_MIN_EXEC = 1.0
                ell_succ = max(ell_R, _F_MIN_EXEC)

                e_phy = pm.physical_edge_marker(r, T_tx)
                e_rec = pm.recoverability_marker(e_phy, ell_succ, F_j)
                f_tilde_req = pm.finite_demand_proxy(ell_succ, e_rec, F_j)

                self.link_state[(i, j)] = {
                    "link_id": link["link_id"],
                    "r": r,
                    "T_tx": T_tx,
                    "E_tx": E_tx,
                    "R_tx": R_tx,
                    "ell_R": ell_R,
                    "ell_succ": ell_succ,
                    "e_phy": e_phy,
                    "e_rec": e_rec,
                    "f_tilde_req": f_tilde_req,
                }

        # 决策前不可行诊断：本地预计失败且无任何物理边
        for i, task in enumerate(self.scenario["tasks"]):
            loc = self.task_local[i]
            has_phy_edge = any(
                (i, j) in self.link_state and self.link_state[(i, j)]["e_phy"] == 1
                for j in range(m)
            )
            if loc["b_loc"] == 0 and not has_phy_edge:
                self.predecision_infeasible.append(task["task_id"])

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def link(self, i: int, j: int) -> Dict:
        """返回边 (i,j) 的链路状态；不存在或物理不可用返回 None。"""
        return self.link_state.get((i, j))

    def has_physical_edge(self, i: int, j: int) -> bool:
        ls = self.link_state.get((i, j))
        return ls is not None and ls["e_phy"] == 1

    def is_predecision_infeasible(self, i: int) -> bool:
        return self.task_ids[i] in self.predecision_infeasible
