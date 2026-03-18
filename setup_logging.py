"""
A reusable, project-agnostic logging setup module.

Usage:
    from setup_logging import setup_logger

    setup_logger()                          # call once in __main__
    log = logging.getLogger(__name__)       # use anywhere in any module
    log.info("Hello")
    log.debug("Detail")
    log.error("Something went wrong")

Design decisions:
    - Configures the root logger so that all module loggers created via
      logging.getLogger(__name__) automatically route through the same
      handlers without any per-module setup.
    - True singleton: returns the existing logger instance on repeated calls.
    - FileHandler uses mode='w' for clean logs — no file deletion needed.
    - Color-coded stream output for fast visual triage in the terminal.
    - sys.excepthook captures all uncaught exceptions with full traceback.
    - KeyboardInterrupt is intentionally excluded from critical logging.
"""

import logging
import sys
from typing import Optional

# --------------------------------------------------------------------------- #
# ANSI color codes for terminal output                                         #
# --------------------------------------------------------------------------- #
_LEVEL_COLORS: dict[int, str] = {
    logging.DEBUG:    "\033[36m",   # Cyan
    logging.INFO:     "\033[32m",   # Green
    logging.WARNING:  "\033[33m",   # Yellow
    logging.ERROR:    "\033[31m",   # Red
    logging.CRITICAL: "\033[1;31m", # Bold Red
}
_COLOR_RESET = "\033[0m"


class _ColorFormatter(logging.Formatter):
    """
    A logging formatter that applies ANSI color codes to the log level name
    in terminal output. Falls back gracefully on non-TTY streams.
    """

    def format(self, record: logging.LogRecord) -> str:
        color = _LEVEL_COLORS.get(record.levelno, "")
        record.levelname = f"{color}{record.levelname}{_COLOR_RESET}"
        return super().format(record)


# --------------------------------------------------------------------------- #
# Own-modules filter                                                           #
# --------------------------------------------------------------------------- #
_OWN_PREFIXES = ("__main__", "main", "lib.", "sources.", "scripts.")


class _OwnModulesFilter(logging.Filter):
    """
    Only passes log records whose logger name originates from this project's
    own modules. Records from third-party libraries are silently discarded.

    The check is prefix-based: a record passes if its logger name starts with
    any entry in _OWN_PREFIXES.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return any(record.name.startswith(p) for p in _OWN_PREFIXES)


# --------------------------------------------------------------------------- #
# Module-level sentinel to enforce singleton per logger name                  #
# --------------------------------------------------------------------------- #
_initialized_loggers: dict[str, logging.Logger] = {}


def setup_logger(
    name: str = "app",
    log_file: Optional[str] = "app.log",
    level: int = logging.DEBUG,
    clean: bool = True,
    capture_warnings: bool = True,
    own_modules_only: bool = True,
) -> logging.Logger:
    """
    Configure the root logger and return a named child logger for the caller.
    Returns the existing instance if already set up (true singleton per name).

    Configuring the root logger ensures that all module loggers created via
    logging.getLogger(__name__) automatically route through the same handlers
    without any per-module setup. Call once in __main__ before any logging occurs.

    Args:
        name:
            Used as the singleton key and as the name of the returned logger.
            Does not affect which logger receives the handlers (always root).
        log_file:
            Path to the log file. Pass None to disable file logging entirely
            (stream-only mode, useful for CLI tools or tests).
        level:
            Minimum log level for both handlers. Defaults to DEBUG so nothing
            is silently swallowed during development.
        clean:
            If True, the log file is truncated on each run (mode='w').
            If False, new entries are appended (mode='a').
        capture_warnings:
            If True, Python's warnings.warn() output is routed through the
            logging system instead of being printed to stderr.
        own_modules_only:
            If True (default), only log records from this project's own modules
            are shown (prefix-matched against _OWN_PREFIXES). Third-party
            library logs are silently discarded.
            If False, all log records including third-party libraries are shown.

    Returns:
        A fully configured logging.Logger instance.

    Example:
        >>> log = setup_logger(name="my_project", log_file="run.log")
        >>> log.info("Pipeline started")
    """
    # --- Singleton guard --------------------------------------------------- #
    if name in _initialized_loggers:
        return _initialized_loggers[name]

    root = logging.getLogger()
    root.setLevel(level)

    # --- File handler ------------------------------------------------------ #
    if log_file is not None:
        file_mode = "w" if clean else "a"
        file_handler = logging.FileHandler(log_file, mode=file_mode, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        if own_modules_only:
            file_handler.addFilter(_OwnModulesFilter())
        root.addHandler(file_handler)

    # --- Stream handler ---------------------------------------------------- #
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(level)

    use_color = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
    if use_color:
        stream_handler.setFormatter(
            _ColorFormatter(
                fmt="%(name)s | %(levelname)s | %(message)s",
            )
        )
    else:
        stream_handler.setFormatter(
            logging.Formatter(
                fmt="%(name)s | %(levelname)s | %(message)s",
            )
        )
    if own_modules_only:
        stream_handler.addFilter(_OwnModulesFilter())
    root.addHandler(stream_handler)

    # --- Uncaught exception hook ------------------------------------------- #
    def _handle_uncaught_exception(
        exc_type: type,
        exc_value: BaseException,
        exc_traceback,
    ) -> None:
        """
        Redirect uncaught exceptions to the logger as CRITICAL entries with
        full traceback. KeyboardInterrupt is passed through unchanged so that
        Ctrl+C still behaves normally in the terminal.
        """
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        root.critical(
            "Uncaught exception — process terminated",
            exc_info=(exc_type, exc_value, exc_traceback),
        )

    sys.excepthook = _handle_uncaught_exception

    # --- Optional: route warnings.warn() through logging ------------------ #
    if capture_warnings:
        # Root logger already receives py.warnings records via propagation.
        logging.captureWarnings(True)

    # --- Register singleton ------------------------------------------------ #
    logger = logging.getLogger(name)
    _initialized_loggers[name] = logger

    logger.info("Logger '%s' initialized (level=%s, file=%s, clean=%s)",
                name, logging.getLevelName(level), log_file, clean)
    return logger
