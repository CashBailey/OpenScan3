from dataclasses import dataclass
from enum import Enum


class PathMethod(Enum):
    FIBONACCI = "fibonacci"
    # Removed SPIRAL and ARCHIMEDES as requested
    # Future methods that can be implemented
    # GRID = "grid"


@dataclass
class CartesianPoint3D:
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class PolarPoint3D:
    """
    PolarPoint3D represents a point in spherical coordinates
    theta: polar angle (0° to 180°), where:
        - 0° is the North Pole
        - 90° is the Equator
        - 180° is the South Pole
    fi: azimuthal angle (0° to 360°), rotation around z-axis
    r: radius, default is 1 for unit sphere
    """
    theta: float  # 0° to 180° (pole to pole)
    fi: float  # 0° to 360° (rotation around z-axis)
    r: float = 1

    def __post_init__(self):
        if not (0 <= self.theta <= 180):
            raise ValueError(f"theta must be between 0 and 180 degrees, got {self.theta}")
        if not (0 <= self.fi <= 360):
            raise ValueError(f"fi must be between 0 and 360 degrees, got {self.fi}")
