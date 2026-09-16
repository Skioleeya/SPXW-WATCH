import numpy as np

# -----------------------------
# SVI parameter bounds
# -----------------------------
# 与原版的差异：原版在这里写死 SVI_BOUNDS / SVI_RANDOM_START_RANGES。本项目按
# 第 3 条「禁止硬编码」把它们搬进 ``config/surface.json``（键名 svi_bounds /
# svi_random_start_ranges，5 元组，顺序 (a, b, rho, m, sigma)），由
# ``models/surface_params.py::svi_fit_params()`` 读出，只有 models/svi_fit.py 用。
# 本模块因此变成纯函数模块（不含任何参数表），**数学实现一字未动**。


# -----------------------------
# Raw SVI total variance
# -----------------------------

def raw_svi_total_variance(k, a, b, rho, m, sigma):
    """
    Raw SVI parameterization.

    Parameters
    ----------
    k : array-like
        Log-moneyness:
            k = ln(K / F)

    a : float
        Overall variance level.

    b : float
        Smile slope magnitude.

    rho : float
        Skew asymmetry parameter.

    m : float
        Smile center.

    sigma : float
        Smile curvature parameter.

    Returns
    -------
    w : ndarray
        Total implied variance:
            w = IV^2 * T
    """
    k = np.asarray(k, dtype=float)

    return (
        a
        + b * (
            rho * (k - m)
            + np.sqrt((k - m) ** 2 + sigma ** 2)
        )
    )


# -----------------------------
# Total variance -> IV
# -----------------------------

def total_variance_to_iv(w, t):
    """
    Converts total variance into implied volatility.

    IV = sqrt(w / T)

    Parameters
    ----------
    w : array-like
        Total variance.

    t : float or array-like
        Time-to-expiry in years.

    Returns
    -------
    iv : ndarray
        Implied volatility.
    """
    w = np.asarray(w, dtype=float)
    t = np.asarray(t, dtype=float)

    safe_t = np.maximum(t, 1e-8)
    safe_w = np.maximum(w, 0.0)

    return np.sqrt(safe_w / safe_t)


# -----------------------------
# IV -> total variance
# -----------------------------

def iv_to_total_variance(iv, t):
    """
    Converts implied volatility into total variance.

    w = IV^2 * T
    """
    iv = np.asarray(iv, dtype=float)
    t = np.asarray(t, dtype=float)

    safe_iv = np.maximum(iv, 0.0)
    safe_t = np.maximum(t, 1e-8)

    return safe_iv ** 2 * safe_t


# -----------------------------
# Forward log-moneyness
# -----------------------------

def log_moneyness(strike, forward):
    """
    Computes forward log-moneyness.

    k = ln(K / F)

    Parameters
    ----------
    strike : array-like
        Option strikes.

    forward : float or array-like
        Forward price.

    Returns
    -------
    k : ndarray
        Log-moneyness.
    """
    strike = np.asarray(strike, dtype=float)
    forward = np.asarray(forward, dtype=float)

    safe_strike = np.maximum(strike, 1e-8)
    safe_forward = np.maximum(forward, 1e-8)

    return np.log(safe_strike / safe_forward)



# -----------------------------
# Black-Scholes forward price
# -----------------------------

def compute_forward_price(
    spot,
    t,
    risk_free_rate=0.0,
    dividend_yield=0.0,
):
    """
    Computes theoretical forward price under
    Black-Scholes carry assumptions.

    F = S * exp((r - q) * T)

    Parameters
    ----------
    spot : float
        Spot price.

    t : float
        Time-to-expiry in years.

    risk_free_rate : float
        Continuously compounded risk-free rate.

    dividend_yield : float
        Continuous dividend yield.

    Returns
    -------
    forward : float
        Forward price.
    """
    spot = max(float(spot), 1e-8)
    t = max(float(t), 1e-8)

    r = float(risk_free_rate)
    q = float(dividend_yield)

    return spot * np.exp((r - q) * t)


# -----------------------------
# Initial SVI guess
# -----------------------------

def initial_svi_guess(k, w):
    """
    Produces a rough initial parameter guess for optimization.

    This does not need to be perfect.
    It only helps optimizer stability.
    """
    k = np.asarray(k, dtype=float)
    w = np.asarray(w, dtype=float)

    min_w = float(np.nanmin(w))
    mean_w = float(np.nanmean(w))

    a = max(min_w * 0.5, 1e-6)

    b = max((np.nanmax(w) - np.nanmin(w)), 0.01)

    rho = -0.3

    m = float(np.nanmean(k))

    sigma = 0.2

    return np.array([a, b, rho, m, sigma], dtype=float)


# -----------------------------
# SVI objective function
# -----------------------------

def svi_objective(params, k, w_market):
    """
    Least-squares objective for SVI calibration.

    Minimizes:
        sum((w_market - w_svi)^2)
    """
    a, b, rho, m, sigma = params

    w_model = raw_svi_total_variance(
        k,
        a,
        b,
        rho,
        m,
        sigma,
    )

    residual = w_market - w_model

    return float(np.nansum(residual ** 2))


# -----------------------------
# Root-mean-square error
# -----------------------------

def rmse(actual, predicted):
    """
    Root mean square error.
    """
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)

    residual = actual - predicted

    return float(np.sqrt(np.nanmean(residual ** 2)))


# -----------------------------
# No-arbitrage: butterfly g(k)
# -----------------------------

def svi_butterfly_g(k, a, b, rho, m, sigma):
    """
    Gatheral's g(k) function for butterfly arbitrage check.

    g(k) >= 0 is required for no butterfly arbitrage (non-negative risk-neutral
    density).  Derived from Lee (2004) / Gatheral & Jacquier (2014):

        g(k) = (1 - k*w'/(2w))^2 - (w')^2/4 * (1/w + 1/4) + w''/2

    where w, w', w'' are the total-variance smile and its first two derivatives
    with respect to k.
    """
    k = np.asarray(k, dtype=float)
    d = k - m
    sqrt_term = np.sqrt(d ** 2 + sigma ** 2)

    w            = a + b * (rho * d + sqrt_term)
    w_prime      = b * (rho + d / sqrt_term)
    w_double_prime = b * sigma ** 2 / sqrt_term ** 3

    safe_w = np.maximum(w, 1e-10)

    g = (
        (1.0 - k * w_prime / (2.0 * safe_w)) ** 2
        - w_prime ** 2 / 4.0 * (1.0 / safe_w + 0.25)
        + w_double_prime / 2.0
    )
    return g


def svi_no_arb_constraints(k_min, k_max):
    """
    Returns SLSQP inequality constraints (fun >= 0) for SVI no-arbitrage.

    Two conditions enforced:
    1. Non-negative minimum variance: a + b*sigma*sqrt(1 - rho^2) >= 0
    2. Butterfly arbitrage-free: g(k) >= 0 at 5 check points across the data range

    Parameters
    ----------
    k_min, k_max : float
        Observed log-moneyness range for the slice being fitted.
    """
    k_check = np.linspace(k_min - 0.1, k_max + 0.1, 5)

    constraints = [
        {
            "type": "ineq",
            "fun": lambda p: p[0] + p[1] * p[4] * np.sqrt(max(1.0 - p[2] ** 2, 0.0)),
        },
    ]

    for kv in k_check:
        kv = float(kv)
        constraints.append({
            "type": "ineq",
            "fun": lambda p, k=kv: float(np.nanmin(
                svi_butterfly_g(k, p[0], p[1], p[2], p[3], p[4])
            )),
        })

    return constraints


# -----------------------------
# Vega-proxy weights
# -----------------------------

def vega_weights(k, t):
    """
    Approximate vega weights for the SVI objective function.

    Uses a Gaussian centred at ATM (k = 0) with standard deviation sqrt(t),
    which approximates the shape of Black-Scholes vega across log-moneyness.
    Near-ATM options receive the highest weight; deep wings are down-weighted.

    Weights are normalised to sum to 1.
    """
    k = np.asarray(k, dtype=float)
    t_safe = max(float(t), 1e-4)

    unnorm = np.exp(-0.5 * k ** 2 / t_safe)
    total  = unnorm.sum()
    if total <= 0:
        return np.ones(len(k), dtype=float) / len(k)
    return unnorm / total


# -----------------------------
# Weighted SVI objective
# -----------------------------

def svi_weighted_objective(params, k, w_market, weights):
    """
    Vega-weighted least-squares objective for SVI calibration.

    Minimises: sum(weights * (w_market - w_svi)^2)
    """
    a, b, rho, m, sigma = params
    w_model  = raw_svi_total_variance(k, a, b, rho, m, sigma)
    residual = w_market - w_model
    return float(np.dot(weights, residual ** 2))