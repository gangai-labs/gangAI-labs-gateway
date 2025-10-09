# file:src/fast_api_utils/security_manager.py


from datetime import datetime, timedelta, timezone
from typing import Optional, Callable, Dict, Any
from functools import wraps
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from starlette.requests import Request



class SecurityManager:
    """
    Handles JWT creation / verification and provides two decorators:
    * require_auth  – any valid token
    * require_admin – token + role == "admin"
    Both decorators attach the OpenAPI security metadata so the docs work.
    For rate limit use claudflare or setup nginx.
    """

    def __init__(self, logger_manager: object,config):
        self.config = config
        self.logger = logger_manager.create_logger(
            logger_name="SecurityManager",
            logging_level=self.config.get("LOGGING_LEVEL", "INFO")
        )

        self.secret_key = self.config["SECRET_KEY"]
        self.algorithm = self.config.get("ALGORITHM", "HS256")
        self.access_token_expire_minutes = self.config.get("ACCESS_TOKEN_EXPIRE_MINUTES", 30)

    def create_access_token(self, data: dict, expires_delta: Optional[timedelta] = None) -> str:
        """Create JWT token"""
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(
                minutes=self.access_token_expire_minutes
            )

        to_encode.update({"exp": expire})
        return jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)

    def verify_token(self, token: str) -> Dict[str, Any]:
        """Verify JWT token with better error handling"""
        try:
            if not token or token == "undefined" or token == "null":
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={
                        "error": "Authentication required",
                        "detail": "Token is missing or invalid"
                    }
                )

            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            return payload

        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error": "Token expired",
                    "detail": "Your token has expired. Please login again."
                }
            )
        except jwt.JWTClaimsError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error": "Invalid token claims",
                    "detail": "Token claims are invalid"
                }
            )
        except jwt.JWTError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error": "Invalid token",
                    "detail": "Token verification failed"
                }
            )

    async def get_current_user(self, token: str = Depends(OAuth2PasswordBearer(tokenUrl="auth/token"))) -> Dict[
        str, Any]:
        """Get current user from token with better error handling"""
        try:
            payload = self.verify_token(token)
            username: str = payload.get("sub")
            role: str = payload.get("role", "user")

            if not username:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={
                        "error": "Invalid token",
                        "detail": "Username not found in token"
                    }
                )

            return {"username": username, "role": role, "user_id": username}

        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error in get_current_user: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "error": "Authentication failed",
                    "detail": "Internal server error during authentication"
                }
            )

    def require_auth(self, func: Callable) -> Callable:
        """
        Authentication decorator: Requires a valid JWT in Authorization: Bearer <token>.
        - Verifies token and sets request.state.current_user = {'username': ..., 'role': ..., 'user_id': ...}
        - Integrates with OpenAPI (adds security scheme to /docs).
        - Usage: @security_manager.require_auth on your route function.
        """
        @wraps(func)  # Preserves original function's metadata (name, docstring, etc.)
        async def wrapper(
            request: Request,  # FastAPI Request object (gives access to headers)
            *args,
            **kwargs
        ):
            try:
                # Extract token from header
                auth_header = request.headers.get("Authorization")
                if not auth_header or not auth_header.startswith("Bearer "):
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail={
                            "error": "Authentication required",
                            "detail": "Missing or invalid Authorization header. Use: Bearer <token>"
                        }
                    )

                token = auth_header.replace("Bearer ", "").strip()
                if not token:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail={
                            "error": "Authentication required",
                            "detail": "Token is empty"
                        }
                    )

                # Verify token and get user (uses existing methods)
                current_user = await self.get_current_user(token)  # This calls verify_token internally [6]

                # Attach user to request state (accessible in your route via request.state.current_user)
                request.state.current_user = current_user

                # Call the original route function
                return await func(request, *args, **kwargs)

            except HTTPException:
                # Re-raise HTTP errors (e.g., 401)
                raise
            except JWTError as e:
                # Handle JWT-specific errors (e.g., expired, invalid signature)
                self.logger.warning(f"JWT error: {e}")  # Assuming you have a logger
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={
                        "error": "Invalid token",
                        "detail": "Token verification failed (expired or tampered)"
                    }
                )
            except Exception as e:
                # Catch-all for unexpected errors
                self.logger.error(f"Auth decorator error: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={
                        "error": "Authentication failed",
                        "detail": "Internal server error during authentication"
                    }
                )

        # Add OpenAPI metadata for Swagger docs (shows "Authorize" button with BearerAuth)
        wrapper.__doc__ = func.__doc__  # Preserve docstring
        wrapper._openapi_extra = getattr(func, '_openapi_extra', {})
        wrapper._openapi_extra.update({
            "security": [{"BearerAuth": []}]  # References the "BearerAuth" scheme in OpenAPI schema [5]
        })

        return wrapper



