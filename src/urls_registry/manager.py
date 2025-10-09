# src/events.py


from typing import Dict

import orjson
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from fastapi.routing import APIRoute
from pydantic import AnyHttpUrl
from starlette.responses import JSONResponse
from starlette.websockets import WebSocketState

from config import ROUTES_MANAGER_CONFIG
from utils.httpx_manager import RequestPayload
from utils.logger import Logger

from urls_registry.models import (
    ExternalAPI,
    RouteConfig,
    WSMessageConfig,
    ExternalAPIRequest,
    ExternalAPIResponse,
)

# Import auth decorators
from session.decorators import check_authenticated, check_admin


# ------------------------------------------------------------------
# Helper for auth (JWT) – the app passes an instance of SecurityManager
# ------------------------------------------------------------------
def get_current_user_dependency(security_manager):
    """FastAPI dependency that returns the decoded JWT payload."""
    return security_manager.get_current_user


# ------------------------------------------------------------------
# URLManager
# ------------------------------------------------------------------
class URLManager:
    """
    *Dynamic* routing: you can add or remove REST/WS endpoints at runtime.
    The gateway internally keeps a reference to every created route so it can be
    deleted by name (e.g. `DELETE /api/unregister?name=weather`).


    """

    def __init__(
            self,
            logger_manager: Logger,
            security_manager,
            session_manager,
            httpx_manager,
    ):
        self.logger = logger_manager.create_logger(
            logger_name="URLManager",
            logging_level=ROUTES_MANAGER_CONFIG["LOGGING_LEVEL"],
        )
        self.security_manager = security_manager
        self.session_manager = session_manager
        self.httpx_manager = httpx_manager

        # Storage for dynamic routes / handlers
        self.rest_routes: Dict[str, RouteConfig] = {}
        self.ws_handlers: Dict[str, WSMessageConfig] = {}
        self.external_apis: Dict[str, ExternalAPI] = {}

        # FastAPI router for the *dynamic* endpoints
        self.router = APIRouter(prefix="/api", tags=["Dynamic Routes"])
        # Keep a reference to the actual FastAPI route objects so we can delete them.
        self._rest_route_refs: Dict[str, APIRoute] = {}
        # Register the management endpoints
        self._setup_management_routes()

    # ------------------------------------------------------------------
    # ----------   Management endpoints  -------------------------------
    # ------------------------------------------------------------------
    def _setup_management_routes(self):
        """Expose /api/register, /api/unregister, /api/list - ALL REQUIRE AUTH."""

        @self.router.post("/register", response_model=ExternalAPIResponse)
        @check_admin  #  Requires authentication
        async def register_api(
                req: ExternalAPIRequest,
                current_user: dict = Depends(self.session_manager.get_current_user_with_activity())
        ):
            """
            Register a new external API (REST or WS).
            Requires authentication.
            """
            api_cfg = ExternalAPI(
                name=req.name,
                base_url=req.base_url,
                path=req.path,
                method=req.method,
                headers=req.headers,
                timeout=req.timeout,
                require_auth=req.require_auth,
                ws_supported=req.ws_supported,
            )
            self.register_external_api(api_cfg)
            self.logger.info(f"User {current_user['user_id']} registered API '{req.name}'")
            return ExternalAPIResponse(
                message=f"API '{req.name}' registered",
                name=req.name,
            )

        @self.router.delete("/unregister")
        @check_admin  #   Requires authentication
        async def unregister_api(
                name: str,
                current_user: dict = Depends(self.session_manager.get_current_user_with_activity())
        ):
            """
            Remove an existing external API (both REST and WS).
            Requires authentication.
            """
            if name not in self.external_apis:
                raise HTTPException(status_code=404, detail="API not found")

            # Remove from our dictionaries
            self.external_apis.pop(name)
            self.ws_handlers.pop(name, None)

            # Remove the REST route, if it exists
            self._remove_rest_route(name)

            self.logger.info(f"User {current_user['user_id']} unregistered API '{name}'")
            return {"message": f"API '{name}' removed"}

        @self.router.get("/list")
        @check_admin  #   Requires authentication
        async def list_apis(
                current_user: dict = Depends(self.session_manager.get_current_user_with_activity())
        ):
            """
            Return a list of all currently registered external APIs.
            Requires authentication.
            """
            return [
                {
                    "name": k,
                    "base_url": v.base_url,
                    "method": v.method,
                    "path": v.path,
                    "ws_supported": v.ws_supported,
                }
                for k, v in self.external_apis.items()
            ]

    # ------------------------------------------------------------------
    # ----------   Public API for other modules  ------------------------
    # ------------------------------------------------------------------
    def get_router(self) -> APIRouter:
        """Return the FastAPI router so the main app can include it."""
        return self.router

    # ------------------------------------------------------------------
    # ----------   Registration helpers -------------------------------
    # ------------------------------------------------------------------
    def register_external_api(self, api_config: ExternalAPI) -> None:
        """
        Store the config and automatically create a REST or WS proxy route.
        """
        self.external_apis[api_config.name] = api_config

        if not api_config.ws_supported:
            self._create_proxy_route(api_config)

        if api_config.ws_supported:
            self._create_ws_proxy_handler(api_config)

        self.logger.debug(f"Registered external API: {api_config.name} → {api_config.base_url}")

    # ------------------------------------------------------------------
    # ----------   Internal route creation  ----------------------------
    # ------------------------------------------------------------------
    def _create_proxy_route(self, api_config: ExternalAPI) -> None:
        """
        Create a REST proxy route:  /api/proxy/<name>
        WITH AUTH: If api_config.require_auth=True, requires authentication.
        """

        async def proxy_handler(
                request: Request,
                current_user: dict = Depends(
                    self.session_manager.get_current_user_with_activity()) if api_config.require_auth else None
        ):
            # Build the full URL
            full_url = f"{api_config.base_url.rstrip('/')}/{api_config.path.lstrip('/')}"
            body = await request.body()

            # Prepare headers
            headers = api_config.headers or {}
            if api_config.require_auth and current_user:
                # Add user context to headers
                headers["X-User-ID"] = current_user["user_id"]
                headers["X-Session-ID"] = current_user.get("session_id", "")

            try:
                # Use the shared httpx_manager instead of creating new client
                response_data = await self.httpx_manager.make_request(
                    RequestPayload(
                        url=AnyHttpUrl(full_url),
                        method=api_config.method,
                        body=body if body else None,
                        headers=headers,
                        timeout=api_config.timeout,
                        follow_redirects=True
                    )
                )

                # Handle the response from httpx_manager
                if "error" in response_data:
                    if response_data["error"] == "CIRCUIT_BREAKER_OPEN":
                        raise HTTPException(status_code=503, detail="Service temporarily unavailable")
                    else:
                        raise HTTPException(status_code=502,
                                            detail=f"External API error: {response_data.get('message', 'Unknown error')}")

                return JSONResponse(
                    content=response_data,
                    status_code=response_data.get("status_code", 200)
                )

            except HTTPException:
                raise
            except Exception as exc:
                self.logger.error(f"Proxy error for {api_config.name}: {exc}")
                raise HTTPException(status_code=500, detail="Internal proxy error")

        # Register the route
        route_path = f"/proxy/{api_config.name}"
        route_method = getattr(self.router, api_config.method.lower())

        # Apply auth decorator if required
        if api_config.require_auth:
            proxy_handler = check_authenticated(proxy_handler)

        route = route_method(
            route_path,
            summary=f"Proxy to {api_config.name}",
            description=f"Forward request to {api_config.base_url}",
            tags=["proxy"],
        )(proxy_handler)

        # Keep a reference so we can delete it later
        self._rest_route_refs[api_config.name] = route

    def _remove_rest_route(self, name: str) -> None:
        """Remove the REST proxy that was registered for `name`."""
        route = self._rest_route_refs.pop(name, None)
        if route and route in self.router.routes:
            self.router.routes.remove(route)
            self.logger.debug(f"Deleted REST route for {name}")

    # ------------------------------------------------------------------
    # ----------   WS proxy handler  ------------------------------------
    # ------------------------------------------------------------------
    def _create_ws_proxy_handler(self, api_config: ExternalAPI) -> None:
        """
        Create a WebSocket message handler that forwards data to an
        external WS-compatible endpoint using the shared httpx_manager.

        AUTH: WS messages are authenticated via the websocket connection's token.
        """

        async def ws_proxy_handler(
                user_id: str,
                session_id: str,
                websocket: WebSocket,
                message_data: dict,
        ):
            full_url = f"{api_config.base_url.rstrip('/')}/{api_config.path.lstrip('/')}"
            request_data = {
                "user_id": user_id,
                "session_id": session_id,
                "message": message_data,
            }

            try:
                # Use the shared httpx_manager instead of creating new client
                response = await self.httpx_manager.make_request(
                    RequestPayload(
                        url=AnyHttpUrl(full_url),
                        method=api_config.method,
                        body=request_data,
                        headers=api_config.headers or {},
                        timeout=api_config.timeout,
                        follow_redirects=True
                    )
                )

                # Handle response from httpx_manager
                if "error" in response:
                    if response["error"] == "CIRCUIT_BREAKER_OPEN":
                        await self._send_error(
                            websocket,
                            "External service temporarily unavailable"
                        )
                    else:
                        error_msg = response.get("message", "External API error")
                        await self._send_error(websocket, error_msg)
                else:
                    # Success - send the response back through WebSocket
                    await websocket.send_bytes(
                        orjson.dumps({
                            "type": f"{api_config.name}_response",
                            "data": response
                        })
                    )

            except Exception as exc:
                self.logger.error(f"WS proxy error for {api_config.name}: {exc}")
                await self._send_error(websocket, f"Proxy error: {str(exc)}")

        # Register the handler in the internal dict
        self.ws_handlers[api_config.name] = WSMessageConfig(
            message_type=api_config.name,
            handler=ws_proxy_handler,
            require_auth=api_config.require_auth,
            description=f"WS proxy to {api_config.name}",
            external_api=api_config,
        )

    async def _send_error(self, websocket: WebSocket, message: str) -> None:
        """Send a structured error to the WS client."""
        if websocket.client_state == WebSocketState.CONNECTED:
            try:
                await websocket.send_bytes(orjson.dumps({"type": "error", "message": message}))
            except Exception as e:
                self.logger.exception(e)