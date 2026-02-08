import functools
from datetime import datetime

DEBUG = True

def log_entry(func):
    """
    日志装饰器
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if DEBUG:
            print(f"    [{datetime.now()}] Entering {func.__name__}")
        result = func(*args, **kwargs)
        if DEBUG:
            print(f"    [{datetime.now()}] Exiting {func.__name__}")
        return result
    return wrapper