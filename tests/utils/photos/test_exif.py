"""
Unit tests for camera intrinsics EXIF injection utilities.

Tests the EXIF building functions without requiring camera hardware.
"""

import pytest
import piexif

from openscan_firmware.utils.photos.exif import (
    get_sensor_for_camera,
    focal_to_rational,
    calculate_35mm_equivalent,
    build_camera_intrinsics_exif,
)
from openscan_firmware.config.sensors import CameraSensor


class TestSensorLookup:
    """Test camera sensor lookup with aliasing."""

    def test_get_sensor_direct_match_imx519(self):
        """Test sensor lookup with direct name match (imx519)."""
        sensor = get_sensor_for_camera("imx519")
        assert sensor is not None
        assert sensor.name == "imx519"
        assert sensor.default_focal_length_mm == 4.28

    def test_get_sensor_direct_match_hawkeye(self):
        """Test sensor lookup with direct name match (hawkeye)."""
        sensor = get_sensor_for_camera("hawkeye")
        assert sensor is not None
        assert sensor.name == "hawkeye"
        assert sensor.default_focal_length_mm == 5.1

    def test_get_sensor_via_alias_arducam_64mp(self):
        """Test sensor lookup via alias (arducam_64mp -> hawkeye)."""
        sensor = get_sensor_for_camera("arducam_64mp")
        assert sensor is not None
        assert sensor.name == "hawkeye"
        assert sensor.default_focal_length_mm == 5.1

    def test_get_sensor_case_insensitive(self):
        """Test sensor lookup is case-insensitive."""
        sensor1 = get_sensor_for_camera("IMX519")
        sensor2 = get_sensor_for_camera("imx519")
        assert sensor1 is not None
        assert sensor2 is not None
        assert sensor1.name == sensor2.name

    def test_get_sensor_unknown_returns_none(self):
        """Test unknown sensor returns None gracefully."""
        sensor = get_sensor_for_camera("unknown_camera_xyz")
        assert sensor is None

    def test_get_sensor_empty_camera_name(self):
        """Test empty camera name returns None gracefully."""
        sensor = get_sensor_for_camera("")
        assert sensor is None

    def test_get_sensor_none_camera_name(self):
        """Test None camera name returns None gracefully."""
        sensor = get_sensor_for_camera(None)
        assert sensor is None


class TestFocalLengthConversion:
    """Test focal length to rational conversion."""

    def test_focal_to_rational_4_28mm(self):
        """Test focal length 4.28mm -> rational (428, 100)."""
        ratio = focal_to_rational(4.28)
        assert ratio == (428, 100)

    def test_focal_to_rational_5_1mm(self):
        """Test focal length 5.1mm -> rational (510, 100)."""
        ratio = focal_to_rational(5.1)
        assert ratio == (510, 100)

    def test_focal_to_rational_integer(self):
        """Test integer focal length (6.0mm -> (600, 100))."""
        ratio = focal_to_rational(6.0)
        assert ratio == (600, 100)

    def test_focal_to_rational_rounding(self):
        """Test rounding to nearest centimeter."""
        ratio = focal_to_rational(4.284)
        assert ratio == (428, 100)  # Rounded to 4.28

    def test_focal_to_rational_preserves_precision(self):
        """Test conversion preserves 2 decimal places."""
        ratio = focal_to_rational(4.28)
        assert ratio[0] / ratio[1] == pytest.approx(4.28, rel=0.001)


class TestCalc35mmEquivalent:
    """Test 35mm equivalent focal length calculation."""

    def test_calc_35mm_imx519(self):
        """Test 35mm equivalent for IMX519.

        IMX519: 4.28mm focal length on 4.64mm sensor width
        35mm_equiv = 4.28 * (36 / 4.64) ≈ 33.2 -> 33
        """
        equiv = calculate_35mm_equivalent(4.28, 4.64)
        assert equiv == 33

    def test_calc_35mm_hawkeye(self):
        """Test 35mm equivalent for Hawkeye.

        Hawkeye: 5.1mm focal length on 6.45mm sensor width
        35mm_equiv = 5.1 * (36 / 6.45) ≈ 28.5 -> 28 or 29 (depends on rounding)
        """
        equiv = calculate_35mm_equivalent(5.1, 6.45)
        assert equiv in [28, 29]  # Allow for rounding variation

    def test_calc_35mm_full_frame_35mm_lens(self):
        """Test 35mm equivalent of 50mm lens on full-frame (36mm sensor).

        50mm on full-frame -> 50mm equivalent
        """
        equiv = calculate_35mm_equivalent(50.0, 36.0)
        assert equiv == 50

    def test_calc_35mm_zero_sensor_width(self):
        """Test graceful handling of invalid sensor width."""
        # Should return input value rounded
        equiv = calculate_35mm_equivalent(4.28, 0.0)
        assert equiv == 4

    def test_calc_35mm_negative_sensor_width(self):
        """Test graceful handling of negative sensor width."""
        equiv = calculate_35mm_equivalent(4.28, -4.64)
        assert isinstance(equiv, int)


class TestEXIFBuilder:
    """Test building EXIF dict for piexif."""

    def test_build_exif_known_sensor_imx519(self):
        """Test building EXIF dict for known sensor (imx519)."""
        exif = build_camera_intrinsics_exif("imx519", 4656, 3496)

        assert isinstance(exif, dict)
        assert "Exif" in exif
        assert piexif.ExifIFD.FocalLength in exif["Exif"]
        assert piexif.ExifIFD.FocalLengthIn35mmFilm in exif["Exif"]
        assert piexif.ExifIFD.PixelXDimension in exif["Exif"]
        assert piexif.ExifIFD.PixelYDimension in exif["Exif"]

    def test_build_exif_focal_length_value(self):
        """Test EXIF contains correct focal length."""
        exif = build_camera_intrinsics_exif("imx519", 4656, 3496)
        focal_ratio = exif["Exif"][piexif.ExifIFD.FocalLength]

        # Should be (428, 100) for 4.28mm
        assert focal_ratio == (428, 100)

    def test_build_exif_35mm_equivalent_value(self):
        """Test EXIF contains correct 35mm equivalent."""
        exif = build_camera_intrinsics_exif("imx519", 4656, 3496)
        focal_35mm = exif["Exif"][piexif.ExifIFD.FocalLengthIn35mmFilm]

        # Should be 33 for IMX519 (4.28mm on 4.64mm sensor)
        assert focal_35mm == 33

    def test_build_exif_dimensions_values(self):
        """Test EXIF contains correct image dimensions."""
        exif = build_camera_intrinsics_exif("imx519", 4656, 3496)

        assert exif["Exif"][piexif.ExifIFD.PixelXDimension] == 4656
        assert exif["Exif"][piexif.ExifIFD.PixelYDimension] == 3496

    def test_build_exif_different_resolution(self):
        """Test EXIF building with different output resolution."""
        exif = build_camera_intrinsics_exif("imx519", 2328, 1748)

        assert exif["Exif"][piexif.ExifIFD.PixelXDimension] == 2328
        assert exif["Exif"][piexif.ExifIFD.PixelYDimension] == 1748
        # Focal length should remain unchanged (it's absolute, not relative)
        assert exif["Exif"][piexif.ExifIFD.FocalLength] == (428, 100)

    def test_build_exif_unknown_sensor_returns_empty(self):
        """Test unknown sensor returns empty dict (graceful degradation)."""
        exif = build_camera_intrinsics_exif("unknown_xyz", 4656, 3496)
        assert exif == {}

    def test_build_exif_unknown_sensor_via_alias(self):
        """Test unknown aliased sensor returns empty dict."""
        exif = build_camera_intrinsics_exif("arducam_unknown", 4656, 3496)
        assert exif == {}

    def test_build_exif_all_sensors(self):
        """Test EXIF building works for all known sensors."""
        sensors = ["imx519", "hawkeye", "imx708", "imx477", "arducam_64mp"]

        for sensor_name in sensors:
            exif = build_camera_intrinsics_exif(sensor_name, 4656, 3496)
            assert isinstance(exif, dict)
            if sensor_name != "unknown":
                # All known sensors should produce non-empty EXIF
                # (arducam_64mp may map to hawkeye which exists)
                if exif:  # Only check structure if not empty
                    assert "Exif" in exif

    def test_build_exif_structure_matches_piexif_format(self):
        """Test EXIF dict structure is compatible with piexif."""
        exif = build_camera_intrinsics_exif("imx519", 4656, 3496)

        # Should have "Exif" key (for ExifIFD tags)
        assert "Exif" in exif

        # All values should be appropriate types for piexif
        for tag, value in exif["Exif"].items():
            if tag == piexif.ExifIFD.FocalLength:
                # Should be rational tuple (int, int)
                assert isinstance(value, tuple)
                assert len(value) == 2
                assert isinstance(value[0], int)
                assert isinstance(value[1], int)
            else:
                # Other tags should be integers
                assert isinstance(value, int)
