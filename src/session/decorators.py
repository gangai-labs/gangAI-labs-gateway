# File: src/session/decorators.py
"""
Auth decorators for FastAPI route handlers.
These work with FastAPI's Depends() system but provide explicit decorator syntax.
"""

from functools import wraps
from typing import Dict, Any, Callable
from fastapi import HTTPException


def check_session_owner(func: Callable) -> Callable:
    """
    Decorator to verify user owns the session being accessed.

    Usage:
        @router.get("/{session_id}")
        @check_session_owner
        async def get_session(
            session_id: str,
            current_user: Dict[str, Any] = Depends(handler.get_current_user_with_activity())
        ):
            # session ownership already verified
            pass
    """

    @wraps(func)
    async def wrapper(
            session_id: str,
            current_user: Dict[str, Any],
            *args,
            **kwargs
    ):
        if current_user["session_id"] != session_id:
            raise HTTPException(
                status_code=403,
                detail="Session access denied"
            )
        return await func(
            session_id=session_id,
            current_user=current_user,
            *args,
            **kwargs
        )

    return wrapper

def check_role(*allowed_roles: str):
    """
    Decorator factory to check user has required role.

    Usage:
        @router.delete("/admin/users/{user_id}")
        @check_role("admin")
        async def delete_user(
            user_id: str,
            current_user: Dict[str, Any] = Depends(handler.get_current_user_with_activity())
        ):
            pass

        @router.post("/moderate")
        @check_role("admin", "moderator")
        async def moderate_content(
            current_user: Dict[str, Any] = Depends(handler.get_current_user_with_activity())
        ):
            pass
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(
                *args,
                current_user: Dict[str, Any],
                **kwargs
        ):
            user_role = current_user.get("role", "user")
            if user_role not in allowed_roles:
                raise HTTPException(
                    status_code=403,
                    detail=f"Access denied. Required roles: {', '.join(allowed_roles)}"
                )
            return await func(*args, current_user=current_user, **kwargs)

        return wrapper

    return decorator

def check_admin(func: Callable) -> Callable:
    """
    Shorthand decorator for admin-only routes.

    Usage:
        @router.get("/admin/stats")
        @check_admin
        async def get_stats(
            current_user: Dict[str, Any] = Depends(handler.get_current_user_with_activity())
        ):
            pass
    """
    return check_role("admin")(func)

def check_authenticated(func: Callable) -> Callable:
    """
    Decorator that explicitly marks a route as requiring authentication.
    This is mostly for documentation/clarity since Depends() already enforces auth,
    but makes it visually clear that auth is required.

    Optional: Can add additional logging or checks here.

    Usage:
        @router.post("/logout")
        @check_authenticated
        async def logout(
            current_user: Dict[str, Any] = Depends(handler.get_current_user_with_activity())
        ):
            pass
    """

    @wraps(func)
    async def wrapper(
            *args,
            current_user: Dict[str, Any],
            **kwargs
    ):
        # Auth already enforced by Depends(), but we can add extra checks
        if not current_user or not current_user.get("user_id"):
            raise HTTPException(
                status_code=401,
                detail="Authentication required"
            )
        return await func(*args, current_user=current_user, **kwargs)

    return wrapper

def check_session_owner_or_admin(func: Callable) -> Callable:
    """
    Decorator that allows session owner OR admin to access.
    Admins can access any session.

    Usage:
        @router.get("/{session_id}")
        @check_session_owner_or_admin
        async def get_session(
            session_id: str,
            current_user: Dict[str, Any] = Depends(handler.get_current_user_with_activity())
        ):
            # owner or admin verified
            pass
    """

    @wraps(func)
    async def wrapper(
            session_id: str,
            current_user: Dict[str, Any],
            *args,
            **kwargs
    ):
        user_role = current_user.get("role", "user")
        is_owner = current_user["session_id"] == session_id
        is_admin = user_role == "admin"

        if not (is_owner or is_admin):
            raise HTTPException(
                status_code=403,
                detail="Session access denied"
            )

        return await func(
            session_id=session_id,
            current_user=current_user,
            *args,
            **kwargs
        )

    return wrapper

def check_user_id_match(func: Callable) -> Callable:
    """
    Decorator to verify user_id in path matches authenticated user.
    Useful for /users/{user_id}/profile type routes.

    Usage:
        @router.get("/users/{user_id}/profile")
        @check_user_id_match
        async def get_profile(
            user_id: str,
            current_user: Dict[str, Any] = Depends(handler.get_current_user_with_activity())
        ):
            # user_id already validated
            pass
    """

    @wraps(func)
    async def wrapper(
            user_id: str,
            current_user: Dict[str, Any],
            *args,
            **kwargs
    ):
        if current_user["user_id"] != user_id:
            raise HTTPException(
                status_code=403,
                detail="Access denied"
            )
        return await func(
            user_id=user_id,
            current_user=current_user,
            *args,
            **kwargs
        )

    return wrapper

def check_user_id_match_or_admin(func: Callable) -> Callable:
    """
    Like check_user_id_match but allows admin override.

    Usage:
        @router.put("/users/{user_id}/settings")
        @check_user_id_match_or_admin
        async def update_settings(
            user_id: str,
            current_user: Dict[str, Any] = Depends(handler.get_current_user_with_activity())
        ):
            pass
    """

    @wraps(func)
    async def wrapper(
            user_id: str,
            current_user: Dict[str, Any],
            *args,
            **kwargs
    ):
        user_role = current_user.get("role", "user")
        is_self = current_user["user_id"] == user_id
        is_admin = user_role == "admin"

        if not (is_self or is_admin):
            raise HTTPException(
                status_code=403,
                detail="Access denied"
            )

        return await func(
            user_id=user_id,
            current_user=current_user,
            *args,
            **kwargs
        )

    return wrapper