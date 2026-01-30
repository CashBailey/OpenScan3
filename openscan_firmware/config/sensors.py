"""
Camera Sensor Database

Provides camera sensor intrinsic parameters for known sensors.
Used for SfM/Meshroom export to generate accurate camera poses.

Common sensors in OpenScan setups:
- IMX519 (Arducam 16MP AF): 4.64mm x 3.48mm sensor
- Hawkeye (Arducam 64MP AF): 6.45mm x 4.84mm sensor  
- IMX708 (RPi Camera Module 3): 6.45mm x 3.63mm sensor
- IMX477 (RPi HQ Camera): 6.287mm x 4.712mm sensor
"""

from typing import Optional
from pydantic import BaseModel, Field


class CameraSensor(BaseModel):
    """Camera sensor physical parameters for intrinsic calibration."""
    
    name: str = Field(description="Sensor model name (e.g. 'imx519', 'hawkeye')")
    sensor_width_mm: float = Field(description="Sensor width in millimeters")
    sensor_height_mm: float = Field(description="Sensor height in millimeters")
    
    # Native resolution (full sensor)
    native_width_px: int = Field(description="Native sensor width in pixels")
    native_height_px: int = Field(description="Native sensor height in pixels")
    
    # Optional: approximate focal length if known
    default_focal_length_mm: Optional[float] = Field(
        default=None,
        description="Default/typical focal length in mm (lens dependent)"
    )
    
    @property
    def pixel_size_um(self) -> float:
        """Calculate pixel size in micrometers."""
        return (self.sensor_width_mm / self.native_width_px) * 1000
    
    def focal_length_px(self, focal_mm: float, image_width_px: int) -> float:
        """Convert focal length from mm to pixels for a given output resolution.
        
        Args:
            focal_mm: Focal length in millimeters
            image_width_px: Output image width in pixels
            
        Returns:
            Focal length in pixels
        """
        # Scale factor from native to output resolution
        scale = image_width_px / self.native_width_px
        # Focal in pixels at native resolution: f_px = f_mm * (native_width_px / sensor_width_mm)
        focal_native_px = focal_mm * (self.native_width_px / self.sensor_width_mm)
        return focal_native_px * scale


# Known sensor database
SENSOR_DATABASE: dict[str, CameraSensor] = {
    # Arducam IMX519 16MP (common in OpenScan Mini)
    "imx519": CameraSensor(
        name="imx519",
        sensor_width_mm=4.64,
        sensor_height_mm=3.48,
        native_width_px=4656,
        native_height_px=3496,
        default_focal_length_mm=4.28,  # M12 lens typical
    ),
    
    # Arducam Hawkeye 64MP (premium option)
    "hawkeye": CameraSensor(
        name="hawkeye",
        sensor_width_mm=6.45,
        sensor_height_mm=4.84,
        native_width_px=9152,
        native_height_px=6944,
        default_focal_length_mm=5.1,
    ),
    
    # Raspberry Pi Camera Module 3 (IMX708)
    "imx708": CameraSensor(
        name="imx708",
        sensor_width_mm=6.45,
        sensor_height_mm=3.63,
        native_width_px=4608,
        native_height_px=2592,
        default_focal_length_mm=4.74,
    ),
    
    # Raspberry Pi HQ Camera (IMX477)
    "imx477": CameraSensor(
        name="imx477",
        sensor_width_mm=6.287,
        sensor_height_mm=4.712,
        native_width_px=4056,
        native_height_px=3040,
        default_focal_length_mm=6.0,  # Varies by lens
    ),
}

# Camera name to sensor name aliases
# Maps controller camera names to sensor database entries
CAMERA_SENSOR_ALIASES = {
    "arducam_64mp": "hawkeye",
    "imx519": "imx519",
    "imx708": "imx708",
    "imx477": "imx477",
}


def get_sensor_by_camera_name(camera_name: str) -> Optional[CameraSensor]:
    """Look up sensor by camera name with alias support.

    Args:
        camera_name: Camera name from controller (e.g., 'arducam_64mp', 'imx519')

    Returns:
        CameraSensor if found, None otherwise
    """
    sensor_name = CAMERA_SENSOR_ALIASES.get(camera_name.lower(), camera_name.lower())
    return SENSOR_DATABASE.get(sensor_name)


def get_sensor_by_name(name: str) -> Optional[CameraSensor]:
    """Look up sensor by name (case-insensitive).
    
    Args:
        name: Sensor name or model identifier
        
    Returns:
        CameraSensor if found, None otherwise
    """
    return SENSOR_DATABASE.get(name.lower())


def get_sensor_names() -> list[str]:
    """Get list of all known sensor names."""
    return list(SENSOR_DATABASE.keys())


def estimate_sensor_from_resolution(width: int, height: int) -> Optional[CameraSensor]:
    """Attempt to identify sensor from native resolution.
    
    Args:
        width: Image width in pixels
        height: Image height in pixels
        
    Returns:
        Best matching CameraSensor or None
    """
    # Try exact native match first
    for sensor in SENSOR_DATABASE.values():
        if sensor.native_width_px == width and sensor.native_height_px == height:
            return sensor
    
    # Try matching aspect ratio (within tolerance)
    target_ratio = width / height
    for sensor in SENSOR_DATABASE.values():
        sensor_ratio = sensor.native_width_px / sensor.native_height_px
        if abs(sensor_ratio - target_ratio) < 0.01:
            # Check if resolution is a reasonable downscale
            if width <= sensor.native_width_px and height <= sensor.native_height_px:
                return sensor
    
    return None
