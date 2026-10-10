"""纯 Python 两阶段单纯形 LP 求解器 (min c^T x)。

支持 a_ub x <= b_ub、a_eq x = b_eq 与逐变量上下界(None = 自由/单边)。
边界处理: 有限下界 x = lo + x'(x'>=0), 有限上界转为显式行,
自由变量拆成 xp - xn(xp,xn>=0)。Bland 规则防循环,偏主元容差 1e-9。
core 链路禁用 numpy, 全程纯 list-of-list。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

TOL = 1e-9


@dataclass
class LPProblem:
    c: List[float]
    a_ub: List[List[float]]
    b_ub: List[float]
    a_eq: Optional[List[List[float]]]
    b_eq: Optional[List[float]]
    bounds: List[Tuple[Optional[float], Optional[float]]]
    n_vars: int


@dataclass
class LPSolution:
    status: str                          # "optimal" | "infeasible" | "unbounded"
    x: List[float]
    objective: float


def _is_finite(v) -> bool:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return False
    return v == v and v != float("inf") and v != float("-inf")


class _Tableau:
    """标准形 min d^T y s.t. A y = b, y>=0 的单纯形表.

    rows[i]: [a_i_0 .. a_i_(n-1), b_i]; basis[i] 为第 i 行基列;
    reduced[j] 长度 n, 记录检验数。recompute_obj() 给出当前基可行解目标。
    """

    def __init__(self, rows: List[List[float]], cost: List[float], basis: List[int]):
        self.rows = rows
        self.cost = cost
        self.basis = basis
        self.n = len(cost)
        self.m = len(rows)
        self.reduced = list(cost)
        for i in range(self.m):
            cb = cost[basis[i]]
            if cb != 0.0:
                row = rows[i]
                for j in range(self.n):
                    a = row[j]
                    if a:
                        self.reduced[j] -= cb * a

    def _pivot(self, r: int, c: int) -> None:
        n = self.n
        prow = self.rows[r]
        pv = prow[c]
        inv = 1.0 / pv
        for j in range(n + 1):
            prow[j] *= inv
        prow[c] = 1.0
        for i in range(self.m):
            if i == r:
                continue
            row = self.rows[i]
            f = row[c]
            if f != 0.0:
                for j in range(n + 1):
                    pj = prow[j]
                    if pj:
                        row[j] -= f * pj
                row[c] = 0.0
        f = self.reduced[c]
        if f != 0.0:
            for j in range(self.n):
                pj = prow[j]
                if pj:
                    self.reduced[j] -= f * pj
            self.reduced[c] = 0.0

    def recompute_obj(self) -> float:
        v = 0.0
        n = self.n
        for i in range(self.m):
            cb = self.cost[self.basis[i]]
            if cb:
                v += cb * self.rows[i][n]
        return v

    def solve(self, allowed: List[bool], max_iter: int) -> Tuple[Optional[str], float]:
        it = 0
        n = self.n
        while True:
            it += 1
            if it > max_iter:
                return "iteration_limit", self.recompute_obj()
            enter = -1
            for j in range(n):
                if allowed[j] and self.reduced[j] < -TOL:
                    enter = j
                    break
            if enter < 0:
                return None, self.recompute_obj()
            leave = -1
            best = 0.0
            for i in range(self.m):
                a = self.rows[i][enter]
                if a > TOL:
                    ratio = self.rows[i][n] / a
                    if (leave < 0 or ratio < best - TOL or
                            (abs(ratio - best) <= TOL and self.basis[i] < self.basis[leave])):
                        best = ratio
                        leave = i
            if leave < 0:
                return "unbounded", float("-inf")
            self._pivot(leave, enter)
            self.basis[leave] = enter

    def values(self) -> List[float]:
        y = [0.0] * self.n
        for i in range(self.m):
            y[self.basis[i]] = self.rows[i][self.n]
        return y


def _infeasible(n: int) -> LPSolution:
    return LPSolution(status="infeasible", x=[0.0] * n, objective=float("inf"))


def solve_lp(p: LPProblem, max_iter: int = 2000) -> LPSolution:
    n = p.n_vars
    if n == 0:
        return LPSolution(status="optimal", x=[], objective=0.0)
    if len(p.c) != n:
        raise ValueError("c length %d != n_vars %d" % (len(p.c), n))
    if len(p.a_ub) != len(p.b_ub):
        raise ValueError("a_ub/b_ub length mismatch")
    eq = p.a_eq if p.a_eq is not None else []
    eqb = p.b_eq if p.b_eq is not None else []
    if len(eq) != len(eqb):
        raise ValueError("a_eq/b_eq length mismatch")
    for i, row in enumerate(p.a_ub):
        if len(row) != n:
            raise ValueError("a_ub row %d length %d != n_vars %d" % (i, len(row), n))
    for i, row in enumerate(eq):
        if len(row) != n:
            raise ValueError("a_eq row %d length %d != n_vars %d" % (i, len(row), n))
    bounds = list(p.bounds) if p.bounds else [(0.0, None)] * n
    if len(bounds) != n:
        raise ValueError("bounds length %d != n_vars %d" % (len(bounds), n))

    # ---------- 1. 变量替换: 原 x_j -> 标准列 y_k (>=0) + base ----------
    # col_to_orig[sidx] = (orig_idx, sign): x_j = base_j + sum sign_k * y_k
    col_to_orig: List[Tuple[int, float]] = []
    col_cost: List[float] = []
    col_of_orig: List[List[int]] = [[] for _ in range(n)]
    base_val: List[float] = [0.0] * n

    def new_col(orig: int, sign: float) -> int:
        idx = len(col_to_orig)
        col_to_orig.append((orig, sign))
        col_cost.append(p.c[orig] * sign)
        col_of_orig[orig].append(idx)
        return idx

    for j in range(n):
        lo, hi = bounds[j]
        if lo is None:
            new_col(j, 1.0)   # xp
            new_col(j, -1.0)  # xn
            base_val[j] = 0.0
        elif hi is not None and abs(hi - lo) <= TOL:
            base_val[j] = lo            # fixed
        else:
            new_col(j, 1.0)
            base_val[j] = lo

    nc = len(col_to_orig)

    def expand(orig_row: List[float]) -> Tuple[List[float], float]:
        std = [0.0] * nc
        bdelta = 0.0
        for j, a in enumerate(orig_row):
            if a == 0.0:
                continue
            bdelta += a * base_val[j]
            for sidx in col_of_orig[j]:
                _, sign = col_to_orig[sidx]
                std[sidx] += a * sign
        return std, bdelta

    # ---------- 2. 收集所有约束到标准列空间 ----------
    raw: List[Tuple[str, List[float], float]] = []
    for row, bb in zip(p.a_ub, p.b_ub):
        std, bd = expand(row)
        raw.append(("le", std, bb - bd))
    for row, bb in zip(eq, eqb):
        std, bd = expand(row)
        raw.append(("eq", std, bb - bd))

    # 上界行 (来自变量替换)
    for j in range(n):
        lo, hi = bounds[j]
        if hi is None:
            continue
        if lo is not None and abs(hi - lo) <= TOL:
            continue  # fixed
        if lo is not None:
            sidx = col_of_orig[j][0]
            cc = [0.0] * nc
            cc[sidx] = 1.0
            raw.append(("le", cc, hi - lo))
        else:
            pi = col_of_orig[j][0]
            ni = col_of_orig[j][1]
            cc = [0.0] * nc
            cc[pi] = 1.0
            cc[ni] = -1.0
            raw.append(("le", cc, hi))

    # ---------- 3. 规范化 (rhs>=0, 全零行检测) ----------
    norm: List[Tuple[str, List[float], float]] = []
    for kind, coeffs, rhs in raw:
        if rhs < -TOL:
            coeffs = [-v for v in coeffs]
            rhs = -rhs
            kind = {"le": "ge", "ge": "le", "eq": "eq"}[kind]
        elif abs(rhs) <= TOL:
            rhs = 0.0
        if all(abs(v) <= TOL for v in coeffs):
            if (kind == "eq" and abs(rhs) > TOL) or (kind == "ge" and rhs < -TOL):
                return _infeasible(n)
            continue  # le 0<=rhs(>=0) 或 eq 0=0: 恒真, 丢弃
        norm.append((kind, coeffs, rhs))

    def finish(yvals: List[float]) -> LPSolution:
        x = [0.0] * n
        for j in range(n):
            total_j = base_val[j]
            for sidx in col_of_orig[j]:
                _, sign = col_to_orig[sidx]
                total_j += sign * yvals[sidx]
            x[j] = total_j
        if not all(_is_finite(v) for v in x):
            return _infeasible(n)
        obj = sum(p.c[j] * x[j] for j in range(n))
        return LPSolution(status="optimal", x=x, objective=float(obj))

    # ---------- 4. 无可行基行: 目标是否可沿某标准列无限下降 ----------
    if not norm:
        # 存在自由增长列 (cost<0 且无上界) 即 unbounded
        if nc > 0 and min(col_cost) < -TOL:
            return LPSolution(status="unbounded", x=[0.0] * n, objective=float("-inf"))
        return finish([0.0] * nc)

    # ---------- 5. 加松弛/剩余/人工列, 建两阶段表 ----------
    plan: List[Tuple[str, List[float], float, List[Tuple[str, int]]]] = []
    col_ptr = nc
    for kind, coeffs, rhs in norm:
        if kind == "le":
            plan.append((kind, coeffs, rhs, [("slack", col_ptr)]))
            col_ptr += 1
        elif kind == "ge":
            plan.append((kind, coeffs, rhs, [("surplus", col_ptr), ("art", col_ptr + 1)]))
            col_ptr += 2
        else:  # eq
            plan.append((kind, coeffs, rhs, [("art", col_ptr)]))
            col_ptr += 1

    ncols = col_ptr
    rows: List[List[float]] = []
    basis: List[int] = []
    art_set = set()
    for kind, coeffs, rhs, adds in plan:
        row = list(coeffs) + [0.0] * (ncols - nc)
        if kind == "le":
            _, sc = adds[0]
            row[sc] = 1.0
            basis.append(sc)
        elif kind == "ge":
            _, sc = adds[0]
            _, ac = adds[1]
            row[sc] = -1.0
            row[ac] = 1.0
            basis.append(ac)
            art_set.add(ac)
        else:
            _, ac = adds[0]
            row[ac] = 1.0
            basis.append(ac)
            art_set.add(ac)
        row.append(rhs)
        rows.append(row)

    # ---- 第一阶段: 最小化人工和 (目标系数仅对人工列为 1) ----
    cost_p1 = [0.0] * ncols
    for ac in art_set:
        cost_p1[ac] = 1.0
    allowed_p1 = [True] * ncols
    tab1 = _Tableau(rows, cost_p1, list(basis))
    st, val = tab1.solve(allowed_p1, max_iter)
    if st == "iteration_limit":
        return _infeasible(n)
    if val > TOL:
        return _infeasible(n)

    # 逐出仍在基中的人工变量
    for i in range(tab1.m):
        if tab1.basis[i] in art_set:
            piv = -1
            for j in range(ncols):
                if j not in art_set and abs(tab1.rows[i][j]) > TOL:
                    piv = j
                    break
            if piv >= 0:
                tab1._pivot(i, piv)
                tab1.basis[i] = piv

    # 删除剩余冗余人工行
    new_rows: List[List[float]] = []
    new_basis: List[int] = []
    for i in range(tab1.m):
        if tab1.basis[i] in art_set:
            continue
        new_rows.append(tab1.rows[i])
        new_basis.append(tab1.basis[i])

    if not new_rows:
        return finish([0.0] * ncols)

    # ---- 第二阶段 ----
    cost_p2 = list(col_cost) + [0.0] * (ncols - nc)
    allowed_p2 = [j not in art_set for j in range(ncols)]
    tab2 = _Tableau(new_rows, cost_p2, new_basis)
    st2, _ = tab2.solve(allowed_p2, max_iter)
    if st2 == "unbounded":
        return LPSolution(status="unbounded", x=[0.0] * n, objective=float("-inf"))
    if st2 == "iteration_limit":
        return _infeasible(n)
    return finish(tab2.values())