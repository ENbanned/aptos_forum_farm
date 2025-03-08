import sys
from pathlib import Path

from loguru import logger


def configure_logging(level: str = "INFO", log_to_file: bool = True, log_file: Path = None):
    logs_dir = Path("files/logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    
    logger.remove()
    
    logger.add(
        sys.stdout, 
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        colorize=True,
    )
    
    if log_to_file:
        if not log_file:
            log_file = logs_dir / "aptos_farm.log"
            
        logger.add(
            log_file,
            level="INFO",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
            rotation="10 MB",
            compression="zip",
            retention="10 days",
            backtrace=True,
            diagnose=True,
            filter=lambda record: "http" not in record["message"].lower() and 
                                 "tls" not in record["name"].lower()
        )
            
    return logger


logger = configure_logging()