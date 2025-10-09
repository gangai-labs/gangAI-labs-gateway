# file:src/utils/logger.py

import json
import logging
import logging.handlers
import os
import inspect
from datetime import datetime
from pathlib import Path
from colorlog import ColoredFormatter
from pydantic import Field, field_validator, ValidationError, BaseModel
from typing import Optional


class LoggerConfig(BaseModel):
    LOG_LEVEL: str = Field(default="INFO")
    LOG_FILE: Optional[str] = Field(default=None)
    ENABLE_SEVERITY_FILES: bool = Field(default=True)
    SEVERITY_FILES_DIR: str = Field(default="logs/severity")
    MAX_LOG_SIZE_MB: int = Field(default=10)
    BACKUP_COUNT: int = Field(default=5)
    PROJECT_ROOT: Optional[str] = Field(default=None)  # New field to specify project root

    @field_validator('LOG_LEVEL')
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid_levels = {'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'}
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(f'Invalid LOG_LEVEL: {v}. Must be one of {valid_levels}')
        return v_upper

    @field_validator('LOG_FILE')
    @classmethod
    def validate_log_file(cls, v: Optional[str], values) -> Optional[str]:
        if not v:
            return None
        v = v.strip()

        # Get project root from values or use default detection
        project_root = values.data.get('PROJECT_ROOT')
        if not project_root:
            # Go up 3 levels from src/logger.py to get to project root
            # src/logger.py -> src/ -> project_root/
            project_root = Path(__file__).parent.parent.parent.absolute()

        if not os.path.isabs(v):
            v = str(Path(project_root) / v)

        if not Path(v).suffix:
            v = f"{v}.log"

        log_dir = os.path.dirname(v)
        os.makedirs(log_dir, exist_ok=True)
        return v

    @field_validator('SEVERITY_FILES_DIR')
    @classmethod
    def validate_severity_dir(cls, v: str, values) -> str:
        v = v.strip()

        # Get project root from values or use default detection
        project_root = values.data.get('PROJECT_ROOT')
        if not project_root:
            project_root = Path(__file__).parent.parent.parent.absolute()

        if not os.path.isabs(v):
            v = str(Path(project_root) / v)

        return v

    @field_validator('MAX_LOG_SIZE_MB')
    @classmethod
    def validate_max_log_size(cls, v: int) -> int:
        if v <= 0 or v > 1000:
            raise ValueError("MAX_LOG_SIZE_MB must be between 1 and 1000")
        return v

    @field_validator('BACKUP_COUNT')
    @classmethod
    def validate_backup_count(cls, v: int) -> int:
        if v < 0 or v > 50:
            raise ValueError("BACKUP_COUNT must be between 0 and 50")
        return v

    @field_validator('PROJECT_ROOT')
    @classmethod
    def validate_project_root(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return None
        v = v.strip()
        if not os.path.isabs(v):
            # If relative path, make it absolute relative to current working directory
            v = str(Path.cwd() / v)
        return v

class SeverityFilter(logging.Filter):
    """TODO Filter to only allow specific
       TODO log levels IDK pycharm says not used leave for now.Will fix enough for secret demo."""

    def __init__(self, level):
        super().__init__()
        self.level = level

    def filter(self, record):
        return record.levelno == self.level

class JsonFormatter(logging.Formatter):
    """Custom formatter that outputs JSON for ERROR and CRITICAL levels"""
    def format(self, record):
        # Only format as JSON for ERROR and CRITICAL levels
        if record.levelno >= logging.ERROR:
            try:
                exc_info = record.exc_info

                if exc_info:
                    exc_type, exc_value, exc_tb = exc_info

                    # Get traceback information
                    if exc_tb:
                        frame = exc_tb.tb_frame
                        filename = frame.f_code.co_filename
                        lineno = exc_tb.tb_lineno
                        function = frame.f_code.co_name
                    else:
                        filename = lineno = function = "unknown"

                    # Build JSON context
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    error_context = {
                        "error_type": exc_type.__name__ if exc_type else "Unknown",
                        "error_message": str(exc_value),
                        "file": filename,
                        "line": lineno,
                        "function": function,
                        "traceback": self.formatException(exc_info),
                        "timestamp": timestamp,
                        "level": record.levelname,
                        "logger": record.name,
                        "message": record.getMessage()
                    }

                    json_output = json.dumps(error_context, indent=2)
                    return f"{timestamp} - [{record.name}] {record.levelname}:\n{json_output}"
                else:
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    return f"{timestamp} - [{record.name}] {record.levelname} - {record.getMessage()}"
            except:
                # Fallback to normal formatting if JSON fails
                return super().format(record)

        # For non-error levels, use normal formatting
        return super().format(record)

class ColoredJsonFormatter(JsonFormatter):
    """Custom formatter that outputs colored JSON for console output"""

    COLORS = {
        'ERROR': '\033[91m',  # Red
        'CRITICAL': '\033[95m',  # Magenta
        'RESET': '\033[0m'  # Reset
    }

    def format(self, record):
        formatted_message = super().format(record)

        # Add color for error levels in console
        if record.levelno >= logging.ERROR:
            color = self.COLORS.get(record.levelname, self.COLORS['ERROR'])
            return f"{color}{formatted_message}{self.COLORS['RESET']}"

        return formatted_message

class SmartFormatter(logging.Formatter):
    def __init__(self, fmt=None, datefmt=None, style='%'):
        super().__init__(fmt, datefmt, style)
        self.original_fmt = fmt

    def format(self, record):
        # If function name is <module>, don't show it
        if getattr(record, 'funcName', None) == '<module>':
            # Replace .%(funcName)s() with nothing
            self._style._fmt = self.original_fmt.replace('.%(funcName)s()', '')
        else:
            self._style._fmt = self.original_fmt

        return super().format(record)

class SmartColoredFormatter(ColoredFormatter):
    def __init__(self, fmt=None, datefmt=None, style='%', log_colors=None):
        super().__init__(fmt, datefmt, style, log_colors)
        self.original_fmt = fmt

    def format(self, record):
        # If function name is <module>, don't show it
        if getattr(record, 'funcName', None) == '<module>':
            # Replace .%(funcName)s() with nothing
            self._style._fmt = self.original_fmt.replace('.%(funcName)s()', '')
        else:
            self._style._fmt = self.original_fmt

        return super().format(record)

class Logger:
    def __init__(self, project_root: Optional[str] = None):
        self._logger_instances = {}  # Global logger registry to prevent duplicates
        self._complete_log_handler = None  # Single complete log handler instance
        self._severity_handlers = {}  # Shared severity handlers
        self._project_root = project_root  # Store project root

    def _get_project_root(self, config: LoggerConfig) -> Path:
        """Get the project root directory"""
        if config.PROJECT_ROOT:
            return Path(config.PROJECT_ROOT)

        if self._project_root:
            return Path(self._project_root)

        # Default: go up 3 levels from src/logger.py to get to project root
        return Path(__file__).parent.parent.parent.absolute()

    def _setup_severity_handlers(self, config: LoggerConfig):
        """Setup shared severity-specific file handlers"""
        if not config.ENABLE_SEVERITY_FILES or self._severity_handlers:
            return

        severity_levels = {
            'WARNING': logging.WARNING,
            'ERROR': logging.ERROR,
            'CRITICAL': logging.CRITICAL
        }

        try:
            # Resolve project root
            project_root = Path(self._get_project_root(config) or Path.cwd()).resolve()

            # Ensure severity directory exists
            severity_dir = project_root / "logs" / "severity"
            try:
                severity_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                print(f"⚠️  Cannot create severity dir {severity_dir}: {e}")
                return

            # Test write
            test_file = severity_dir / ".write_test"
            try:
                with test_file.open("w") as f:
                    f.write("test")
                test_file.unlink()
            except Exception as e:
                print(f"⚠️  Cannot write to severity dir {severity_dir}: {e}")
                return

            # Formatter
            json_formatter = JsonFormatter(
                "%(asctime)s - [%(name)s] %(levelname)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )

            for level_name, level_value in severity_levels.items():
                log_file_path = severity_dir / f"{level_name.lower()}.log"

                handler = logging.handlers.RotatingFileHandler(
                    log_file_path,
                    mode="a",
                    maxBytes=config.MAX_LOG_SIZE_MB * 1024 * 1024,
                    backupCount=config.BACKUP_COUNT,
                    encoding="utf-8",
                )
                handler.setFormatter(json_formatter)
                handler.setLevel(level_value)

                # Exact-level filter
                handler.addFilter(lambda record, lvl=level_value: record.levelno == lvl)

                # Save in dict
                self._severity_handlers[level_name] = handler

            #print(f" Severity handlers setup complete in {severity_dir}")

        except Exception as e:
            print(f"⚠️  Could not set up severity-specific log files: {e}")

    def setup_logger(self, config: Optional[LoggerConfig] = None, logger_name: str = "main_logger"):
        """Setup logger with validated Pydantic configuration - Singleton pattern"""
        # Return existing logger if already created
        if logger_name in self._logger_instances:
            return self._logger_instances[logger_name]

        # Load and validate config if not provided
        if config is None:
            try:
                # Set default project root if not provided
                config_data = {}
                if self._project_root:
                    config_data['PROJECT_ROOT'] = self._project_root

                config = LoggerConfig(**config_data)
            except ValidationError as e:
                print("❌ Logger configuration validation failed fix .env :")
                for error in e.errors():
                    print(f"  - {error['loc'][0]}: {error['msg']}")
                # Fall back to basic config
                config = LoggerConfig(
                    LOG_LEVEL="INFO",
                    LOG_FILE=None,
                    ENABLE_SEVERITY_FILES=False
                )
                return None

        # Setup shared handlers
        self._setup_severity_handlers(config)

        # Main application logger
        logger = logging.getLogger(logger_name)

        # Clear existing handlers to prevent duplication
        logger.handlers.clear()
        logger.propagate = False

        # Set log level
        level_mapping = {
            'DEBUG': logging.DEBUG,
            'INFO': logging.INFO,
            'WARNING': logging.WARNING,
            'ERROR': logging.ERROR,
            'CRITICAL': logging.CRITICAL
        }
        logger.setLevel(level_mapping[config.LOG_LEVEL])

        # Normal formatter
        # Now use the smart formatters
        normal_formatter = SmartFormatter(
            '%(asctime)s - %(levelname)s [%(name)s.%(funcName)s()] - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        color_formatter = SmartColoredFormatter(
            '%(log_color)s%(asctime)s - %(levelname)s [%(name)s.%(funcName)s()] - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            log_colors={
                'DEBUG': 'cyan',
                'INFO': 'green',
                'WARNING': 'yellow',
                'ERROR': 'red',
                'CRITICAL': 'bold_red',
            }
        )
        json_formatter = JsonFormatter()
        colored_json_formatter = ColoredJsonFormatter()

        # Console handler - use colored formatter for all levels
        console_handler = logging.StreamHandler()

        # For console, use colored JSON for errors and normal color for others
        class ConsoleLevelAwareFormatter(logging.Formatter):
            def format(self, record):
                if record.levelno >= logging.ERROR:
                    return colored_json_formatter.format(record)
                else:
                    return color_formatter.format(record)

        console_handler.setFormatter(ConsoleLevelAwareFormatter())
        logger.addHandler(console_handler)

        # File handler for specific logger (if specified)
        if config.LOG_FILE:
            try:
                file_handler = logging.handlers.RotatingFileHandler(
                    config.LOG_FILE,
                    mode='a',
                    maxBytes=config.MAX_LOG_SIZE_MB * 1024 * 1024,
                    backupCount=config.BACKUP_COUNT,
                    encoding='utf-8'
                )

                # For files, use JSON for errors and normal format for others
                class FileLevelAwareFormatter(logging.Formatter):
                    def format(self, record):
                        if record.levelno >= logging.ERROR:
                            return json_formatter.format(record)
                        else:
                            return normal_formatter.format(record)

                file_handler.setFormatter(FileLevelAwareFormatter())
                logger.addHandler(file_handler)
            except Exception as e:
                print(f"⚠️  Error: Could not set up file logging: {e}")
                logger.warning(f"File logging disabled due to error: {e}")

        # Add complete log handler (shared across all loggers)
        if self._complete_log_handler is None:
            try:
                # Get project root
                project_root = self._get_project_root(config)
                complete_log_path = project_root / "logs" / "complete_log.log"

                # Ensure directory exists
                os.makedirs(complete_log_path.parent, exist_ok=True)

                self._complete_log_handler = logging.handlers.RotatingFileHandler(
                    complete_log_path,
                    mode='a',
                    maxBytes=config.MAX_LOG_SIZE_MB * 1024 * 1024,
                    backupCount=config.BACKUP_COUNT,
                    encoding='utf-8'
                )

                # For complete log, use JSON for errors and normal format for others
                class CompleteLogLevelAwareFormatter(logging.Formatter):
                    def format(self, record):
                        if record.levelno >= logging.ERROR:
                            return json_formatter.format(record)
                        else:
                            return normal_formatter.format(record)

                self._complete_log_handler.setFormatter(CompleteLogLevelAwareFormatter())
            except Exception as e:
                print(f"⚠️  Error: Could not set up complete log: {e}")
                # Don't add handler if it fails

        # Add complete log handler if it was successfully created
        if self._complete_log_handler:
            logger.addHandler(self._complete_log_handler)

        # Add severity-specific handlers
        for handler in self._severity_handlers.values():
            logger.addHandler(handler)

        # Store in registry
        self._logger_instances[logger_name] = logger

        return logger

    def close_logger(self, logger_name: str = None):
        """Close and clean up logger handlers"""
        if logger_name:
            # Close specific logger
            if logger_name in self._logger_instances:
                logger = self._logger_instances[logger_name]
                for handler in logger.handlers[:]:  # Copy list to avoid modification during iteration
                    handler.close()
                    logger.removeHandler(handler)
                del self._logger_instances[logger_name]
        else:
            # Close all loggers
            for name, logger in list(self._logger_instances.items()):
                for handler in logger.handlers[:]:
                    handler.close()
                    logger.removeHandler(handler)
            self._logger_instances.clear()

            # Close shared handlers
            if self._complete_log_handler:
                self._complete_log_handler.close()
                self._complete_log_handler = None

            for handler in self._severity_handlers.values():
                handler.close()
            self._severity_handlers.clear()

    def close_all_loggers(self):
        """Close all loggers and handlers - alias for close_logger()"""
        self.close_logger()

    def list_loggers(self):
        """Return list of active logger names"""
        return list(self._logger_instances.keys())

    def _get_caller_class_name(self) -> str:
        """Automatically detect the calling class name using inspect"""
        try:

            # Get the call stack
            frame = inspect.currentframe()
            # Go back 2 frames: 1 for create_logger, 1 for the caller
            for i in range(2):
                if frame:
                    frame = frame.f_back


            if frame:

                # Check if we're in the main module
                module_name = frame.f_globals.get('__name__', '')

                if module_name == '__main__' :

                    return 'main'

                # Look for class context
                if 'self' in frame.f_locals:
                    return frame.f_locals['self'].__class__.__name__
                elif 'cls' in frame.f_locals:
                    return frame.f_locals['cls'].__name__

                # Return the function name as fallback

                return frame.f_code.co_name

        except Exception:
            pass

        return "main"

    def create_logger(self, logging_level: str = "DEBUG", **kwargs):
        """Factory function to create logger with customizable options"""
        # Automatically detect class name
        class_instance = self._get_caller_class_name()


        config_kwargs = {
            'LOG_LEVEL': logging_level,
            'LOG_FILE': f"logs/{class_instance}.log",
            'ENABLE_SEVERITY_FILES': True,
            'SEVERITY_FILES_DIR': "logs/severity"
        }

        # Add project root if specified
        if self._project_root:
            config_kwargs['PROJECT_ROOT'] = self._project_root

        config_kwargs.update(kwargs)

        logger_config = LoggerConfig(**config_kwargs)
        return self.setup_logger(config=logger_config, logger_name=class_instance)


# Example usage with main.py integration
if __name__ == '__main__':
    #Future will make as
    # Method 1: Auto-detect project root (goes up 3 levels from src/logger.py)
    logger_manager = Logger()



    # Example usage
    client_logger_config = LoggerConfig(
        LOG_LEVEL="DEBUG",
        LOG_FILE="logs/client.log",  # This will now be saved in project_root/logs/client.log
        ENABLE_SEVERITY_FILES=True,
        SEVERITY_FILES_DIR="logs/severity"
    )

    client_logger = logger_manager.setup_logger(config=client_logger_config, logger_name="client")


    class CreateErr:
        def zerodiverror(self):
            try:
                result = 10 / 0  # This will cause ZeroDivisionError
            except Exception as e:
                client_logger.exception(e)


    CreateErr().zerodiverror()
    client_logger.error('my error')
    client_logger.critical('my critical')
    client_logger.info('my info')
    client_logger.debug('my debug')

    print("Logs will be saved to:")
    print("- project_root/logs/complete_log.log")
    print("- project_root/logs/client.log")
    print("- project_root/logs/severity/error.log")
    print("- project_root/logs/severity/critical.log")