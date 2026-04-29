# SPDX-FileCopyrightText: 2025 Espressif Systems (Shanghai) CO LTD
#
# SPDX-License-Identifier: GPL-2.0-or-later

import os
import sys
from abc import abstractmethod
from typing import ClassVar

from esp_pylib.logger import EspLog
from esp_pylib.logger import EspLogBase
from esp_pylib.logger import Verbosity as BaseVerbosity
from rich.console import Console
from rich.control import Control
from rich.segment import ControlType


class Verbosity(BaseVerbosity):
    """Extend the base verbosity levels with esptool-specific levels."""

    AUTO = BaseVerbosity.NORMAL
    COMPACT = 7


class TemplateLogger(EspLogBase):
    """
    Abstract base class for esptool loggers.

    Extends EspLogBase with esptool-specific stage collapsing.
    Provides default no-op implementations for debug() and die()
    so existing custom logger subclasses do not need to add those methods.
    """

    @abstractmethod
    def stage(self, finish: bool = False):
        """
        Start or finish a new collapsible stage.
        """
        pass

    @abstractmethod
    def set_verbosity(self, verbosity: str | int) -> None:
        """
        Set the verbosity level.
        """
        pass

    @abstractmethod
    def error(self, message) -> None:
        """Error message to stderr."""
        pass

    @abstractmethod
    def warning(self, message: str) -> None:
        """Warning message to stderr."""
        pass

    # Backward compatibility API; no need to implement in custom loggers
    # err/warn aliases for error/warning + additional suggestion to IDE
    def err(self, message: str, suggestion: str | None = None) -> None:
        self.error(message)
        # send_log_message('error', message, suggestion, file, line)

    def warn(self, message: str, suggestion: str | None = None) -> None:
        self.warning(message)
        # send_log_message('warning', message, suggestion, file, line)

    def debug(self, message: str) -> None:
        # Debug is not used in esptool; implement this to satisfy the EspLogBase ABC
        pass


class EsptoolLogger(EspLog, TemplateLogger):
    """
    Esptool's concrete logger with Rich colors, stage collapsing, and
    progress bars. Inherits Rich Console infrastructure from EspLog.
    """

    instance: ClassVar["EsptoolLogger | None"] = None

    _stage_active: bool = False
    _newline_count: int = 0
    # Stores (kind, message) tuples: kind is 'note' or 'warning'
    _kept_lines: list = []

    _smart_features: bool = False
    # Console with force_terminal=True so control codes are emitted when stdout
    # is a pipe (e.g. idf.py subprocess)
    _control_console: Console | None = None

    def __new__(cls):
        """
        Singleton to ensure only one instance of the logger exists.
        """
        if cls.instance is None:
            cls.instance = super().__new__(cls)
        return cls.instance

    def __init__(self):
        # Singleton: EspLog.__init__ must run only once per instance
        if getattr(self, "_esptool_logger_inited", False):
            return
        self._esptool_logger_inited = True
        super().__init__()
        # Enable stage collapsing and progress-bar overwrite by default when
        # terminal supports it
        if self._verbosity == Verbosity.AUTO:
            self.__class__._set_smart_features()

    @classmethod
    def _del(cls) -> None:
        if cls.instance is not None:
            cls.instance._esptool_logger_inited = False
        cls.instance = None

    @classmethod
    def _set_smart_features(cls, override: bool | None = None):
        inst = cls.instance
        assert inst is not None
        # Check for smart terminal and color support
        if override is not None:
            inst._smart_features = override
            inst._control_console = None  # Recreate when next needed
        else:
            # TODO: Use rich.terminal.is_interactive() instead? We need to be careful
            # with this as it might break something
            is_tty = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
            term_supports_color = os.getenv("TERM", "").lower() in (
                "xterm",
                "xterm-256color",
                "screen",
                "screen-256color",
                "linux",
                "vt100",
            )

            # Determine if colors should be enabled
            inst._smart_features = is_tty or term_supports_color and not inst.no_color
            # Handle Windows specifically
            if sys.platform == "win32" and inst._smart_features:
                try:
                    from colorama import init

                    init()  # Enable ANSI support on Windows
                except ImportError:
                    inst._smart_features = False
            if not inst._smart_features:
                inst._control_console = None

    def _get_interactive_console(self) -> Console | None:
        """Prefer the control console so progress works when stdout is piped
        (e.g. idf.py)."""
        if self._smart_features:
            console = self._control_stdout()
            if console is not None:
                return console
        return super()._get_interactive_console()

    def _control_stdout(self) -> Console | None:
        """Console that emits control codes even when stdout is a pipe
        (e.g. idf.py subprocess)."""
        if not self._smart_features:
            return None
        if self._control_console is None:
            self._control_console = Console(
                file=sys.stdout,
                no_color=self.no_color,
                highlight=self._stdout._highlight,
                force_terminal=True,
            )
        return self._control_console

    def print(self, *args, **kwargs):
        """
        Log a plain message. Count newlines if in a collapsing stage.
        """
        if self._verbosity == Verbosity.SILENT:
            return
        if self._stage_active:
            # Count the number of newlines in the message
            message = "".join(map(str, args))
            self._newline_count += message.count("\n")
            if kwargs.get("end", "\n") == "\n":
                self._newline_count += 1
        # Flush is not used in rich; TODO: Remove flush from print calls
        kwargs.pop("flush", None)
        super().print(*args, **kwargs)

    def note(self, message: str):
        """
        Log a Note: message (cyan prefix) to stdout.
        """
        if self._stage_active:
            self._kept_lines.append(("note", message))
        super().note(message)

    def warning(self, message: str):
        """
        Log a Warning: message (yellow prefix) to stderr.
        """
        if self._stage_active:
            self._kept_lines.append(("warning", message))
        super().warn(message)

    def error(self, message) -> None:
        """
        Log an Error: message (red, bold prefix) to stderr.
        Uses EspLog.err directly so TemplateLogger.err() does not recurse into error().
        """
        super().err(message)

    def progress_bar(
        self,
        cur_iter: int,
        total_iters: int,
        prefix: str = "",
        suffix: str = "",
        bar_length: int = 30,
    ) -> None:
        """
        Render a progress bar via the parent (Rich) implementation, then track
        the trailing newline emitted on completion so a surrounding
        :meth:`stage` collapses the finished bar away — preserving the legacy
        esptool behaviour where a successful read/write/verify only leaves the
        summary line on screen.
        """
        super().progress_bar(cur_iter, total_iters, prefix, suffix, bar_length)
        # The parent uses ``c.print()`` on a Rich Console, bypassing our
        # overridden ``print()``. So we never get a chance to bump
        # ``_newline_count`` for the bar. The Rich path with ``_smart_features``
        # enabled overwrites the bar in place with ``\r`` + ERASE_IN_LINE on
        # every update and only emits ``\n`` on the completion call. Count
        # exactly that one newline so ``stage(finish=True)`` cursor-up + erases
        # the leftover bar line. Verbose / non-TTY modes set
        # ``_smart_features=False`` and disable stage collapsing entirely, so
        # they don't need this.
        if not self._stage_active or not self._smart_features:
            return
        if self._verbosity == Verbosity.SILENT:  # type: ignore
            return
        if total_iters < 0:
            return
        if total_iters == 0:
            emitted_newline = True
        else:
            clamped = max(0, min(cur_iter, total_iters))
            emitted_newline = clamped == total_iters
        if emitted_newline:
            self._newline_count += 1

    def stage(self, finish: bool = False):
        """
        Start or finish a collapsible stage.
        Any log messages printed between the start and finish will be deleted
        when the stage is successfully finished.
        Warnings and notes will be saved and printed at the end of the stage.
        If terminal doesn't support smart features, no collapsing happens.
        """
        if finish:
            if not self._stage_active:
                return
            # Deactivate stage to stop collecting input
            self._stage_active = False

            if self._smart_features:
                # Delete printed lines using Rich Control (cursor up + erase line).
                # Use _control_stdout() so codes are emitted when run under idf.py.
                console = self._control_stdout()
                if console is not None:
                    controls = []
                    for _ in range(self._newline_count):
                        controls.append(Control.move(y=-1))
                        controls.append(Control((ControlType.ERASE_IN_LINE, 2)))
                    if controls:
                        console.print(*controls, end="")
                        console.file.flush()
                # Print saved warnings and notes
                for kind, line in self._kept_lines:
                    if kind == "note":
                        super().note(line)
                    elif kind == "warning":
                        super().warn(line)

            # Clean the buffers for next stage
            self._kept_lines.clear()
            self._newline_count = 0
        else:
            self._stage_active = True

    def set_logger(self, new_logger):
        if not isinstance(new_logger, TemplateLogger):
            raise TypeError(
                f"New logger must implement the TemplateLogger interface, "
                f"got {type(new_logger).__name__!r}"
            )
        self.__class__ = new_logger.__class__

    def set_verbosity(self, verbosity: str | int):
        """
        Set the verbosity level to one of the following:
        - "auto": Enable smart terminal features if supported by the terminal
        - "verbose": Enable verbose output (no collapsing output)
        - "silent": Disable all output except errors
        - "compact": Enable smart terminal features even if not auto-detected
        """
        if isinstance(verbosity, str):
            try:
                new_verbosity = getattr(Verbosity, verbosity.upper())
            except AttributeError:
                raise ValueError(f"Invalid verbosity level: {verbosity}") from None
        else:
            new_verbosity = verbosity

        if new_verbosity == self._verbosity:  # type: ignore
            return

        self._verbosity = new_verbosity
        if new_verbosity == Verbosity.AUTO:
            self._set_smart_features()
        elif new_verbosity == Verbosity.COMPACT:
            self._set_smart_features(override=True)
        elif new_verbosity == Verbosity.VERBOSE:
            self._set_smart_features(override=False)


log = EsptoolLogger()
