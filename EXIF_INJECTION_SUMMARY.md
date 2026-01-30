# EXIF Injection Summary (Phase 2 Verification)

Verified on 2026-01-30. This document records observed results and does not claim production readiness.

## What Changed

- Added EXIF intrinsics builder utilities in `openscan_firmware/utils/photos/exif.py`.
- Added sensor database + alias mapping in `openscan_firmware/config/sensors.py`.
- Injected intrinsics EXIF during Picamera2 JPEG capture in `openscan_firmware/controllers/hardware/cameras/picamera2.py`.
- Added unit tests in `tests/utils/photos/test_exif.py` and integration tests in `tests/controllers/hardware/picamera2/test_exif_injection.py`.

## Injected EXIF Tags

- `FocalLength`
- `FocalLengthIn35mmFilm`
- `PixelXDimension`
- `PixelYDimension`

## Failure Behavior

- Intrinsics EXIF injection runs inside a try/except.
- On failure, a warning is logged and JPEG capture continues without intrinsics EXIF.

## Runtime Dependency Note

- `piexif` is listed in `pyproject.toml` dependencies (runtime).

## How to Run Tests

```bash
cd /home/c/VScode/OpenScan/OpenScan3
source .venv/bin/activate
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/utils/photos/test_exif.py -v
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/controllers/hardware/picamera2/test_exif_injection.py -v
```

Observed warning when running with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`:

- `PytestConfigWarning: Unknown config option: asyncio_default_fixture_loop_scope`
- This warning appears because `pytest-asyncio` is not auto-loaded, so its config option is unknown.

## Verified Results (2026-01-30)

- `tests/utils/photos/test_exif.py`: 26 passed, 1 warning
- `tests/controllers/hardware/picamera2/test_exif_injection.py`: 17 passed, 1 warning
