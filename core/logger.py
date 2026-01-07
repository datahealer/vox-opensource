import logging
import os
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)


def setup_logger(
    name: str = "vox",
    level: int = logging.INFO
) -> logging.Logger:
    """
    Creates a logger that logs to:
    - Terminal (stdout)
    - Daily rotating log files
    """

    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Prevent duplicate logs
    if logger.handlers:
        return logger

    # ---- Formatter ----
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ---- Console Handler ----
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    # ---- File Handler (daily rotation) ----
    file_handler = TimedRotatingFileHandler(
        filename=os.path.join(LOG_DIR, "vox.log"),
        when="midnight",
        interval=1,
        backupCount=14,      # keep last 14 days
        encoding="utf-8",
        utc=False,
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    # ---- Attach handlers ----
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    logger.propagate = False

    return logger
