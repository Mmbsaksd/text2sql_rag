"""
Centralized logging configuration for the RAG application.
Provides structured logging with rotation and multiple handlers.
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

def setup_logging(log_level: str = "INFO") -> logging.Logger:
    """
    Configure application-wide logging with console and file handlers.
    In Lambda environment, uses CloudWatch-compatible stdout logging only.

    Args:
        log_level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)

    Returns:
        Configured logger instance
    """
    is_lambda = os.getenv("AWS_LAMBDA_FUNCTION_NAME") is not None

    logger = logging.getLogger("rag_app")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    if logger.handlers:
        return logger
    
    if is_lambda:
        console_handler = logging.StreamHandler(sys.stdout)