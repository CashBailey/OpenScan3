from io import BytesIO
from tempfile import TemporaryFile
from typing import IO, Optional
import gphoto2 as gp

from .camera import CameraController
from openscan_firmware.models.camera import Camera, PhotoData


class Gphoto2Camera(CameraController):
    """GPhoto2-based camera controller for DSLR/mirrorless cameras.

    Note: This controller currently only supports JPEG capture. Other formats
    (RGB array, YUV array, DNG) are not implemented for GPhoto2 cameras.
    """

    _gp_camera: Optional[gp.Camera] = None

    def _get_gp_camera(self) -> gp.Camera:
        """Get or initialize the GPhoto2 camera instance."""
        if Gphoto2Camera._gp_camera is None:
            port_info_list = gp.PortInfoList()
            port_info_list.load()
            abilities_list = gp.CameraAbilitiesList()
            abilities_list.load()
            camera_list = abilities_list.detect(port_info_list)
            if not camera_list:
                raise RuntimeError("No GPhoto2 cameras detected")
            Gphoto2Camera._gp_camera = gp.Camera()
            idx = port_info_list.lookup_path(self.camera.path)
            Gphoto2Camera._gp_camera.set_port_info(port_info_list[idx])
            idx = abilities_list.lookup_model(camera_list[0][0])
            Gphoto2Camera._gp_camera.set_abilities(abilities_list[idx])
        return Gphoto2Camera._gp_camera

    def preview(self) -> IO[bytes]:
        """Capture a preview image from the GPhoto2 camera."""
        gp_camera = self._get_gp_camera()
        camera_file = gp.gp_camera_capture_preview(gp_camera)[1]
        file = TemporaryFile()
        file.write(camera_file.get_data_and_size())
        file.seek(0)
        return file

    def capture_jpeg(self) -> PhotoData:
        """Capture a JPEG image from the GPhoto2 camera."""
        gp_camera = self._get_gp_camera()
        file_path = gp_camera.capture(gp.GP_CAPTURE_IMAGE)
        camera_file = gp_camera.file_get(
            file_path.folder, file_path.name, gp.GP_FILE_TYPE_NORMAL
        )
        data = BytesIO(camera_file.get_data_and_size())
        return PhotoData(data=data)

    def capture_rgb_array(self) -> PhotoData:
        """Not supported for GPhoto2 cameras."""
        raise NotImplementedError(
            "RGB array capture is not supported for GPhoto2 cameras. "
            "Use capture_jpeg() instead."
        )

    def capture_yuv_array(self) -> PhotoData:
        """Not supported for GPhoto2 cameras."""
        raise NotImplementedError(
            "YUV array capture is not supported for GPhoto2 cameras. "
            "Use capture_jpeg() instead."
        )

    def capture_dng(self) -> PhotoData:
        """Not supported for GPhoto2 cameras."""
        raise NotImplementedError(
            "DNG capture is not supported for GPhoto2 cameras. "
            "Use capture_jpeg() instead."
        )

    # Legacy static methods for backward compatibility
    @staticmethod
    def photo(camera: Camera) -> IO[bytes]:
        """Legacy method - use capture_jpeg() instead."""
        # Create a temporary instance to use the new method
        from .camera import get_camera_controller
        controller = get_camera_controller(camera.name)
        result = controller.capture_jpeg()
        result.data.seek(0)
        return result.data
