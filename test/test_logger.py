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
        assert "Progress:" in output
        assert "50.0%" in output
        assert "\u2501" in output or "\u2500" in output
        assert "100.0%" in output
        assert output.endswith("\n")

    def test_progress_context_emits_bars(self, logger):
        out = StringIO()
        logger._control_console = None
        with (
            patch.object(logger, "_stdout", new=Console(file=out, highlight=False)),
            patch("sys.stdout", new=out),
        ):
            with logger.progress(total=2, description="Step") as bar:
                bar.update(1)
                bar.update(1)
        text = out.getvalue()
        assert "1/2" in text and "2/2" in text

    def test_stage_collapses_finished_progress_bar(self, logger):
        """
        Regression: a completed progress bar inside a stage must be erased by
        ``stage(finish=True)`` — same as the original esptool logger did. The
        Rich-based parent emits a single ``\\n`` on the completion call which
        bypasses our overridden ``print()``; the override of ``progress_bar``
        in :class:`EsptoolLogger` must count it so the cursor-up + erase-line
        sequence covers the leftover bar line.
        """
        out = StringIO()
        logger._control_console = None
        with (
            patch.object(
                logger,
                "_stdout",
                new=Console(file=out, highlight=False, force_terminal=True),
            ),
            patch("sys.stdout", new=out),
        ):
            logger.stage()
            with logger.progress(total=4, description="Reading") as bar:
                bar.update(2)
                bar.update(2)
            logger.stage(finish=True)
            logger.print("Done.")

        output = out.getvalue()
        # The parent emits exactly one trailing newline (on the completion
        # update); ``stage(finish=True)`` must therefore issue exactly one
        # cursor-up + erase-line pair so the finished bar is gone before
        # "Done." is printed.
        assert "\x1b[1A\x1b[2K" in output
        assert output.rstrip().endswith("Done.")
        # And the percentage from the bar must NOT survive past "Done." in
        # the final visible text — i.e. the bar line was actually erased.
        assert output.count("Done.") == 1
        assert output.split("Done.")[1].strip() == ""

    def test_progress_bar_outside_stage_does_not_change_newline_count(self, logger):
        """``_newline_count`` only matters inside an active stage."""
        out = StringIO()
        logger._control_console = None
        logger._newline_count = 0
        with (
            patch.object(
                logger,
                "_stdout",
                new=Console(file=out, highlight=False, force_terminal=True),
            ),
            patch("sys.stdout", new=out),
        ):
            logger.progress_bar(
                cur_iter=4,
                total_iters=4,
                prefix="Done: ",
                suffix="",
                bar_length=10,
            )
        assert logger._newline_count == 0

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
