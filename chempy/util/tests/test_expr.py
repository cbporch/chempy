# -*- coding: utf-8 -*-
from __future__ import (absolute_import, division, print_function)

import math
from operator import add
from functools import reduce

import pytest

from chempy import Substance
from chempy.units import (
    units_library, default_constants, Backend, to_unitless,
    SI_base_registry, default_units as u
)
from chempy.util.testing import requires

from .._expr import Expr, mk_Poly, mk_PiecewisePoly
from ..parsing import parsing_library


def _get_cv(kelvin=1, gram=1, mol=1):
    class HeatCapacity(Expr):
        parameter_keys = ('temperature',)
        kw = {'substance': None}

    class EinsteinSolid(HeatCapacity):
        """ arguments: einstein temperature """
        nargs = 1

        def __call__(self, variables, backend=math):
            molar_mass = self.substance.mass
            TE = self.arg(variables, 0)  # einstein_temperature
            R = variables['R']
            T, = self.all_params(variables, backend=backend)
            # Canoncial ensemble:
            molar_c_v = 3*R*(TE/(2*T))**2 * backend.sinh(TE/(2*T))**-2
            return molar_c_v/molar_mass

    Al = Substance.from_formula('Al', other_properties={'DebyeT': 428*kelvin})
    Be = Substance.from_formula('Be', other_properties={'DebyeT': 1440*kelvin})
    Al.mass *= gram/mol
    Be.mass *= gram/mol

    def einT(s):
        return 0.806*s.other_properties['DebyeT']
    return {s.name: EinsteinSolid([einT(s)], substance=s) for s in (Al, Be)}


@requires(parsing_library)
def test_Expr():
    cv = _get_cv()
    _ref = 0.8108020083055849
    assert abs(cv['Al']({'temperature': 273.15, 'R': 8.3145}) - _ref) < 1e-14


def _poly(args, x, backend=None):
    x0, coeffs = args[0], args[1:]
    return reduce(add, [c*(x-x0)**i for i, c in enumerate(coeffs)])


@requires(parsing_library)
def test_Expr__nested_Expr():
    Poly = Expr.from_callback(_poly, parameter_keys=('x',), argument_names=('x0', Ellipsis))
    T = Poly([3, 7, 5])

    cv = _get_cv()
    _ref = 0.8108020083055849
    assert abs(cv['Al']({'temperature': T, 'x': (273.15-7)/5 + 3, 'R': 8.3145}) - _ref) < 1e-14


def test_nargs():
    class A(Expr):
        nargs = 1

    with pytest.raises(ValueError):
        A([1, 2])


@requires('sympy')
def test_Expr_symbolic():
    import sympy
    cv = _get_cv()
    R, T = sympy.symbols('R T')
    sexpr = cv['Be']({'temperature': T, 'R': R}, backend=sympy)
    assert sexpr.free_symbols == set([T, R])


@requires(units_library)
def test_Expr_units():
    cv = _get_cv(u.kelvin, u.gram, u.mol)
    R = default_constants.molar_gas_constant.rescale(u.joule/u.mol/u.kelvin)

    def _check(T=273.15*u.kelvin):
        result = cv['Be']({'temperature': T, 'R': R}, backend=Backend())
        ref = 0.7342617587256584*u.joule/u.gram/u.kelvin
        assert abs(to_unitless((result - ref)/ref)) < 1e-10
    _check()
    _check(491.67*u.rankine)


@requires(units_library)
def test_Expr__dedimensionalisation():
    cv = _get_cv(u.kelvin, u.gram, u.mol)
    units, expr = cv['Be']._dedimensionalisation(SI_base_registry)
    assert units == [u.kelvin]
    assert expr.args == [0.806*1440]


def test_Expr__from_callback():
    def two_dim_gauss(args, x, y, backend=None):
        A, x0, y0, sx, sy = args
        xp, yp = x-x0, y-y0
        vx, vy = 2*sx**2, 2*sy**2
        return A*backend.exp(-(xp**2/vx + yp**2/vy))

    TwoDimGauss = Expr.from_callback(two_dim_gauss, parameter_keys=('x', 'y'), nargs=5)
    with pytest.raises(ValueError):
        TwoDimGauss([1, 2])
    args = [3, 2, 1, 4, 5]
    g1 = TwoDimGauss(args)
    ref = two_dim_gauss(args, 6, 7, math)
    assert abs(g1({'x': 6, 'y': 7}) - ref) < 1e-14


def test_mk_Poly():
    Poly = mk_Poly('T', reciprocal=True)
    p = Poly([3, 2, 5, 7, 8, 2, 9])
    assert p.eval_poly({'T': 13}) == 2.57829
    assert p.parameter_keys == ('T',)


def test_Expr__nargs():

    class Linear(Expr):
        """ Arguments: p0, p1 """
        nargs = 2
        parameter_keys = ('x',)

        def __call__(self, variables, backend=None):
            p0, p1 = self.all_args(variables)
            return p0 + p1*variables['x']

    l1 = Linear([3, 2])
    assert l1(dict(x=5)) == 13
    with pytest.raises(ValueError):
        Linear([3])
    with pytest.raises(ValueError):
        Linear([3, 2, 1])

    l2 = Linear([3, 2], ['a', 'b'])
    with pytest.raises(ValueError):
        Linear([3, 2], ['a'])
    with pytest.raises(ValueError):
        Linear([3, 2], ['a', 'b', 'c'])

    assert l2(dict(x=5)) == 13
    assert l2(dict(x=5, a=11, b=13)) == 11 + 13*5


def test_PiecewisePoly():
    Poly = mk_Poly('temperature')

    p1 = Poly([0, 1, 0.1])
    assert p1.eval_poly({'temperature': 10}) == 2

    p2 = Poly([0, 3, -.1])
    assert p2.eval_poly({'temperature': 10}) == 2

    TPiecewisePoly = mk_PiecewisePoly('temperature')
    tpwp = TPiecewisePoly.from_polynomials([(0, 10), (10, 20)], [p1, p2])
    assert tpwp.eval_poly({'temperature': 5}) == 1.5
    assert tpwp.eval_poly({'temperature': 15}) == 1.5
    assert tpwp.parameter_keys == ('temperature',)

    with pytest.raises(ValueError):
        tpwp.eval_poly({'temperature': 21})


@requires('sympy')
def test_PiecewisePoly__sympy():
    import sympy as sp
    Poly = mk_Poly('T')
    p1 = Poly([0, 1, 0.1])
    p2 = Poly([0, 3, -.1])

    TPiecewisePoly = mk_PiecewisePoly('temperature')
    tpwp = TPiecewisePoly([2, 2, 0, 10, 2, 10, 20, 0, 1, 0.1, 0, 3, -.1])
    x = sp.Symbol('x')
    res = tpwp.eval_poly({'temperature': x}, backend=sp)
    assert isinstance(res, sp.Piecewise)
    assert res.args[0][0] == 1+0.1*x
    assert res.args[0][1] == sp.And(0 <= x, x <= 10)
    assert res.args[1][0] == 3-0.1*x
    assert res.args[1][1] == sp.And(10 <= x, x <= 20)

    with pytest.raises(ValueError):
        tpwp.from_polynomials([(0, 10), (10, 20)], [p1, p2])


def test_BinaryExpr():
    Poly = Expr.from_callback(_poly, parameter_keys=('x',), argument_names=('x0', Ellipsis))
    p1 = Poly([1, 2, 3])
    p2 = Poly([2, 3, 4])
    assert p1({'x': 5}) == 14
    assert p2({'x': 5}) == 15
    assert (p1+p2)({'x': 5}) == 14+15
    assert (p1-p2)({'x': 5}) == 14-15
    assert (p1*p2)({'x': 5}) == 14*15
    assert (p1/p2)({'x': 5}) == 14/15

    assert (p1+2)({'x': 5}) == 14+2
    assert (p1-2)({'x': 5}) == 14-2
    assert (p1*2)({'x': 5}) == 14*2
    assert (p1/2)({'x': 5}) == 14/2

    assert (2+p1)({'x': 5}) == 2+14
    assert (2-p1)({'x': 5}) == 2-14
    assert (2*p1)({'x': 5}) == 2*14
    assert (2/p1)({'x': 5}) == 2/14
