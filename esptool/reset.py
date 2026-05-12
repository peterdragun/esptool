# SPDX-FileCopyrightText: 2014-2025 Fredrik Ahlberg, Angus Gratton,
# Espressif Systems (Shanghai) CO LTD, other contributors as noted.
#
# SPDX-License-Identifier: GPL-2.0-or-later

import errno
import time

from esp_pylib.serial_reset import DEFAULT_RESET_DELAY
from esp_pylib.serial_reset import classic_bootloader_reset
from esp_pylib.serial_reset import execute_custom_reset
from esp_pylib.serial_reset import hard_reset
from esp_pylib.serial_reset import unix_tight_bootloader_reset
from esp_pylib.serial_reset import usb_jtag_bootloader_reset

from .util import FatalError, PrintOnce
from .logger import log

# DEFAULT_RESET_DELAY is re-exported above so existing imports
# (`from esptool.reset import DEFAULT_RESET_DELAY` in loader.py and
# esp_rfc2217_server) keep working without changes.

__all__ = [
    "ClassicReset",
    "CustomReset",
    "DEFAULT_RESET_DELAY",
    "HardReset",
    "ResetStrategy",
    "USBJTAGSerialReset",
    "UnixTightReset",
]


class ResetStrategy:
    """
    Wraps a named reset sequence with esptool's retry/reopen behavior.

    The actual DTR/RTS pulse trains live in ``esp_pylib.serial_reset`` so they
    can be shared with esp-idf-monitor; this class only owns the
    "open the port if it dropped, retry up to 3 times" policy that is specific
    to esptool's connect loop.
    """

    print_once = PrintOnce(log.warning)

    def __init__(self, port, reset_delay=DEFAULT_RESET_DELAY, flow_control=False):
        self.port = port
        self.reset_delay = reset_delay
        # ``flow_control`` selects the CP2102C-class variant of the underlying
        # esp_pylib sequence: such adapters tie CTS to the chip's RTS, so the
        # trailing IO0 / DTR writes have to be skipped (boot reset) and HUPCL
        # has to be cleared before close (hard reset) to keep the chip from
        # being held in reset by an RTS twitch on port close.
        self.flow_control = flow_control

    def __call__(self):
        """
        On targets with USB modes, the reset process can cause the port to
        disconnect / reconnect during reset.
        This will retry reconnections on ports that
        drop out during the reset sequence.
        """
        for retry in reversed(range(3)):
            try:
                if not self.port.isOpen():
                    self.port.open()
                self.reset()
                break
            except OSError as e:
                # ENOTTY for TIOCMSET; EINVAL for TIOCMGET
                if e.errno in [errno.ENOTTY, errno.EINVAL]:
                    self.print_once(
                        "Chip was NOT reset. Setting RTS/DTR lines is not "
                        f"supported for port '{self.port.name}'. Set --before and "
                        "--after arguments to 'no-reset' and switch to bootloader "
                        "manually to avoid this warning."
                    )
                    break
                elif not retry:
                    raise
                self.port.close()
                time.sleep(0.5)

    def reset(self):
        pass


class ClassicReset(ResetStrategy):
    """
    Classic reset sequence, sets DTR and RTS lines sequentially.
    """

    def reset(self):
        classic_bootloader_reset(
            self.port, 0.1, self.reset_delay, flow_control=self.flow_control
        )


class UnixTightReset(ResetStrategy):
    """
    UNIX-only reset sequence with custom implementation,
    which allows setting DTR and RTS lines at the same time.
    """

    def reset(self):
        unix_tight_bootloader_reset(
            self.port, 0.1, self.reset_delay, flow_control=self.flow_control
        )


class USBJTAGSerialReset(ResetStrategy):
    """
    Custom reset sequence, which is required when the device
    is connecting via its USB-JTAG-Serial peripheral.
    """

    def reset(self):
        usb_jtag_bootloader_reset(self.port)


class HardReset(ResetStrategy):
    """
    Reset sequence for hard resetting the chip.
    Can be used to reset out of the bootloader or to restart a running app.
    """

    def __init__(self, port, uses_usb=False, flow_control=False):
        super().__init__(port, flow_control=flow_control)
        self.uses_usb = uses_usb

    def reset(self):
        if self.uses_usb:
            # Chips on the internal USB peripheral disappear from the bus
            # while reset is asserted; the post-release wait gives them time
            # to re-enumerate before any further DTR/RTS writes. ``flow_control``
            # is not applicable here because internal-USB chips don't go
            # through a CP2102C-class UART bridge.
            hard_reset(self.port, hold_delay=0.2, post_release_delay=0.2)
        else:
            hard_reset(self.port, hold_delay=0.1, flow_control=self.flow_control)


class CustomReset(ResetStrategy):
    """
    Custom reset strategy defined with a string.

    CustomReset object is created as "rst = CustomReset(port, seq_str)"
    and can be later executed simply with "rst()"

    The seq_str input string consists of individual commands divided by "|".
    Commands (e.g. R0) are defined by a code (R) and an argument (0).

    The commands are:
    D: setDTR - 1=True / 0=False
    R: setRTS - 1=True / 0=False
    U: setDTRandRTS (Unix-only) - 0,0 / 0,1 / 1,0 / or 1,1
    W: Wait (time delay) - positive float number

    e.g.
    "D0|R1|W0.1|D1|R0|W0.05|D0" represents the ClassicReset strategy
    "U1,1|U0,1|W0.1|U1,0|W0.05|U0,0" represents the UnixTightReset strategy
    """

    def __init__(self, port, seq_str):
        super().__init__(port)
        self.seq_str = seq_str

    def reset(self):
        try:
            execute_custom_reset(self.port, self.seq_str)
        except ValueError as e:
            # Convert esp_pylib's parse error into esptool's FatalError so the
            # CLI surfaces it with the historical "Invalid custom reset
            # sequence option format:" prefix that tests/users rely on.
            raise FatalError(f"Invalid custom reset sequence option format: {e}")
