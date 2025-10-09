import asyncio
from functools import wraps



def auto_retry(max_retries: int = 3, delay: float = 1.0):
    """Decorator for retries httpx rest (e.g., on API/device errors)."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            #Extract self (first arg for instance methods) and logger for use in except
            if args:
                self_ = args[0]
                logger = getattr(self_, 'logger', None)
            else:
                self_ = None
                logger = None
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if logger:
                        logger.warning(f"Attempt {attempt + 1} failed: {str(e)}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(delay)
            if logger:
                logger.error(f"All {max_retries} attempts failed")
            raise last_exception

        return wrapper

    return decorator
