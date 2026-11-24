"""Ed25519 signature verification (RFC 8032, 5.1.7) in plain Python: the update checks one signature per
release (updates.py), so speed does not matter and no dependency is needed for it."""
from __future__ import annotations

import hashlib

P = 2**255 - 19
L = 2**252 + 27742317777372353535851937790883648493
D = -121665 * pow(121666, P - 2, P) % P
# A square root of -1.
ROOT = pow(2, (P - 1) // 4, P)


def _add(a: tuple, b: tuple) -> tuple:
    """Two points in extended coordinates (X, Y, Z, T)."""
    x1, y1, z1, t1 = a
    x2, y2, z2, t2 = b
    first, second = (y1 - x1) * (y2 - x2) % P, (y1 + x1) * (y2 + x2) % P
    third, fourth = 2 * t1 * t2 * D % P, 2 * z1 * z2 % P
    e, f, g, h = second - first, fourth - third, fourth + third, second + first
    return e * f % P, g * h % P, f * g % P, e * h % P


def _mul(scalar: int, point: tuple) -> tuple:
    found = (0, 1, 1, 0)
    while scalar:
        if scalar & 1:
            found = _add(found, point)
        point = _add(point, point)
        scalar >>= 1
    return found


def _same(a: tuple, b: tuple) -> bool:
    return (a[0] * b[2] - b[0] * a[2]) % P == 0 and (a[1] * b[2] - b[1] * a[2]) % P == 0


def _x(y: int, sign: int) -> int | None:
    """The x of the curve point with this y and the sign bit, or None."""
    if y >= P:
        return None
    square = (y * y - 1) * pow(D * y * y + 1, P - 2, P) % P
    if square == 0:
        return None if sign else 0
    x = pow(square, (P + 3) // 8, P)
    if (x * x - square) % P:
        x = x * ROOT % P
    if (x * x - square) % P:
        return None
    return P - x if x & 1 != sign else x


def _point(data: bytes) -> tuple | None:
    y = int.from_bytes(data, "little")
    sign, y = y >> 255, y & ((1 << 255) - 1)
    x = _x(y, sign)
    return None if x is None else (x, y, 1, x * y % P)


_BASE_Y = 4 * pow(5, P - 2, P) % P
BASE = (_x(_BASE_Y, 0), _BASE_Y, 1, _x(_BASE_Y, 0) * _BASE_Y % P)


def verify(public: bytes, message: bytes, signature: bytes) -> bool:
    """Whether `signature` is the signature of `message` by the key whose public half is `public` (32 bytes)."""
    if len(public) != 32 or len(signature) != 64:
        return False
    key, r = _point(public), _point(signature[:32])
    s = int.from_bytes(signature[32:], "little")
    if key is None or r is None or s >= L:
        return False
    h = int.from_bytes(hashlib.sha512(signature[:32] + public + message).digest(), "little") % L
    return _same(_mul(s, BASE), _add(r, _mul(h, key)))
