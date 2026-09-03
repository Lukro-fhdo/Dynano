"""
sensor_model.py
---------------
Optical sensor model for SPION detection in a flow channel.
Based on the Beer-Lambert law, single-beam model.

Reference: sensormodell.tex
"""

import numpy as np


# ── Geometry ────────────────────────────────────────────────────────────────
R_I = 3.17 / 2    # mm — inner radius of tubing
R_A = R_I + 0.85  # mm — outer radius of tubing


# ── Beer-Lambert ─────────────────────────────────────────────────────────────

def beer_lambert(I_0, layers):
    """
    Beer-Lambert law for multiple absorbing layers.

    I_sensor = I_0 * exp(-(alpha_1*d_1 + alpha_2*d_2 + ...))

    Parameters
    ----------
    I_0    : float
        Incident intensity [W/m² or ADC counts]
    layers : list of (alpha, d) tuples
        alpha in [1/mm], d in [mm]

    Returns
    -------
    I_sensor : float
        Transmitted intensity after all layers
    """
    exponent = sum(alpha * d for alpha, d in layers)
    return I_0 * np.exp(-exponent)


# ── Calibration ──────────────────────────────────────────────────────────────

def fit_beta(c, I_sensor, I_0, r_i=R_I):
    """
    Determine beta from a calibration series via linear fit in log-space.

    ln(I_sensor / I_0) = -beta * 2*r_i * c

    Parameters
    ----------
    c        : array-like
        Concentration vector [mg/mL]
    I_sensor : array-like
        Measured intensities at each c [ADC counts]
    I_0      : float
        Baseline intensity at c=0 [ADC counts]
    r_i      : float
        Inner radius [mm]

    Returns
    -------
    beta  : float
        Absorption coefficient [mL/(mg·mm)]
    r_sq  : float
        R² of the fit
    """
    from scipy.stats import linregress
    log_I_norm = np.log(I_sensor / I_0)
    slope, _, r_corr, _, _ = linregress(c, log_I_norm)
    beta = -slope / (2 * r_i)
    return beta, r_corr**2


def recalibrate_beta(I_0_new, I_100_new, c_100=5.0, r_i=R_I):
    """
    Two-point recalibration from 0% and 100% measurements.

    Parameters
    ----------
    I_0_new   : float
        Measurement at c=0 [ADC counts]
    I_100_new : float
        Measurement at c=c_100 [ADC counts]
    c_100     : float
        Concentration of the 100% reference [mg/mL]
    r_i       : float
        Inner radius [mm]

    Returns
    -------
    beta_new : float
        Updated absorption coefficient [mL/(mg·mm)]
    """
    return -np.log(I_100_new / I_0_new) / (2 * r_i * c_100)


# ── Forward Model ─────────────────────────────────────────────────────────────

def sensor_signal(c_rt, r, beta, I_0):
    """
    Compute I_sensor(t) from a radial concentration profile c(r, t).

    I_sensor(t) = I_0 * exp(-beta * C(t))
    C(t) = 2 * integral_0^r_i c(r, t) dr

    Parameters
    ----------
    c_rt : ndarray, shape (Nr, Nt)
        Concentration profile c(r, t) [mg/mL]
    r    : ndarray, shape (Nr,)
        Radial coordinate vector [mm], from 0 to r_i
    beta : float
        Absorption coefficient [mL/(mg·mm)]
    I_0  : float
        Baseline intensity at c=0 [ADC counts]

    Returns
    -------
    I_sensor : ndarray, shape (Nt,)
        Sensor signal over time [ADC counts]
    """
    C_t = 2 * np.trapezoid(c_rt, r, axis=0)  # cumulative concentration (Nt,)
    return I_0 * np.exp(-beta * C_t)
