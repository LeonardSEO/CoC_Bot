"""Conservative local price-colour observations; no inferred bank balances."""
import numpy as np


def red_price_mask(frame):
    rgb = np.asarray(frame).astype(np.int16)
    if rgb.ndim != 3 or rgb.shape[2] != 3 or not rgb.size:
        raise ValueError('Price observation requires a nonempty RGB crop')
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    # Includes the old (255,136,127) palette and darker/antialiased variants.
    return (r >= 150) & (r-g >= 45) & (r-b >= 45) & (np.abs(g-b) <= 65)


def price_status(row):
    """True: white price indicator; False: red; None: unreadable.

    Inspect only the right-hand price column, avoiding name/icon colours.
    This observes the game's indicator, not numerical cost versus balance.
    """
    row = np.asarray(row)
    if row.ndim != 3 or row.shape[2] != 3 or not row.size:
        raise ValueError('Price observation requires a nonempty RGB row')
    price = row[:, int(row.shape[1]*.55):]
    if np.count_nonzero(red_price_mask(price)) >= 4:
        return False
    rgb = price.astype(np.int16)
    white = (rgb.min(axis=2) >= 220) & (np.ptp(rgb, axis=2) <= 20)
    if np.count_nonzero(white) >= 6:
        return True
    return None
