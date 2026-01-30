"""
Camera intrinsics EXIF injection utilities.

Provides functions to build and inject camera focal length, sensor dimensions,
and image resolution into JPEG EXIF metadata for photogrammetry compatibility.
"""

import logging
from typing import Optional

from openscan_firmware.config.sensors import (
    SENSOR_DATABASE,
    CAMERA_SENSOR_ALIASES,
    CameraSensor,
)

logger = logging.getLogger(__name__)


def get_sensor_for_camera(camera_name: str) -> Optional[CameraSensor]:
    """
    Look up sensor by camera name with aliasing support.

    Handles known aliases:
    - "arducam_64mp" -> "hawkeye"
    - "imx519" -> "imx519"
    - "imx708" -> "imx708"
    - "imx477" -> "imx477"

    Args:
        camera_name: Camera name from controller (e.g., "arducam_64mp", "imx519")

    Returns:
        CameraSensor if found, None otherwise (graceful degradation)
    """
    if not camera_name:
        logger.debug("Camera name is empty")
        return None

    # Try alias mapping first
    sensor_name = CAMERA_SENSOR_ALIASES.get(camera_name.lower(), camera_name.lower())
    sensor = SENSOR_DATABASE.get(sensor_name)

    if sensor is None:
        logger.warning(
            f"Unknown camera sensor: {camera_name} (mapped to {sensor_name}). "
            "Camera intrinsics will not be injected into EXIF."
        )

    return sensor


def focal_to_rational(focal_mm: float) -> tuple[int, int]:
    """
    Convert focal length to EXIF rational format.

    EXIF FocalLength tag requires a rational number (numerator, denominator).
    Uses denominator 100 for 2 decimal places of precision.

    Args:
        focal_mm: Focal length in millimeters (float)

    Returns:
        Tuple of (numerator, denominator) representing the rational value.
        Example: 4.28mm -> (428, 100)
    """
    # Use denominator 100 for 2 decimal precision
    numerator = int(round(focal_mm * 100))
    denominator = 100
    return (numerator, denominator)


def calculate_35mm_equivalent(focal_mm: float, sensor_width_mm: float) -> int:
    """
    Calculate 35mm film equivalent focal length.

    Standard formula for crop factor based on sensor width.
    Full-frame 35mm film is 36mm wide by definition.

    Args:
        focal_mm: Actual focal length in millimeters
        sensor_width_mm: Sensor width in millimeters

    Returns:
        35mm equivalent focal length as integer (rounded)

    Example:
        IMX519: 4.28mm focal length on 4.64mm sensor
        -> 4.28 * (36 / 4.64) ≈ 33.2 -> 33
    """
    if sensor_width_mm <= 0:
        return int(round(focal_mm))

    focal_35mm = focal_mm * (36.0 / sensor_width_mm)
    return int(round(focal_35mm))


def build_camera_intrinsics_exif(
    camera_name: str,
    image_width: int,
    image_height: int,
) -> dict:
    """
    Build EXIF dict with camera intrinsics for piexif injection.

    Looks up camera sensor by name and creates an EXIF dict containing:
    - FocalLength (rational format)
    - FocalLengthIn35mmFilm (integer)
    - PixelXDimension (integer, image width)
    - PixelYDimension (integer, image height)

    Returns empty dict if sensor not found (graceful degradation).

    Args:
        camera_name: Camera name from controller
        image_width: Output image width in pixels
        image_height: Output image height in pixels

    Returns:
        Dict with structure: {"Exif": {piexif_tag: value, ...}}
        Returns empty dict {} if sensor lookup fails.

    Example:
        >>> exif = build_camera_intrinsics_exif("imx519", 4656, 3496)
        >>> exif
        {
            "Exif": {
                37386: (428, 100),  # FocalLength 4.28mm
                41405: 33,          # FocalLengthIn35mmFilm
                41486: 4656,        # PixelXDimension
                41487: 3496,        # PixelYDimension
            }
        }
    """
    # Look up sensor
    sensor = get_sensor_for_camera(camera_name)
    if sensor is None:
        return {}

    if sensor.default_focal_length_mm is None:
        logger.warning(
            "Sensor %s has no default focal length; skipping EXIF intrinsics.",
            sensor.name,
        )
        return {}

    try:
        import piexif
    except Exception as exc:
        logger.warning(
            "piexif not available; skipping EXIF intrinsics injection: %s",
            exc,
        )
        return {}

    # Build EXIF dict
    try:
        exif_dict = {
            "Exif": {
                piexif.ExifIFD.FocalLength: focal_to_rational(
                    sensor.default_focal_length_mm
                ),
                piexif.ExifIFD.FocalLengthIn35mmFilm: calculate_35mm_equivalent(
                    sensor.default_focal_length_mm,
                    sensor.sensor_width_mm,
                ),
                piexif.ExifIFD.PixelXDimension: image_width,
                piexif.ExifIFD.PixelYDimension: image_height,
            }
        }

        logger.debug(
            f"Built camera intrinsics EXIF for {camera_name}: "
            f"f={sensor.default_focal_length_mm:.2f}mm, "
            f"f35mm={calculate_35mm_equivalent(sensor.default_focal_length_mm, sensor.sensor_width_mm)}mm, "
            f"dimensions={image_width}x{image_height}px"
        )

        return exif_dict

    except Exception as e:
        logger.error(f"Error building camera intrinsics EXIF: {e}")
        return {}
