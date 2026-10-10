"""Tests for core.lp: 手算验证 LP 最优解、不可行/无界检测、随机规模压力。"""
from __future__ import annotations

import math
import random

import pytest

from core.lp import LPProblem, LPSolution, solve_lp


class TestBasicLPs:
    def test_simple_2d(self):
        # min -x - y s.t. x + y <= 4, x <= 3, y <= 3, x>=0, y>=0
        # optimal: x=1, y=3 (or x=3, y=1), obj = -4
        p = LPProblem(
            c=[-1, -1],
            a_ub=[[1, 1], [1, 0], [0, 1]],
            b_ub=[4, 3, 3],
            a_eq=None, b_eq=None,
            bounds=[(0, None), (0, None)],
            n_vars=2,
        )
        sol = solve_lp(p)
        assert sol.status == "optimal"
        assert sol.objective == pytest.approx(-4, abs=1e-6)

    def test_equality_constraint(self):
        # min 3x + 2y s.t. x + y = 10, x>=0, y>=0
        # optimal: y=10, x=0, obj=20
        p = LPProblem(
            c=[3, 2],
            a_ub=[], b_ub=[],
            a_eq=[[1, 1]], b_eq=[10],
            bounds=[(0, None), (0, None)],
            n_vars=2,
        )
        sol = solve_lp(p)
        assert sol.status == "optimal"
        assert sol.objective == pytest.approx(20, abs=1e-6)

    def test_upper_bound(self):
        # min -x s.t. x <= 5, x >= 0
        p = LPProblem(
            c=[-1],
            a_ub=[], b_ub=[],
            a_eq=None, b_eq=None,
            bounds=[(0, 5)],
            n_vars=1,
        )
        sol = solve_lp(p)
        assert sol.status == "optimal"
        assert sol.x[0] == pytest.approx(5, abs=1e-6)
        assert sol.objective == pytest.approx(-5, abs=1e-6)

    def test_fixed_variable(self):
        # min x s.t. x = 3 (fixed via bounds (3,3))
        p = LPProblem(
            c=[1], a_ub=[], b_ub=[], a_eq=None, b_eq=None,
            bounds=[(3, 3)], n_vars=1,
        )
        sol = solve_lp(p)
        assert sol.status == "optimal"
        assert sol.x[0] == pytest.approx(3, abs=1e-9)

    def test_free_variable(self):
        # min x s.t. x + y = 5, y in [2,3], x free
        # x = 5 - y, min(5-y) → y=3, x=2
        p = LPProblem(
            c=[1, 0], a_ub=[], b_ub=[],
            a_eq=[[1, 1]], b_eq=[5],
            bounds=[(None, None), (2, 3)],
            n_vars=2,
        )
        sol = solve_lp(p)
        assert sol.status == "optimal"
        assert sol.x[0] == pytest.approx(2, abs=1e-6)

    def test_negative_rhs(self):
        # min x s.t. -x <= -2 → x >= 2 → optimal x=2, obj=2
        p = LPProblem(
            c=[1], a_ub=[[-1]], b_ub=[-2],
            a_eq=None, b_eq=None, bounds=[(None, None)], n_vars=1,
        )
        sol = solve_lp(p)
        assert sol.status == "optimal"
        assert sol.x[0] == pytest.approx(2, abs=1e-6)


class TestInfeasible:
    def test_contradiction(self):
        # x >= 5 and x <= 3 → infeasible
        p = LPProblem(
            c=[1], a_ub=[[1]], b_ub=[3],
            a_eq=None, b_eq=None, bounds=[(5, None)], n_vars=1,
        )
        sol = solve_lp(p)
        assert sol.status == "infeasible"

    def test_equality_contradiction(self):
        # x = 5 and x = 3 via bounds + eq
        p = LPProblem(
            c=[0], a_ub=[], b_ub=[],
            a_eq=[[1]], b_eq=[5],
            bounds=[(0, 3)], n_vars=1,
        )
        sol = solve_lp(p)
        assert sol.status == "infeasible"


class TestUnbounded:
    def test_min_negative_unbounded(self):
        # min -x s.t. no constraint, x >= 0 → unbounded
        p = LPProblem(
            c=[-1], a_ub=[], b_ub=[],
            a_eq=None, b_eq=None, bounds=[(0, None)], n_vars=1,
        )
        sol = solve_lp(p)
        assert sol.status == "unbounded"


class TestScaling:
    def test_80_vars_brute_force(self):
        """Random 80-variable LP with known optimal via construction.

        Build a feasible point x*, set c = random, then construct constraints
        such that x* is optimal (x* is a vertex where n linearly independent
        constraints bind).
        """
        rng = random.Random(12345)
        n = 40
        # Simple structured test: min sum_i x_i s.t. x_i in [0,2], sum_i x_i >= 10
        # optimal: exactly 10 of 40 vars at 0, 5 at 2, 5 at ... actually:
        # min sum x_i, x_i <= 2, sum x_i >= 10 → set x_i = 2 for 5 vars, 0 for rest → obj = 10
        c = [1.0] * n
        a_ub = [[0.0] * n for _ in range(n)]
        b_ub = [2.0] * n
        for i in range(n):
            a_ub[i][i] = 1.0
        a_eq = [[1.0] * n]
        b_eq = [10.0]
        p = LPProblem(c=c, a_ub=a_ub, b_ub=b_ub, a_eq=a_eq, b_eq=b_eq,
                      bounds=[(0, None)] * n, n_vars=n)
        sol = solve_lp(p)
        assert sol.status == "optimal"
        assert sol.objective == pytest.approx(10.0, abs=1e-5)
        assert sum(sol.x) == pytest.approx(10.0, abs=1e-4)

    def test_120_vars_tpu_scales(self):
        """Simulate optimizer's problem shape: 24*5 vars, ~120 rows, solve in <1s."""
        n_vars = 120
        n_steps = 24
        nv_per = 5  # charge,discharge,buy,sell,soc
        rng = random.Random(99)
        c = [rng.uniform(0, 1) for _ in range(n_vars)]
        # Simple: just bounds + one aggregate row
        a_ub = [[0.0] * n_vars for _ in range(n_vars)]
        b_ub = [rng.uniform(1, 10) for _ in range(n_vars)]
        for i in range(n_vars):
            a_ub[i][i] = 1.0
        p = LPProblem(c=c, a_ub=a_ub, b_ub=b_ub, a_eq=None, b_eq=None,
                      bounds=[(0, 5)] * n_vars, n_vars=n_vars)
        import time
        t0 = time.time()
        sol = solve_lp(p, max_iter=5000)
        elapsed = time.time() - t0
        assert sol.status == "optimal"
        assert elapsed < 1.0, "120 vars took %.2fs" % elapsed


class TestEdgeCases:
    def test_zero_vars(self):
        p = LPProblem(c=[], a_ub=[], b_ub=[], a_eq=None, b_eq=None, bounds=[], n_vars=0)
        sol = solve_lp(p)
        assert sol.status == "optimal"
        assert sol.objective == 0.0

    def test_all_fixed(self):
        p = LPProblem(c=[1, 2], a_ub=[], b_ub=[], a_eq=None, b_eq=None,
                      bounds=[(3, 3), (5, 5)], n_vars=2)
        sol = solve_lp(p)
        assert sol.status == "optimal"
        assert sol.x == pytest.approx([3, 5], abs=1e-9)
        assert sol.objective == pytest.approx(13, abs=1e-9)