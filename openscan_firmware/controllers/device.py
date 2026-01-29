"""OpenScan Hardware Manager Module

This module is responsible for initializing and managing hardware components
like cameras, motors, and lights. It also handles different scanner models
and their specific configurations.
"""

import json
import logging
import os
import subprocess
import pathlib
from pathlib import Path
from typing import Dict, List, Optional
from importlib import resources
from dotenv import load_dotenv

from linuxpy.video.device import iter_video_capture_devices
import gphoto2 as gp

from openscan_firmware.models.camera import Camera, CameraType
from openscan_firmware.models.motor import Motor, Endstop
from openscan_firmware.models.light import Light
from openscan_firmware.models.scanner import ScannerDevice, ScannerModel, ScannerShield

from openscan_firmware.config.camera import CameraSettings
from openscan_firmware.config.motor import MotorConfig
from openscan_firmware.config.light import LightConfig
from openscan_firmware.config.endstop import EndstopConfig
from openscan_firmware.config.cloud import (
    load_cloud_settings_from_env,
    set_cloud_settings,
    mask_secret,
)
from openscan_firmware.controllers.services.cloud_settings import (
    load_persistent_cloud_settings,
    set_active_source,
)

from openscan_firmware.controllers.hardware.cameras.camera import (
    create_camera_controller,
    get_all_camera_controllers,
    get_available_camera_types,
    is_camera_type_available,
    remove_camera_controller,
)
from openscan_firmware.controllers.hardware.motors import create_motor_controller, get_all_motor_controllers, get_motor_controller, \
    remove_motor_controller
from openscan_firmware.controllers.hardware.lights import create_light_controller, get_all_light_controllers, remove_light_controller, \
    get_light_controller
from openscan_firmware.controllers.hardware.endstops import EndstopController
from openscan_firmware.controllers.hardware.gpio import cleanup_all_pins

from openscan_firmware.controllers.services.projects import get_project_manager
from openscan_firmware.controllers.services.device_events import schedule_device_status_broadcast
from openscan_firmware.utils.settings import (
    resolve_settings_dir,
    resolve_settings_file,
)

logger = logging.getLogger(__name__)

# Current scanner model
_scanner_device = ScannerDevice(
    name="Unknown device",
    model=None,
    shield=None,
    cameras={},
    motors={},
    lights={},
    endstops={},
    initialized=False,
)

_endstop_controllers: dict[str, EndstopController] = {}

# Path to device configuration file (persisted)
BASE_DIR = pathlib.Path(__file__).parent.parent.parent
SETTINGS_DIR = resolve_settings_dir("device")
DEVICE_CONFIG_FILE = resolve_settings_file("device", "device_config.json")


def load_device_config(config_file=None) -> dict:
    """Load device configuration from a file

    Args:
        config_file: Path to configuration file to load as preset.
                     If None, loads from device_config.json or default_minimal_config.json

    Returns:
        dict: Loaded device configuration
    """
    # populate default config dictionary
    config_dict = _scanner_device.model_dump(mode='json')

    # Determine which configuration file to load
    if config_file is None:
        # No file specified, try to load device_config.json in selected settings dir
        try:
            DEVICE_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning("Could not ensure settings directory exists: %s: %s", DEVICE_CONFIG_FILE.parent, e)
        if not os.path.exists(DEVICE_CONFIG_FILE):
            # If device_config.json doesn't exist, save minimal model as starting point
            with open(DEVICE_CONFIG_FILE, "w") as f:
                json.dump(config_dict, f, indent=4)
            logger.warning("No device configuration found. Created default at %s.", DEVICE_CONFIG_FILE)
        config_file = str(DEVICE_CONFIG_FILE)
    try:
        logger.debug(f"Loading device configuration from: {config_file}")
        if os.path.exists(config_file):
            with open(config_file, "r") as f:
                loaded_config_from_file = json.load(f)
                config_dict.update(loaded_config_from_file)

                # if a config is specified, save it as device_config.json
                if Path(config_file).resolve() != DEVICE_CONFIG_FILE.resolve():
                    with open(DEVICE_CONFIG_FILE, "w") as f:
                        json.dump(config_dict, f, indent=4)
            logger.info(f"Loaded device configuration for: {config_dict['name']} with {config_dict['shield']}")
    except (OSError, json.JSONDecodeError, KeyError) as e:
        logger.error(f"Error loading device configuration: {e}")

    return config_dict


def save_device_config() -> bool:
    """Save the current device configuration to device_config.json"""
    #global _scanner_device

    try:
        os.makedirs(os.path.dirname(DEVICE_CONFIG_FILE), exist_ok=True)

        config_to_save = {
            "name": _scanner_device.name,
            "model": _scanner_device.model.value if _scanner_device.model else None,
            "shield": _scanner_device.shield.value if _scanner_device.shield else None,
            "cameras": {name: cam.model_dump(mode='json') for name, cam in _scanner_device.cameras.items()},
            "motors": {name: motor.settings.model_dump(mode='json') for name, motor in _scanner_device.motors.items()},
            "lights": {name: light.settings.model_dump(mode='json') for name, light in _scanner_device.lights.items()},
            "endstops": {name: endstop.model_dump(mode='json') for name, endstop in _scanner_device.endstops.items()}
        }

        with open(DEVICE_CONFIG_FILE, "w") as f:
            json.dump(config_to_save, f, indent=4)

        logger.info(f"Device configuration saved successfully to {DEVICE_CONFIG_FILE}")
        return True
    except Exception as e:
        logger.error(f"Error saving device configuration: {e}", exc_info=True)
        return False


def set_device_config(config_file) -> bool:
    """Set the device configuration from a file and initialize hardware

    Args:
        config_file: Path to the configuration file

    Returns:
        bool: True if successful, False otherwise
    """

    try:
        initialize(load_device_config(config_file))
    except Exception as e:
        logger.error("Failed to apply device configuration from %s: %s", config_file, e, exc_info=True)
        return False
    return True


def get_scanner_model():
    """Get the current scanner model"""
    return _scanner_device.model


def get_device_info():
    """Get information about the device"""
    return {
        "name": _scanner_device.name,
        "model": _scanner_device.model.value if _scanner_device.model else None,
        "shield": _scanner_device.shield.value if _scanner_device.shield else None,
        "cameras": {name: controller.get_status() for name, controller in get_all_camera_controllers().items()},
        "motors": {name: controller.get_status() for name, controller in get_all_motor_controllers().items()},
        "lights": {name: controller.get_status() for name, controller in get_all_light_controllers().items()},
        "initialized": _scanner_device.initialized
    }


def _load_camera_config(settings: dict) -> CameraSettings:
    try:
        return CameraSettings(**settings)
    except Exception as e:
        # Return default settings if error occured
        logger.error("Error loading camera settings: %s", e, exc_info=True)
        return CameraSettings()


def _load_motor_config(settings: dict) -> MotorConfig:
    """Load motor configuration for the current model"""
    try:
        return MotorConfig(**settings)
    except Exception as e:
        # Return default settings if error occured
        logger.error("Error loading motor settings: %s", e, exc_info=True)
        return MotorConfig()


def _load_light_config(settings: dict) -> LightConfig:
    """Load light configuration for the current model"""
    try:
        return LightConfig(**settings)
    except Exception as e:
        # Return default settings if error occured
        logger.error("Error loading light settings: %s", e, exc_info=True)
        return LightConfig()


def _load_endstop_config(settings: dict) -> EndstopConfig:
    """Helper function to load and validate endstop settings from a dictionary."""
    try:
        return EndstopConfig(**settings)
    except Exception as e:
        # Return default settings if error occured
        logger.error("Error loading endstop settings: %s", e, exc_info=True)
        return EndstopConfig()


def _detect_cameras() -> Dict[str, Camera]:
    """Get a list of available cameras"""
    logger.debug("Loading cameras...")

    global _scanner_device

    def _unique_camera_name(base_name: str | None) -> str:
        name = base_name or "camera"
        if name not in cameras:
            return name
        suffix = 2
        while True:
            candidate = f"{name}-{suffix}"
            if candidate not in cameras:
                return candidate
            suffix += 1

    for camera_controller in list(get_all_camera_controllers()):
        remove_camera_controller(camera_controller)

    cameras = {}

    # Get Linux cameras
    try:
        linuxpycameras = iter_video_capture_devices()
        for cam in linuxpycameras:
            try:
                cam.open()
                if cam.info.card not in ("unicam", "bcm2835-isp"):
                    cam_name = _unique_camera_name(cam.info.card)
                    cameras[cam_name] = Camera(
                        type=CameraType.LINUXPY,
                        name=cam_name,
                        path=cam.filename,
                        settings=None
                    )
            finally:
                try:
                    cam.close()
                except Exception:
                    logger.debug("Failed to close Linux camera handle for %s", getattr(cam, "filename", "?"))
    except Exception as e:
        logger.error(f"Error loading Linux cameras: {e}")

    # Get GPhoto2 cameras
    try:
        gphoto2_cameras = gp.Camera.autodetect()
        for c in gphoto2_cameras:
            cam_name = _unique_camera_name(c[0])
            cameras[cam_name] = Camera(
                type=CameraType.GPHOTO2,
                name=cam_name,
                path=c[1],
                settings=None
            )
    except Exception as e:
        logger.error(f"Error loading GPhoto2 cameras: {e}")

    # Get Picamera2
    if is_camera_type_available(CameraType.PICAMERA2):
        try:
            from picamera2 import Picamera2

            picam = Picamera2()
            try:
                picam_name = picam.camera_properties.get("Model")
                cam_name = _unique_camera_name(picam_name)
                cameras[cam_name] = Camera(
                    type=CameraType.PICAMERA2,
                    name=cam_name,
                    path="/dev/video0" + str(picam.camera_properties.get("Location")),
                    settings=CameraSettings()
                )
            finally:
                try:
                    picam.close()
                finally:
                    del picam
        except IndexError as e:
            logger.critical(
                "Error loading Picamera2, most likely because of incorrect dtoverlay in /boot/firmware/config.txt.",
                exc_info=True,
            )
        except Exception as e:
            logger.error(f"Error loading Picamera2: {e}", exc_info=True)
    else:
        logger.info("Skipping Picamera2 detection: module not available on this system.")
    return cameras


def initialize(config: dict | None = None, detect_cameras = False):
    """Detect and load hardware components"""
    global _scanner_device
    # Load environment variables
    load_dotenv()
    if config is None:
        config = _scanner_device.model_dump(mode='json')
    config = config or {}
    config_cameras = config.get("cameras") or {}
    config_motors = config.get("motors") or {}
    config_lights = config.get("lights") or {}
    config_endstops = config.get("endstops") or {}
    if not isinstance(config_cameras, dict):
        logger.warning("Invalid cameras config; expected dict, got %s", type(config_cameras).__name__)
        config_cameras = {}
    if not isinstance(config_motors, dict):
        logger.warning("Invalid motors config; expected dict, got %s", type(config_motors).__name__)
        config_motors = {}
    if not isinstance(config_lights, dict):
        logger.warning("Invalid lights config; expected dict, got %s", type(config_lights).__name__)
        config_lights = {}
    if not isinstance(config_endstops, dict):
        logger.warning("Invalid endstops config; expected dict, got %s", type(config_endstops).__name__)
        config_endstops = {}

    # if already initialized, remove all controllers for reinitializing
    if _scanner_device.initialized:
        logger.debug("Hardware already initialized. Cleaning up old controllers.")
        for name in list(get_all_motor_controllers().keys()):
            remove_motor_controller(name)
        for name in list(get_all_light_controllers().keys()):
            remove_light_controller(name)
        for name in list(get_all_camera_controllers().keys()):
            remove_camera_controller(name)
        for name, endstop_controller in list(_endstop_controllers.items()):
            try:
                endstop_controller.cleanup()
            except Exception as e:
                logger.error("Error cleaning up endstop '%s': %s", name, e)
            _endstop_controllers.pop(name, None)
        cleanup_all_pins()
        logger.debug("Cleaned up old controllers.")

    # Detect hardware
    if detect_cameras or not config_cameras:
        camera_objects = _detect_cameras()
    else:
        camera_objects = {}
        for cam_name, cam_data in config_cameras.items():
            if not isinstance(cam_data, dict):
                logger.warning("Skipping camera '%s': invalid config entry.", cam_name)
                continue
            try:
                cam_type = CameraType(cam_data.get("type"))
            except Exception:
                logger.warning("Skipping camera '%s': invalid type '%s'.", cam_name, cam_data.get("type"))
                continue
            camera = Camera(
                name=cam_name,
                type=cam_type,
                path=cam_data.get("path", ""),
                settings=_load_camera_config(cam_data.get("settings") or {})
            )
            camera_objects[cam_name] = camera

    # Create motor objects
    motor_objects = {}
    for motor_name, motor_settings in config_motors.items():
        motor = Motor(
            name=motor_name,
            settings=_load_motor_config(motor_settings or {}),
        )
        motor_objects[motor_name] = motor
        logger.debug(f"Loaded motor {motor_name} with settings: {motor.settings}")

    # Create light objects
    light_objects = {}
    for light_name, light_settings in config_lights.items():
        light = Light(
            name=light_name,
            settings=_load_light_config(light_settings or {})
        )
        light_objects[light_name] = light
        logger.debug(f"Loaded light {light_name} with settings: {light.settings}")

    # Cloud settings
    persistent_settings = load_persistent_cloud_settings()
    if persistent_settings:
        set_cloud_settings(persistent_settings)
        set_active_source("persistent")
        logger.info(
            "Cloud service configured from persisted settings for host %s (user %s).",
            persistent_settings.host,
            mask_secret(persistent_settings.user),
        )
    else:
        cloud_settings = load_cloud_settings_from_env()
        if cloud_settings:
            set_cloud_settings(cloud_settings)
            set_active_source("environment")
            logger.info(
                "Cloud service configured from environment for host %s (user %s).",
                cloud_settings.host,
                mask_secret(cloud_settings.user),
            )
        else:
            set_cloud_settings(None)
            set_active_source(None)
            logger.warning(
                "Cloud service not configured. Set OPENSCANCLOUD_USER, OPENSCANCLOUD_PASSWORD and OPENSCANCLOUD_TOKEN to enable uploads."
            )

    # Initialize controllers
    availability = get_available_camera_types()
    for name, camera in camera_objects.items():
        try:
            if not availability.get(camera.type, False):
                logger.warning(
                    "Skipping controller init for %s (%s): dependency not available.",
                    name,
                    camera.type,
                )
                continue
            create_camera_controller(camera)
        except Exception as e:
            logger.error(f"Error initializing camera controller for {name}: {e}")

    for name, motor in motor_objects.items():
        try:
            create_motor_controller(motor)
        except Exception as e:
            logger.error(f"Error initializing motor controller for {name}: {e}")

    # Create endstop objects
    endstop_objects = {}
    for endstop_name, endstop_data in config_endstops.items():
        try:
            settings = _load_endstop_config((endstop_data or {}).get("settings") or {})
            endstop = Endstop(name=endstop_name, settings=settings)
            controller = get_motor_controller(settings.motor_name)
            if not controller:
                raise ValueError(f"Motor '{settings.motor_name}' not found for endstop '{endstop_name}'")
            endstop_controller = EndstopController(endstop, controller=controller)
            endstop_objects[endstop_name] = endstop
            _endstop_controllers[endstop_name] = endstop_controller
            logger.debug(f"Loaded endstop {endstop_name} with settings: {endstop.settings}")
            endstop_controller.start_listener()
        except Exception as e:
            logger.error(f"Error initializing endstop '{endstop_name}': {e}")


    for name, light in light_objects.items():
        try:
            create_light_controller(light)
        except Exception as e:
            logger.error(f"Error initializing light controller for {name}: {e}")

    # initialize project manager
    try:
        project_manager = get_project_manager(BASE_DIR / "projects")
    except Exception as e:
        logger.error(f"Error initializing project manager: {e}", exc_info=True)

    # turn on lights
    for _, controller in get_all_light_controllers().items():
        try:
            controller.turn_on()
        except Exception as e:
            controller_name = getattr(getattr(controller, "model", None), "name", "<unknown>")
            logger.error("Error turning on light '%s': %s", controller_name, e)

    model_value = config.get("model")
    shield_value = config.get("shield")
    model = None
    shield = None
    if model_value:
        try:
            model = ScannerModel(model_value)
        except Exception:
            logger.warning("Invalid scanner model '%s'; defaulting to None.", model_value)
    if shield_value:
        try:
            shield = ScannerShield(shield_value)
        except Exception:
            logger.warning("Invalid scanner shield '%s'; defaulting to None.", shield_value)

    _scanner_device = ScannerDevice(
        name=config.get("name", _scanner_device.name),
        model=model,
        shield=shield,
        cameras=camera_objects,
        motors=motor_objects,
        lights=light_objects,
        endstops=endstop_objects,
        initialized=True
    )
    logger.info("Hardware initialized.")
    logger.debug(f"Initialized ScannerDevice: {_scanner_device.model_dump(mode='json')}.")
    schedule_device_status_broadcast()


def get_available_configs():
    """Get a list of all available device configuration files

    Returns:
        list: List of dictionaries with information about each config file
    """
    configs: list[dict] = []

    settings_dir = resolve_settings_dir("device")
    if not settings_dir.exists():
        fallback_dir = resolve_settings_dir()
        if fallback_dir.exists():
            settings_dir = fallback_dir
        else:
            return configs

    for file in settings_dir.iterdir():
        if file.suffix == ".json":
            try:
                data = json.loads(file.read_text())
                configs.append({
                    "filename": file.name,
                    "path": str(file),
                    "name": data.get("name", "Unknown"),
                    "model": data.get("model", "Unknown"),
                    "shield": data.get("shield", "Unknown")
                })
            except Exception:
                configs.append({"filename": file.name, "path": str(file)})

    return configs


def reboot(with_saving = False):
    if with_saving:
        save_device_config()
    cleanup_and_exit()
    subprocess.run(["sudo", "reboot"], check=False)


def shutdown(with_saving = False):
    if with_saving:
        save_device_config()
    cleanup_and_exit()
    subprocess.run(["sudo", "shutdown", "now"], check=False)


def cleanup_and_exit():
    # Clean up cameras
    cam_controllers = get_all_camera_controllers()
    for name, controller in cam_controllers.items():
        try:
            controller.cleanup()
            logger.debug(f"Camera controller '{name}' closed successfully.")
        except Exception as e:
            logger.error(f"Error closing camera controller '{name}': {e}")

    # Clean up endstops
    for name, endstop_controller in list(_endstop_controllers.items()):
        try:
            endstop_controller.cleanup()
            logger.debug("Endstop controller '%s' closed successfully.", name)
        except Exception as e:
            logger.error("Error closing endstop controller '%s': %s", name, e)
        _endstop_controllers.pop(name, None)

    # Turn off lights
    for name, light_controller in get_all_light_controllers().items():
        try:
            light_controller.turn_off()
            logger.debug("Light controller '%s' turned off.", name)
        except Exception as e:
            logger.error("Error turning off light '%s': %s", name, e)

    cleanup_all_pins()
    logger.info("Exiting now...")


def check_arducam_overlay(camera_model: str) -> bool:
    """Check if the arducam overlay is set for the given camera model

    Args:
        camera_model (str): The camera model to check for

    Returns:
        bool: True if the correct overlay is set, False otherwise
    """
    config_path = "/boot/firmware/config.txt"
    arducam_overlays = {
        "arducam_64mp": "dtoverlay=arducam-64mp",
        "imx519": "dtoverlay=imx519"
    }

    overlay = arducam_overlays.get(camera_model)

    try:
        with open( config_path, "r") as f:
            config_lines = f.read().splitlines()

        if overlay in config_lines:
            logger.debug(f"Overlay for {camera_model} is set: {overlay}")
            return True
        else:
            logger.error(f"Overlay for {camera_model} missing or wrong, should be: {overlay}")
            return False
    except Exception as e:
        logger.error(f"Error checking for arducam overlay in {config_path}: {e}")
        return False
