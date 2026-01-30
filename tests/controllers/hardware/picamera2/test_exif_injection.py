"""
Integration tests for EXIF injection in Picamera2 controller.

Tests that camera intrinsics EXIF is properly injected into captured JPEGs.
These tests stub optional hardware modules (picamera2/libcamera) when absent.
"""

import sys
import types
from unittest.mock import MagicMock

import pytest
import piexif


def _install_stub_module(name: str, attrs: dict) -> None:
    """Install a lightweight module stub to satisfy imports in tests."""
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module


def _ensure_libcamera_stub() -> None:
    """Stub libcamera when it is not available in the test environment."""
    try:
        import libcamera  # noqa: F401
    except Exception:
        class _ColorSpace:
            Sycc = object()
            Jpeg = None

        class _Transform:
            def __init__(self, *args, **kwargs) -> None:
                pass

        class _Controls:
            class AfMeteringEnum:
                Windows = object()

            class AfModeEnum:
                Continuous = object()
                Auto = object()
                Manual = object()

        _install_stub_module(
            "libcamera",
            {
                "ColorSpace": _ColorSpace,
                "controls": _Controls,
                "Transform": _Transform,
            },
        )


def _ensure_picamera2_stub() -> None:
    """Stub picamera2 when it is not available in the test environment."""
    try:
        import picamera2  # noqa: F401
    except Exception:
        class _StubPicamera2:
            def __init__(self, *args, **kwargs) -> None:
                self.options = {}
                self.camera_properties = {"PixelArraySize": (0, 0), "Model": "stub"}

            def create_preview_configuration(self, *args, **kwargs):
                return {}

            def create_still_configuration(self, *args, **kwargs):
                return {}

            def configure(self, *args, **kwargs) -> None:
                return None

            def start(self) -> None:
                return None

            def set_controls(self, *args, **kwargs) -> None:
                return None

            def autofocus_cycle(self) -> None:
                return None

            def switch_mode_and_capture_file(self, *args, **kwargs) -> dict:
                return {}

            def capture_metadata(self) -> dict:
                return {"LensPosition": 0.0}

            def capture_array(self, *args, **kwargs):
                return []

            def stop(self) -> None:
                return None

            def close(self) -> None:
                return None

        _install_stub_module("picamera2", {"Picamera2": _StubPicamera2})


def _ensure_cv2_stub() -> None:
    """Stub cv2 when it is not available in the test environment."""
    try:
        import cv2  # noqa: F401
    except Exception:
        def _rotate(frame, _mode):
            return frame

        def _cvt_color(frame, _mode):
            return frame

        def _resize(frame, _size):
            return frame

        def _imencode(_ext, frame, _params=None):
            return True, frame

        def _lut(image, _table):
            return image

        _install_stub_module(
            "cv2",
            {
                "ROTATE_180": 0,
                "ROTATE_90_CLOCKWISE": 1,
                "ROTATE_90_COUNTERCLOCKWISE": 2,
                "COLOR_YUV420p2RGB": 0,
                "IMWRITE_JPEG_QUALITY": 1,
                "rotate": _rotate,
                "cvtColor": _cvt_color,
                "resize": _resize,
                "imencode": _imencode,
                "LUT": _lut,
            },
        )


_ensure_libcamera_stub()
_ensure_picamera2_stub()
_ensure_cv2_stub()

from openscan_firmware.controllers.hardware.cameras.picamera2 import Picamera2Controller
from openscan_firmware.config.camera import CameraSettings
from openscan_firmware.controllers.settings import Settings
from openscan_firmware.models.camera import Camera, CameraType


def _build_controller(
    camera_name: str = "imx519",
    photo_size: tuple[int, int] = (4656, 3496),
    orientation_flag: int = 1,
):
    settings_model = CameraSettings(
        orientation_flag=orientation_flag,
        jpeg_quality=95,
        AF=False,
    )
    camera = Camera(
        type=CameraType.PICAMERA2,
        name=camera_name,
        path="/dev/null",
        settings=settings_model,
    )

    controller = Picamera2Controller.__new__(Picamera2Controller)
    controller.camera = camera
    controller.settings = Settings(settings_model)
    controller.photo_config = {"main": {"size": photo_size}}
    controller._picam = MagicMock()
    controller._picam.options = {}
    controller._picam.switch_mode_and_capture_file.return_value = {"dummy": True}
    controller._busy = False
    controller._is_closing = False
    controller._set_busy = lambda *_args, **_kwargs: None
    controller._configure_focus = lambda *_args, **_kwargs: None
    controller._configure_cropping_for_scalercrop = lambda *_args, **_kwargs: None
    return controller


def _get_exif_from_capture(mock_picam: MagicMock) -> dict:
    assert mock_picam.switch_mode_and_capture_file.called
    _, kwargs = mock_picam.switch_mode_and_capture_file.call_args
    assert "exif_data" in kwargs
    return kwargs["exif_data"]


class TestEXIFInjectionInCapture:
    """Test EXIF injection during JPEG capture."""

    def test_capture_jpeg_injects_intrinsics_exif(self):
        """Test that intrinsics EXIF is injected for known sensors."""
        controller = _build_controller(camera_name="imx519", photo_size=(4656, 3496))
        controller.capture_jpeg()

        exif_data = _get_exif_from_capture(controller._picam)
        assert "Exif" in exif_data

        exif = exif_data["Exif"]
        assert exif[piexif.ExifIFD.FocalLength] == (428, 100)
        assert exif[piexif.ExifIFD.FocalLengthIn35mmFilm] == 33
        assert exif[piexif.ExifIFD.PixelXDimension] == 4656
        assert exif[piexif.ExifIFD.PixelYDimension] == 3496

    def test_capture_jpeg_preserves_basic_exif(self):
        """Test that basic EXIF (orientation, model, software) is preserved."""
        controller = _build_controller(
            camera_name="imx519",
            photo_size=(800, 600),
            orientation_flag=6,
        )
        controller.capture_jpeg()

        exif_data = _get_exif_from_capture(controller._picam)
        base_exif = exif_data["0th"]
        assert base_exif[piexif.ImageIFD.Orientation] == 6
        assert base_exif[piexif.ImageIFD.Model] == "imx519"
        assert base_exif[piexif.ImageIFD.Software] == "OpenScan3 (Picamera2)"

    def test_capture_jpeg_unknown_sensor_does_not_add_intrinsics(self):
        """Test that unknown sensors do not add intrinsics EXIF."""
        controller = _build_controller(camera_name="unknown_camera_xyz")
        controller.capture_jpeg()

        exif_data = _get_exif_from_capture(controller._picam)
        assert "Exif" not in exif_data

    def test_capture_jpeg_uses_photo_config_dimensions(self):
        """Test that EXIF dimensions follow the photo config size."""
        controller = _build_controller(camera_name="imx519", photo_size=(2328, 1748))
        controller.capture_jpeg()

        exif_data = _get_exif_from_capture(controller._picam)
        exif = exif_data["Exif"]
        assert exif[piexif.ExifIFD.PixelXDimension] == 2328
        assert exif[piexif.ExifIFD.PixelYDimension] == 1748

    def test_capture_jpeg_exif_tag_types(self):
        """Test that EXIF tag types are correct in capture path."""
        controller = _build_controller(camera_name="imx519", photo_size=(4656, 3496))
        controller.capture_jpeg()

        exif_data = _get_exif_from_capture(controller._picam)
        exif = exif_data["Exif"]

        assert isinstance(exif[piexif.ExifIFD.FocalLength], tuple)
        assert len(exif[piexif.ExifIFD.FocalLength]) == 2
        assert isinstance(exif[piexif.ExifIFD.FocalLength][0], int)
        assert isinstance(exif[piexif.ExifIFD.FocalLength][1], int)
        assert isinstance(exif[piexif.ExifIFD.FocalLengthIn35mmFilm], int)
        assert isinstance(exif[piexif.ExifIFD.PixelXDimension], int)
        assert isinstance(exif[piexif.ExifIFD.PixelYDimension], int)

    def test_capture_jpeg_merges_optional_exif_data(self):
        """Test that optional EXIF data is merged after intrinsics injection."""
        controller = _build_controller(camera_name="imx519", photo_size=(4656, 3496))
        optional_exif_data = {
            "GPS": {
                piexif.GPSIFD.GPSVersionID: (2, 3, 0, 0),
            }
        }

        controller.capture_jpeg(optional_exif_data=optional_exif_data)

        exif_data = _get_exif_from_capture(controller._picam)
        assert "GPS" in exif_data
        assert exif_data["GPS"][piexif.GPSIFD.GPSVersionID] == (2, 3, 0, 0)
        assert "Exif" in exif_data


class TestEXIFDataStructure:
    """Test the structure of injected EXIF data."""

    def test_exif_includes_focal_length_tag(self):
        """Test that FocalLength tag is present."""
        from openscan_firmware.utils.photos.exif import build_camera_intrinsics_exif

        exif = build_camera_intrinsics_exif("imx519", 4656, 3496)

        assert piexif.ExifIFD.FocalLength in exif["Exif"]

    def test_exif_includes_focal_length_35mm_tag(self):
        """Test that FocalLengthIn35mmFilm tag is present."""
        from openscan_firmware.utils.photos.exif import build_camera_intrinsics_exif

        exif = build_camera_intrinsics_exif("imx519", 4656, 3496)

        assert piexif.ExifIFD.FocalLengthIn35mmFilm in exif["Exif"]

    def test_exif_includes_pixel_dimension_tags(self):
        """Test that pixel dimension tags are present."""
        from openscan_firmware.utils.photos.exif import build_camera_intrinsics_exif

        exif = build_camera_intrinsics_exif("imx519", 4656, 3496)

        assert piexif.ExifIFD.PixelXDimension in exif["Exif"]
        assert piexif.ExifIFD.PixelYDimension in exif["Exif"]


class TestEXIFValues:
    """Test correctness of injected EXIF values."""

    def test_focal_length_matches_sensor_db(self):
        """Test that focal length in EXIF matches sensor database."""
        from openscan_firmware.utils.photos.exif import build_camera_intrinsics_exif
        from openscan_firmware.config.sensors import get_sensor_by_name

        sensor = get_sensor_by_name("imx519")
        exif = build_camera_intrinsics_exif("imx519", 4656, 3496)

        focal_ratio = exif["Exif"][piexif.ExifIFD.FocalLength]
        focal_from_ratio = focal_ratio[0] / focal_ratio[1]

        assert focal_from_ratio == pytest.approx(
            sensor.default_focal_length_mm, rel=0.01
        )

    def test_dimensions_match_output_size(self):
        """Test that EXIF dimensions match actual output size."""
        from openscan_firmware.utils.photos.exif import build_camera_intrinsics_exif

        output_width, output_height = 4656, 3496
        exif = build_camera_intrinsics_exif("imx519", output_width, output_height)

        assert exif["Exif"][piexif.ExifIFD.PixelXDimension] == output_width
        assert exif["Exif"][piexif.ExifIFD.PixelYDimension] == output_height

    def test_dimensions_respects_cropped_resolution(self):
        """Test that EXIF dimensions respect cropped/scaled output."""
        from openscan_firmware.utils.photos.exif import build_camera_intrinsics_exif

        # Test with cropped resolution
        output_width, output_height = 2328, 1748
        exif = build_camera_intrinsics_exif("imx519", output_width, output_height)

        # EXIF should report the actual output dimensions, not sensor native
        assert exif["Exif"][piexif.ExifIFD.PixelXDimension] == output_width
        assert exif["Exif"][piexif.ExifIFD.PixelYDimension] == output_height

        # But focal length should remain the same (it's absolute)
        focal_ratio = exif["Exif"][piexif.ExifIFD.FocalLength]
        assert focal_ratio == (428, 100)  # 4.28mm

    def test_35mm_equivalent_reasonable(self):
        """Test that 35mm equivalent values are reasonable."""
        from openscan_firmware.utils.photos.exif import build_camera_intrinsics_exif

        exif = build_camera_intrinsics_exif("imx519", 4656, 3496)
        focal_35mm = exif["Exif"][piexif.ExifIFD.FocalLengthIn35mmFilm]

        # For a small sensor camera, 35mm equivalent should be significantly larger
        # IMX519: 4.28mm actual -> ~33mm equivalent
        assert focal_35mm > 25  # Should be reasonable focal length
        assert focal_35mm < 100  # But not unreasonably large


class TestEXIFErrorHandling:
    """Test error handling in EXIF injection."""

    def test_unknown_sensor_returns_empty_dict(self):
        """Test that unknown sensor gracefully returns empty dict."""
        from openscan_firmware.utils.photos.exif import build_camera_intrinsics_exif

        exif = build_camera_intrinsics_exif("nonexistent_sensor", 4656, 3496)

        assert isinstance(exif, dict)
        assert exif == {}

    def test_none_camera_name_returns_empty_dict(self):
        """Test that None camera name returns empty dict."""
        from openscan_firmware.utils.photos.exif import build_camera_intrinsics_exif

        exif = build_camera_intrinsics_exif(None, 4656, 3496)

        assert isinstance(exif, dict)
        assert exif == {}

    def test_invalid_dimensions_dont_crash(self):
        """Test that invalid dimensions are handled gracefully."""
        from openscan_firmware.utils.photos.exif import build_camera_intrinsics_exif

        # Zero dimensions
        exif = build_camera_intrinsics_exif("imx519", 0, 0)
        # Should still return EXIF (even with 0 dimensions)
        assert isinstance(exif, dict)

        # Negative dimensions
        exif = build_camera_intrinsics_exif("imx519", -100, -100)
        assert isinstance(exif, dict)

    def test_sensor_lookup_exception_doesnt_crash(self):
        """Test that exceptions in sensor lookup are caught."""
        from openscan_firmware.utils.photos.exif import get_sensor_for_camera

        # This should not raise an exception
        sensor = get_sensor_for_camera("")
        assert sensor is None
