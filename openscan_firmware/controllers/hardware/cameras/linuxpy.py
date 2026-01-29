from io import BytesIO
from tempfile import TemporaryFile
from typing import IO, Optional, List, Any
from linuxpy.video.device import Device, VideoCapture

from .camera import CameraController
from openscan_firmware.models.camera import Camera, CameraMode, PhotoData


class LINUXPYCamera(CameraController):
    """Linux V4L2-based camera controller using linuxpy.

    Note: This controller currently only supports JPEG capture. Other formats
    (RGB array, YUV array, DNG) are not implemented for V4L2 cameras.
    """

    _device: Optional[Device] = None
    _current_mode: Optional[CameraMode] = None

    def _get_device(self, mode: CameraMode) -> Device:
        """Get or initialize the V4L2 device for the specified mode."""
        if LINUXPYCamera._current_mode != mode:
            LINUXPYCamera._current_mode = mode
            if LINUXPYCamera._device is not None:
                LINUXPYCamera._device.close()
            LINUXPYCamera._device = Device(self.camera.path)
            if mode == CameraMode.PHOTO:
                with LINUXPYCamera._device as dev:
                    capture = VideoCapture(dev)
                    capture.set_format(1920, 1080, "MJPG")
            elif mode == CameraMode.PREVIEW:
                LINUXPYCamera._device.video_capture.set_format(320, 240, "MJPG")
        return LINUXPYCamera._device

    def preview(self) -> IO[bytes]:
        """Capture a preview frame from the V4L2 camera.

        Note: This method may not work correctly on all devices.
        """
        device = self._get_device(CameraMode.PREVIEW)
        device_stream = iter(device)
        next(device_stream)  # first frame can be garbage
        file = TemporaryFile()
        file.write(next(device_stream))
        file.seek(0)
        return file

    def capture_jpeg(self) -> PhotoData:
        """Capture a JPEG image from the V4L2 camera."""
        device = self._get_device(CameraMode.PHOTO)
        with device as dev:
            capture = VideoCapture(dev)
            capture.set_format(1920, 1080, "MJPG")
            with capture:
                for frame in capture:
                    data = BytesIO(bytes(frame))
                    return PhotoData(data=data)
        raise RuntimeError("Failed to capture frame from V4L2 camera")

    def capture_rgb_array(self) -> PhotoData:
        """Not supported for V4L2 cameras."""
        raise NotImplementedError(
            "RGB array capture is not supported for V4L2/linuxpy cameras. "
            "Use capture_jpeg() instead."
        )

    def capture_yuv_array(self) -> PhotoData:
        """Not supported for V4L2 cameras."""
        raise NotImplementedError(
            "YUV array capture is not supported for V4L2/linuxpy cameras. "
            "Use capture_jpeg() instead."
        )

    def capture_dng(self) -> PhotoData:
        """Not supported for V4L2 cameras."""
        raise NotImplementedError(
            "DNG capture is not supported for V4L2/linuxpy cameras. "
            "Use capture_jpeg() instead."
        )

    # Legacy static methods for backward compatibility
    @staticmethod
    def photo(camera: Camera) -> IO[bytes]:
        """Legacy method - use capture_jpeg() instead."""
        from .camera import get_camera_controller
        controller = get_camera_controller(camera.name)
        result = controller.capture_jpeg()
        result.data.seek(0)
        return result.data
