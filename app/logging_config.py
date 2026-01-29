import logging
import logging.handlers
from pathlib import Path

def setup_logging(log_dir: Path = None) -> logging.Logger:
    """Configura logging para la aplicación"""
    if log_dir is None:
        log_dir = Path("/app/data/logs") if Path("/app").exists() else Path("./logs")
    
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Logger root
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Formato
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Handler de consola (stdout)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # Handler de archivo (rotativo)
    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "cartelas.log",
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # Handler de errores en archivo separado
    error_handler = logging.FileHandler(log_dir / "cartelas_errors.log")
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    logger.addHandler(error_handler)
    
    return logger
