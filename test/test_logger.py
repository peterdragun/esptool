import pytest
from io import StringIO
from unittest.mock import patch
from esptool import __version__
from esptool.logger import EsptoolLogger, log, TemplateLogger
from esptool.cmds import version

from rich.console import Console


# Custom logger that implements all methods
class CustomLogger(TemplateLogger):
    def print(self, *args, **kwargs):
        print("Custom logger:", *args, **kwargs)

    def note(self, message: str):
        """
        Logs a Note: message.
        """
        pass

    def warning(self, message: str):
        """
        Logs a Warning: message.
        """
        pass

    def error(self, message: str):
        """
        Logs an error message.
        """
        pass

    def stage(self, finish=False):
        pass

    def progress_bar(
        self,
        cur_iter: int,
        total_iters: int,
        prefix: str = "",
        suffix: str = "",
        bar_length: int = 30,
    ):
        pass

    def set_verbosity(self, verbosity: str):
        pass


# Custom logger that doesn't implement all methods
class CustomLoggerIncomplete:
    def print(self, *args, **kwargs):
        pass


@pytest.mark.host_test
class TestLogger:
    @pytest.fixture
    def logger(self):
        log = EsptoolLogger()
        log._set_smart_features(True)
        return log

    def test_singleton(self, logger):
        logger2 = EsptoolLogger()
        assert logger is logger2
        assert logger is log

    def test_print(self, logger):
        out = StringIO()
        with patch.object(logger, "_stdout", new=Console(file=out)):
            logger.print("With newline")
            logger.print("Without newline", end="")
        assert out.getvalue() == "With newline\nWithout newline"

    def test_note_message(self, logger):
        out = StringIO()
        with patch.object(logger, "_stdout", new=Console(file=out)):
            logger.note("This is a note")
        assert out.getvalue() == "Note: This is a note\n"

    def test_warning_message(self, logger):
        out = StringIO()
        with patch.object(logger, "_stderr", new=Console(file=out)):
            logger.warning("This is a warning")
        assert out.getvalue() == "WARNING: This is a warning\n"

    def test_error_message(self, logger):
        out = StringIO()
        with patch.object(logger, "_stderr", new=Console(file=out)):
            logger.error("This is an error")
        assert out.getvalue() == "ERROR: This is an error\n"

    def test_stage(self, logger):
        out = StringIO()
        logger._control_console = None
        with (
            patch.object(logger, "_stdout", new=Console(file=out)),
            patch("sys.stdout", new=out),
        ):
            logger.stage()
            assert logger._stage_active
            logger.print("Line1")
            logger.print("Line2")
            logger.stage(finish=True)
            assert not logger._stage_active
            logger.print("Line3")

            output = out.getvalue()
            # Rich Control emits cursor-up + erase-line (\x1b[1A\x1b[2K) per line
            assert "\033[1A\033[2K" * 2 in output or "\x1b[1A\x1b[2K" * 2 in output
            assert "Line1\nLine2\n" in output
            assert "Line1\nLine2\nLine3\n" not in output

    def test_progress_bar(self, logger):
        out = StringIO()
        logger._control_console = None
        with (
            patch.object(logger, "_stdout", new=Console(file=out, highlight=False)),
            patch("sys.stdout", new=out),
        ):
            logger.progress_bar(
                cur_iter=2,
                total_iters=4,
                prefix="Progress: ",
                suffix=" (2/4)",
                bar_length=10,
            )
            logger.progress_bar(
                cur_iter=4,
                total_iters=4,
                prefix="Progress: ",
                suffix=" (4/4)",
                bar_length=10,
            )
        output = out.getvalue()
        assert "Progress: [====>     ]  50.0% (2/4)" in output
        assert "Progress: [==========] 100.0% (4/4) \n" in output

    def test_set_incomplete_logger(self, logger):
        with pytest.raises(
            TypeError,
            match="New logger must implement the TemplateLogger interface, "
            "got 'CustomLoggerIncomplete'",
        ):
            logger.set_logger(CustomLoggerIncomplete())

    def test_set_logger(self, logger):
        # Original logger (Rich Console holds the stream from init; patch the instance.)
        out = StringIO()
        with patch.object(log, "_stdout", new=Console(file=out)):
            version()  # This will log.print the esptool version
            assert out.getvalue() == f"{__version__}\n"

        # Replace logger with custom one
        with patch("sys.stdout", new=StringIO()) as fake_out:
            logger.set_logger(CustomLogger())
            assert isinstance(logger, CustomLogger)
            version()  # This will use print from CustomLogger
            output = fake_out.getvalue()
            assert output == f"Custom logger: {__version__}\n"
