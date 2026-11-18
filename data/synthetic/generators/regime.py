"""Independent parameter draws for explicit family x affine-shape regimes.

Surface draws are uniform on the *parameter sphere*, not area-uniform on
an affine ellipsoid. Curve draws are a noisy helix. Scale factors describe
an affine transform, not a promise about the realised covariance spectrum.
"""

from __future__ import annotations
import math
from data.synthetic.generators.common import SplitMix64
from data.synthetic.generators.gaussian_ellipsoid import rotation_matrix, apply_rotation

FAMILIES = ("volume", "surface", "curve", "clustered")
SHAPES = {
    "isotropic": (1.0, 1.0, 1.0),
    "oblate": (4.0, 4.0, 1.0),
    "prolate": (16.0, 1.0, 1.0),
    "triaxial": (16.0, 4.0, 1.0),
}


def regime_points(count, family, shape, seed):
    if count < 1 or family not in FAMILIES or shape not in SHAPES:
        raise ValueError("invalid regime family, shape or point count")
    rng = SplitMix64(seed)
    rotation = rotation_matrix(seed)
    points = []
    for _ in range(count):
        x, y = rng.gaussian_pair()
        z, _unused = rng.gaussian_pair()
        if family == "surface":
            norm = math.hypot(x, y, z)
            if norm == 0:
                raise ValueError("zero Gaussian sphere direction")
            p = (x / norm, y / norm, z / norm)
        elif family == "curve":
            t = rng.uniform(-math.pi, math.pi)
            p = (math.cos(t) + 0.02 * x, math.sin(t) + 0.02 * y, t / math.pi + 0.02 * z)
        elif family == "clustered":
            center = ((-1.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 1.0))[
                rng.next_u64() % 3
            ]
            p = tuple(center[j] + 0.2 * v for j, v in enumerate((x, y, z)))
        else:
            p = (x, y, z)
        points.append(
            apply_rotation(tuple(v * a for v, a in zip(p, SHAPES[shape])), rotation)
        )
    return points
