"""
Grundlegende Smoke-Tests für sensor_model.py
"""
import numpy as np
import pytest
from spektral_sensor.model.sensor_model import beer_lambert, fit_beta, sensor_signal, R_I


def test_beer_lambert_zero_absorption():
    """Ohne absorption kommt I_0 unverändert an."""
    assert beer_lambert(100.0, [(0.0, 10.0)]) == pytest.approx(100.0)


def test_beer_lambert_additive_layers():
    """Zwei Schichten = eine Schicht mit addiertem Produkt."""
    I_combined = beer_lambert(100.0, [(0.1, 5.0), (0.2, 3.0)])
    I_single = beer_lambert(100.0, [(0.1 * 5.0 + 0.2 * 3.0, 1.0)])
    assert I_combined == pytest.approx(I_single)


def test_fit_beta_exact():
    """Wenn Daten exakt Beer-Lambert folgen, muss beta reproduziert werden."""
    beta_true = 0.27
    r_i = R_I
    c = np.array([0.0, 1.25, 2.5, 5.0])
    I_0 = 10000.0
    I_sensor = I_0 * np.exp(-beta_true * 2 * r_i * c)
    # c=0 → I=I_0 → log(1)=0, linregress braucht Variation
    beta_fit, r2 = fit_beta(c[1:], I_sensor[1:], I_0, r_i=r_i)
    assert beta_fit == pytest.approx(beta_true, rel=1e-6)
    assert r2 == pytest.approx(1.0, rel=1e-6)


def test_sensor_signal_zero_concentration():
    """Bei c=0 überall muss I_sensor = I_0."""
    r = np.linspace(0, R_I, 50)
    c_rt = np.zeros((len(r), 10))
    I_0 = 5000.0
    result = sensor_signal(c_rt, r, beta=0.27, I_0=I_0)
    np.testing.assert_allclose(result, I_0)
