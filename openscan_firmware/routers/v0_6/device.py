from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel, ValidationError
import os
import json
import tempfile
import shutil
import re
from pathlib import Path

from openscan_firmware.models.scanner import ScannerDevice
from openscan_firmware.controllers import device

from openscan_firmware.utils.settings import resolve_settings_dir
from .cameras import CameraStatusResponse
from .motors import MotorStatusResponse
from .lights import LightStatusResponse
from openscan_firmware.security import require_admin

router = APIRouter(
    prefix="/device",
    tags=["device"],
    responses={404: {"description": "Not found"}},
)


class DeviceConfigRequest(BaseModel):
    config_file: str

class DeviceStatusResponse(BaseModel):
    name: str
    model: str
    shield: str
    cameras: dict[str, CameraStatusResponse]
    motors: dict[str, MotorStatusResponse]
    lights: dict[str, LightStatusResponse]
    initialized: bool

class DeviceControlResponse(BaseModel):
    success: bool
    message: str
    status: DeviceStatusResponse


_SAFE_CONFIG_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


def _validate_config_filename(config_name: str) -> str:
    candidate = (config_name or "").strip()
    if not candidate:
        raise HTTPException(status_code=400, detail="Config filename is required.")
    if not _SAFE_CONFIG_NAME.match(candidate):
        raise HTTPException(status_code=400, detail="Config filename contains invalid characters.")
    if os.sep in candidate or (os.altsep and os.altsep in candidate) or ".." in candidate:
        raise HTTPException(status_code=400, detail="Config filename must not contain path separators.")
    return candidate


def _resolve_config_path(config_value: str, available_configs: list[dict]) -> str:
    if not config_value:
        raise HTTPException(status_code=400, detail="Config filename is required.")

    config_paths: dict[Path, dict] = {}
    config_files: dict[str, dict] = {}
    for config in available_configs:
        path = config.get("path")
        filename = config.get("filename")
        if path:
            config_paths[Path(path).resolve()] = config
        if filename:
            config_files[filename] = config

    if not os.path.dirname(config_value):
        safe_name = _validate_config_filename(config_value)
        lookup_names = {safe_name}
        if not safe_name.endswith(".json"):
            lookup_names.add(f"{safe_name}.json")
        for name in lookup_names:
            match = config_files.get(name)
            if match and match.get("path"):
                return str(match["path"])
        raise HTTPException(status_code=404, detail=f"Config file not found: {config_value}")

    candidate = Path(config_value).expanduser().resolve()
    if candidate in config_paths:
        return str(candidate)

    raise HTTPException(status_code=404, detail=f"Config file not found: {config_value}")

@router.get("/info", response_model=DeviceStatusResponse)
async def get_device_info():
    """Get information about the device

    Returns:
        dict: A dictionary containing information about the device
    """
    try:
        info = device.get_device_info()
        return DeviceStatusResponse.model_validate(info)
    except ValidationError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Device configuration is not loaded.",
                "errors": exc.errors(),
            },
        )
    except (RuntimeError, OSError) as e:
        raise HTTPException(status_code=500, detail=f"Error getting device info: {str(e)}")


@router.get("/configurations")
async def list_config_files():
    """List all available device configuration files"""
    try:
        configs = device.get_available_configs()
        return {"status": "success", "configs": configs}
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Error listing configuration files: {str(e)}")


@router.post("/configurations/", response_model=DeviceControlResponse)
async def add_config_json(config_data: ScannerDevice, filename: DeviceConfigRequest):
    """Add a device configuration from a JSON object

    This endpoint accepts a JSON object with the device configuration,
    validates it and saves it to a file.

    Args:
        config_data: The device configuration to add
        filename: The filename to save the configuration as

    Returns:
        dict: A dictionary containing the status of the operation
    """
    try:
        # Create a temporary file to save the configuration
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w") as temp_file:
            # Convert the model to a dictionary and save it as JSON
            config_dict = config_data.dict()
            json.dump(config_dict, temp_file, indent=4)
            temp_path = temp_file.name

        # Save to settings directory with a meaningful name
        settings_dir = resolve_settings_dir("device")
        os.makedirs(settings_dir, exist_ok=True)

        safe_filename = _validate_config_filename(filename.config_file)
        if not safe_filename.endswith(".json"):
            safe_filename = f"{safe_filename}.json"
        target_path = Path(settings_dir) / safe_filename

        # Move the temporary file to the target path
        shutil.move(temp_path, str(target_path))

        return DeviceControlResponse(
            success=True,
            message="Configuration saved successfully",
            status=DeviceStatusResponse.model_validate(device.get_device_info())
        )

    except HTTPException:
        raise
    except (OSError, json.JSONDecodeError, ValidationError) as e:
        raise HTTPException(status_code=500, detail=f"Error setting device configuration: {str(e)}")


@router.patch("/configurations/current", response_model=DeviceControlResponse)
async def save_device_config():
    """Save the current device configuration to a file

    This endpoint saves the current device configuration to device_config.json.

    Returns:
        dict: A dictionary containing the status of the operation
    """
    if device.save_device_config():
        return DeviceControlResponse(
            success=True,
            message="Configuration saved successfully",
            status=DeviceStatusResponse.model_validate(device.get_device_info())
        )
    else:
        raise HTTPException(status_code=500, detail="Failed to save device configuration")

@router.put("/configurations/current", response_model=DeviceControlResponse)
async def set_config_file(config_data: DeviceConfigRequest):
    """Set the device configuration from a file and initialize hardware

    Args:
        config_data: The device configuration to set

    Returns:
        dict: A dictionary containing the status of the operation
    """
    try:
        # Get available configs
        available_configs = device.get_available_configs()

        # Check if the config file exists in available configs
        config_file = _resolve_config_path(config_data.config_file, available_configs)

        # Set device config
        if device.set_device_config(config_file):
            return DeviceControlResponse(
                success=True,
                message="Configuration loaded successfully",
                status=DeviceStatusResponse.model_validate(device.get_device_info())
            )
        else:
            raise HTTPException(status_code=500, detail="Failed to load device configuration")

    except HTTPException:
        # Re-raise HTTP exceptions to preserve status code and detail
        raise
    except (OSError, json.JSONDecodeError, ValidationError, RuntimeError) as e:
        raise HTTPException(status_code=500, detail=f"Error setting device configuration: {str(e)}")


@router.post("/configurations/current/initialize", response_model=DeviceControlResponse)
async def reinitialize_hardware(detect_cameras: bool = False):
    """Reinitialize hardware components

    This can be used in case of a hardware failure or to reload the hardware components.

    Args:
        detect_cameras: Whether to detect cameras

    Returns:
        dict: A dictionary containing the status of the operation
    """
    try:
        device.initialize(detect_cameras=detect_cameras)
        return DeviceControlResponse(
            success=True,
            message="Hardware reinitialized successfully",
            status=DeviceStatusResponse.model_validate(device.get_device_info())
        )
    except (RuntimeError, OSError, ValidationError) as e:
        raise HTTPException(status_code=500, detail=f"Error reloading hardware: {str(e)}")


@router.post("/reboot", response_model=bool)
def reboot(save_config: bool = False, _admin: None = Depends(require_admin)):
    """Reboot system and optionally save config.

    Args:
        save_config: Whether to save the current configuration before rebooting
    """
    device.reboot(save_config)
    return True


@router.post("/shutdown", response_model=bool)
def shutdown(save_config: bool = False, _admin: None = Depends(require_admin)) -> None:
    """Shutdown system and optionally save config.

    Args:
        save_config: Whether to save the current configuration before shutting down
    """
    device.shutdown(save_config)
    return True
