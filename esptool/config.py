# SPDX-FileCopyrightText: 2014-2025 Espressif Systems (Shanghai) CO LTD,
# other contributors as noted.
#
# SPDX-License-Identifier: GPL-2.0-or-later

from esp_pylib.config import ToolConfig

from .logger import log

CONFIG_OPTIONS = [
    "timeout",
    "chip_erase_timeout",
    "max_timeout",
    "sync_timeout",
    "md5_timeout_per_mb",
    "erase_region_timeout_per_mb",
    "erase_write_timeout_per_mb",
    "mem_end_rom_timeout",
    "serial_write_timeout",
    "connect_attempts",
    "write_block_attempts",
    "reset_delay",
    "open_port_attempts",
    "custom_reset_sequence",
    "custom_hard_reset_sequence",
]

ENV_VAR = "ESPTOOL_CFGFILE"
SECTION_NAME = "esptool"
CONFIG_FILENAMES = ["esptool.cfg", "setup.cfg", "tox.ini"]


def load_config_file(verbose=False):
    """Locate, parse, and return the esptool configuration.

    Returns a ``(parser, path)`` tuple where ``path`` is the absolute path
    of the loaded file (as a string) or ``None`` when no config was found.
    The parser always contains an ``[esptool]`` section so callers can use
    ``parser["esptool"].get(...)`` unconditionally.

    Uses :class:`esp_pylib.config.ToolConfig` for the discovery / parsing /
    verbose-logging pipeline. The esptool ``log`` instance is passed
    explicitly so the messages route through esptool's Rich-styled logger
    rather than relying on the ``EspLog.instance`` global (which is
    ``None`` at module-import time, where this function is called).

    ``permissive_env_var=True`` preserves esptool's historical behavior of
    falling back to the standard search path when ``ESPTOOL_CFGFILE``
    points at a missing file or one without an ``[esptool]`` section,
    instead of aborting CLI startup.
    """
    config = ToolConfig(
        section_name=SECTION_NAME,
        config_filenames=CONFIG_FILENAMES,
        env_var=ENV_VAR,
        valid_options=CONFIG_OPTIONS,
        permissive_env_var=True,
        verbose=verbose,
        logger=log,
    )
    parser, path = config.load()
    return parser, (str(path) if path is not None else None)
