from fastapi import FastAPI
from fastapi.testclient import TestClient

from openscan_firmware.config.camera import CameraSettings
from openscan_firmware.config.endstop import EndstopConfig
from openscan_firmware.config.light import LightConfig
from openscan_firmware.config.motor import MotorConfig
from openscan_firmware.models.camera import Camera, CameraType
from openscan_firmware.models.light import Light
from openscan_firmware.models.motor import Motor, Endstop
from openscan_firmware.models.scanner import ScannerDevice, ScannerModel, ScannerShield


def _build_scanner_payload() -> dict:
    motor_config = MotorConfig(
        direction_pin=1,
        enable_pin=2,
        step_pin=3,
        steps_per_rotation=200,
    )
    endstop_config = EndstopConfig(pin=4, angular_position=0.0, motor_name="motor")

    scanner = ScannerDevice(
        name="scanner",
        model=ScannerModel.CLASSIC,
        shield=ScannerShield.GREENSHIELD,
        cameras={
            "cam": Camera(
                type=CameraType.EXTERNAL,
                name="cam",
                path="/dev/null",
                settings=CameraSettings(),
            )
        },
        motors={"motor": Motor(name="motor", settings=motor_config)},
        lights={"light": Light(name="light", settings=LightConfig(pin=5))},
        endstops={"endstop": Endstop(name="endstop", settings=endstop_config)},
        initialized=True,
    )
    return scanner.model_dump(mode="json")


def test_add_config_rejects_invalid_filename(latest_router_loader):
    app = FastAPI()
    router_module = latest_router_loader("device")
    app.include_router(router_module.router)

    payload = {
        "config_data": _build_scanner_payload(),
        "filename": {"config_file": "../bad"},
    }

    with TestClient(app) as client:
        response = client.post("/device/configurations/", json=payload)

    assert response.status_code == 400


def test_set_config_rejects_unlisted_path(latest_router_loader, monkeypatch, tmp_path):
    app = FastAPI()
    router_module = latest_router_loader("device")
    app.include_router(router_module.router)

    safe_path = tmp_path / "safe.json"
    safe_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        router_module.device,
        "get_available_configs",
        lambda: [{"filename": "safe.json", "path": str(safe_path)}],
    )
    monkeypatch.setattr(router_module.device, "set_device_config", lambda _: True)
    monkeypatch.setattr(
        router_module.device,
        "get_device_info",
        lambda: {
            "name": "scanner",
            "model": "classic",
            "shield": "greenshield",
            "cameras": {},
            "motors": {},
            "lights": {},
            "initialized": True,
        },
    )

    with TestClient(app) as client:
        response = client.put("/device/configurations/current", json={"config_file": "../evil.json"})

    assert response.status_code == 404
