"""Database decorators module for DB access patterns."""

from functools import wraps
from typing import Callable, Any


def requires_connection(func: Callable) -> Callable:
    """Decorator to ensure DatabaseManager has an open connection.

    Raises RuntimeError if `self.conn` is falsy.
    """
    @wraps(func)
    def wrapper(self, *args: Any, **kwargs: Any) -> Any:
        if not getattr(self, 'conn', None):
            raise RuntimeError("No open database connection")
        return func(self, *args, **kwargs)

    return wrapper


def requires_repo(name: str) -> Callable:
    """Decorator to ensure a repository attribute exists.
    
    Args:
        name: Name of the repository attribute to check for
    
    Example:
        @requires_repo('interests_repo')
        def method(self):
            self.interests_repo.do_something()
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, *args: Any, **kwargs: Any) -> Any:
            repo = getattr(self, name, None)
            if not repo:
                raise RuntimeError(f"No {name} available")
            return func(self, *args, **kwargs)
        return wrapper
    return decorator