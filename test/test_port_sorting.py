import pytest
from unittest.mock import patch
import esptool

# Espressif USB Vendor ID, used by all official Espressif USB bridges
# and the ESP32-S2/-S3/-C3/... internal USB peripheral.
ESPRESSIF_VID = 0x303A


class MockPort:
    """Mock serial port object that mimics pyserial's ListPortInfo"""

    def __init__(self, device, vid=None, pid=None, name=None, serial_number=None):
        self.device = device
        self.vid = vid
        self.pid = pid
        self.name = name
        self.serial_number = serial_number


# ``esptool.get_port_list`` delegates to ``esp_pylib.serial_ports.get_port_list``,
# which calls the local ``_comports`` shim imported from ``serial.tools.list_ports``.
# Patching it here lets the tests inject a fake port list without needing a real
# pyserial backend.
_COMPORTS_PATCH = "esp_pylib.serial_ports._comports"


@pytest.mark.host_test
class TestPortSorting:
    """Test the port sorting algorithm in get_port_list function.

    esp_pylib returns ports "best candidates first": Espressif VID, then
    known platform USB device patterns, then anything else.
    """

    def test_linux_port_sorting(self):
        """Test port sorting on Linux platform"""
        mock_ports = [
            MockPort("/dev/ttyS0", vid=0x1234),
            MockPort("/dev/ttyS1", vid=0x1234),
            MockPort("/dev/ttyUSB0", vid=0x1234),
            MockPort("/dev/ttyUSB1", vid=0x1234),
            MockPort("/dev/ttyACM1", vid=ESPRESSIF_VID),
            MockPort("/dev/ttyACM0", vid=0x1234),
        ]

        with (
            patch("sys.platform", "linux"),
            patch(_COMPORTS_PATCH, return_value=mock_ports),
        ):
            result = esptool.get_port_list()

            # Expected sorting order: Espressif VID first (highest priority),
            # then ttyUSB*/ttyACM* devices, then everything else. Within each
            # bucket the order is the platform pattern's preference followed by
            # the device path (alphabetically).
            expected = [
                "/dev/ttyACM1",  # Espressif VID
                "/dev/ttyUSB0",  # ttyUSB before ttyACM (pattern order)
                "/dev/ttyUSB1",
                "/dev/ttyACM0",
                "/dev/ttyS0",  # other
                "/dev/ttyS1",
            ]

            assert result == expected

    def test_macos_port_sorting(self):
        """Test port sorting on macOS platform"""
        mock_ports = [
            MockPort("/dev/cu.wlan-debug", vid=0x1234),  # Excluded by macOS filter
            MockPort(
                "/dev/cu.Bluetooth-Incoming-Port", vid=0x1234
            ),  # Excluded by macOS filter
            MockPort("/dev/cu.debug-console", vid=0x1234),  # Excluded by macOS filter
            MockPort("/dev/cu.usbserial2", vid=0x1234),
            MockPort("/dev/cu.usbmodem1", vid=0x1234),
            MockPort("/dev/cu.usbmodem2", vid=ESPRESSIF_VID),
            MockPort("/dev/cu.usbserial1", vid=0x1234),
        ]

        with (
            patch("sys.platform", "darwin"),
            patch(_COMPORTS_PATCH, return_value=mock_ports),
        ):
            result = esptool.get_port_list()

            # Expected: Espressif VID first, then usbserial*/usbmodem* devices
            # (usbserial preferred over usbmodem in pattern order).
            # wlan-debug, Bluetooth-Incoming-Port, debug-console are excluded.
            expected = [
                "/dev/cu.usbmodem2",  # Espressif VID
                "/dev/cu.usbserial1",  # usbserial first
                "/dev/cu.usbserial2",
                "/dev/cu.usbmodem1",
            ]

            assert result == expected

    def test_windows_port_sorting(self):
        """Test port sorting on Windows platform"""
        mock_ports = [
            MockPort("COM3", vid=0x1234),
            MockPort("COM1", vid=0x1234),
            MockPort("COM10", vid=0x1234),
            MockPort("COM5", vid=ESPRESSIF_VID),
            MockPort("COM2", vid=0x1234),
        ]

        with (
            patch("sys.platform", "win32"),
            patch(_COMPORTS_PATCH, return_value=mock_ports),
        ):
            result = esptool.get_port_list()

            # Expected: Espressif VID first, then remaining COM ports sorted by
            # device path (string sort: "COM1", "COM10", "COM2", "COM3").
            expected = [
                "COM5",  # Espressif VID
                "COM1",
                "COM10",
                "COM2",
                "COM3",
            ]

            assert result == expected

    def test_port_filtering_parameters(self):
        """Test port filtering with various parameters while maintaining sorting.

        Note: the ``names`` filter is a case-insensitive substring match against
        the device path (``port.device``), not against pyserial's ``port.name``
        / ``port.description``. ``serials`` is a substring match against the
        device's USB serial number.
        """
        mock_ports = [
            MockPort(
                "/dev/ttyUSB0",
                vid=0x1234,
                pid=0x5678,
                name="USB Serial",
                serial_number="ABC123",
            ),
            MockPort(
                "/dev/ttyUSB1",
                vid=ESPRESSIF_VID,
                pid=0x1001,
                name="ESP32",
                serial_number="ESP001",
            ),
            MockPort(
                "/dev/ttyUSB2",
                vid=ESPRESSIF_VID,
                pid=0x1002,
                name="ESP32-S3",
                serial_number="ESP002",
            ),
        ]

        with (
            patch("sys.platform", "linux"),
            patch(_COMPORTS_PATCH, return_value=mock_ports),
        ):
            # VID filtering: Espressif ports only, sorted by device path.
            result = esptool.get_port_list(vids=[ESPRESSIF_VID])
            assert result == ["/dev/ttyUSB1", "/dev/ttyUSB2"]

            # PID filtering: single match.
            result = esptool.get_port_list(pids=[0x1001])
            assert result == ["/dev/ttyUSB1"]

            # Device-path substring filtering (``names``).
            result = esptool.get_port_list(names=["ttyUSB1"])
            assert result == ["/dev/ttyUSB1"]

            # USB serial-number substring filtering.
            result = esptool.get_port_list(serials=["ESP"])
            assert result == ["/dev/ttyUSB1", "/dev/ttyUSB2"]
