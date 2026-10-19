"""HTTP 只监听本机；页面与接口同源，不开放整个项目目录。"""

import threading
import time
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__, application_root, asset_root, project_instance
from .discovery import discover_devices
from .models import ConnectionInput, DeviceFailure, EmptyInput, StatePatch, TimerInput
from .service import DeviceService
from .settings import SettingsStore

PROJECT = asset_root()
RUNTIME = application_root()


def create_app(service: DeviceService | None = None, *, poll: bool = True, discover=discover_devices) -> FastAPI:
    service = service or DeviceService(
        SettingsStore(RUNTIME / ".local" / "device.json"),
        timer_path=RUNTIME / ".local" / "timer.json",
    )

    @asynccontextmanager
    async def lifespan(app):
        if poll:
            service.start()
        try:
            yield
        finally:
            if poll:
                service.stop()

    app = FastAPI(title="AIRA", version=__version__, docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
    app.state.device_service = service
    app.state.shutdown_callback = None
    discovery_lock = threading.Lock()
    last_discovery = -float("inf")

    @app.middleware("http")
    async def local_requests(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            if (origin and origin != str(request.base_url).rstrip("/")) or request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"error": {"code": "origin_denied", "message": "请从本机页面操作"}}, status_code=403)
            if request.method in ("POST", "PATCH", "DELETE"):
                if request.headers.get("x-aira-request") != "1":
                    return JSONResponse({"error": {"code": "request_denied", "message": "请求来源无法验证"}}, status_code=403)
                if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
                    return JSONResponse({"error": {"code": "json_required", "message": "请使用 JSON 请求"}}, status_code=415)
                try:
                    length = int(request.headers.get("content-length", "-1"))
                except ValueError:
                    length = -1
                if not 0 <= length <= 8192:
                    return JSONResponse({"error": {"code": "invalid_size", "message": "请求大小不正确"}}, status_code=413)
                if request.headers.get("transfer-encoding"):
                    return JSONResponse({"error": {"code": "invalid_size", "message": "不支持此请求传输方式"}}, status_code=400)
                body = await request.body()
                if len(body) > 8192:
                    return JSONResponse({"error": {"code": "invalid_size", "message": "请求大小不正确"}}, status_code=413)
                if len(body) != length:
                    return JSONResponse({"error": {"code": "invalid_size", "message": "请求长度不一致"}}, status_code=400)
        response = await call_next(request)
        response.headers.update({
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        })
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        # FastAPI 默认错误包含 input；连接 Token 不应在验证错误中回显。
        return JSONResponse({"error": {"code": "invalid_input", "message": "参数无效，请检查温度范围、控制项或连接信息"}}, status_code=422)

    @app.exception_handler(DeviceFailure)
    async def device_failure(request, error):
        return JSONResponse({"error": {"code": error.code, "message": error.message}, "snapshot": service.snapshot()}, status_code=error.status)

    @app.exception_handler(Exception)
    async def unexpected_error(request, error):
        return JSONResponse({"error": {"code": "internal_error", "message": "服务暂时无法完成请求"}}, status_code=500)

    @app.get("/api/health")
    def health():
        return {"ok": True, "service": "aira", "version": __version__, "instance": project_instance(RUNTIME)}

    @app.get("/api/status")
    def status():
        return service.snapshot()

    @app.post("/api/refresh")
    def refresh(body: EmptyInput):
        return service.refresh()

    @app.get("/api/timer")
    def timer():
        return service.snapshot()

    @app.post("/api/timer")
    def set_timer(body: TimerInput):
        return service.set_timer(body.action, body.due)

    @app.delete("/api/timer")
    def clear_timer(body: EmptyInput):
        return service.clear_timer()

    @app.post("/api/device")
    def configure(body: ConnectionInput):
        return service.configure(body)

    @app.patch("/api/state")
    def control(body: StatePatch):
        return service.control(body)

    @app.post("/api/discover")
    def discover_network(body: EmptyInput):
        nonlocal last_discovery
        if not discovery_lock.acquire(blocking=False):
            raise DeviceFailure("discovery_busy", "正在查找设备，请稍候", 429)
        try:
            if time.monotonic() - last_discovery < 8:
                raise DeviceFailure("discovery_rate_limit", "请稍候再查找", 429)
            last_discovery = time.monotonic()
            try:
                return {"devices": discover()}
            except OSError:
                raise DeviceFailure("discovery_failed", "查找失败，可在路由器的设备列表中查看 IP", 503) from None
        finally:
            discovery_lock.release()

    @app.post("/api/shutdown")
    def shutdown(body: EmptyInput, background: BackgroundTasks):
        if app.state.shutdown_callback is None:
            raise DeviceFailure("shutdown_unavailable", "请在启动服务的进程中停止", 409)
        background.add_task(app.state.shutdown_callback)
        return {"stopping": True}

    @app.get("/")
    def index():
        return FileResponse(PROJECT / "index.html")

    @app.get("/setup")
    def setup():
        return FileResponse(PROJECT / "setup.html")

    @app.get("/setup.js")
    def setup_script():
        return FileResponse(PROJECT / "setup.js", media_type="text/javascript")

    @app.get("/setup.css")
    def setup_styles():
        return FileResponse(PROJECT / "setup.css", media_type="text/css")

    @app.get("/desktop.js")
    def desktop_script():
        return FileResponse(PROJECT / "desktop.js", media_type="text/javascript")

    @app.get("/desktop.css")
    def desktop_styles():
        return FileResponse(PROJECT / "desktop.css", media_type="text/css")

    @app.get("/floating.js")
    def floating_script():
        return FileResponse(PROJECT / "floating.js", media_type="text/javascript")

    @app.get("/floating.css")
    def floating_styles():
        return FileResponse(PROJECT / "floating.css", media_type="text/css")

    @app.get("/favicon.ico")
    def favicon():
        return FileResponse(PROJECT / "assets" / "空调.ico", media_type="image/x-icon")

    @app.get("/assets/inter.woff2")
    def number_font():
        return FileResponse(PROJECT / "assets" / "inter.woff2", media_type="font/woff2")

    return app
