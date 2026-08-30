from __future__ import annotations

# The browser UI is served from the same loopback origin as every LocalHub API,
# thumbnail, preview and media stream. There is no legitimate external origin.
CSP = (
    "default-src 'self'; "
    "connect-src 'self'; "
    "img-src 'self' blob: data:; "
    "media-src 'self' blob:; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "font-src 'self' data:; "
    "worker-src 'none'; "
    "frame-src 'none'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "form-action 'self'"
)


def install(server_module) -> None:
    """Add a same-origin-only CSP to the final LocalHub request handler.

    The Python process already has a loopback-only socket guard. This layer
    closes the other half of the privacy contract: JavaScript running in the
    user's browser cannot fetch, stream, embed, frame, or open a WebSocket to an
    internet origin from a LocalHub page.
    """
    if getattr(server_module, "_localhub_browser_privacy_installed", False):
        return

    original_make_handler = server_module.make_handler

    def make_handler(store):
        BaseHandler = original_make_handler(store)

        class LocalOnlyBrowserHandler(BaseHandler):
            def _headers(self, status, content_type, length=None, extra=None):
                headers = dict(extra or {})
                headers.setdefault("Content-Security-Policy", CSP)
                headers.setdefault("Referrer-Policy", "no-referrer")
                headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
                headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
                return super()._headers(status, content_type, length, headers)

        return LocalOnlyBrowserHandler

    server_module.make_handler = make_handler
    server_module._localhub_browser_privacy_installed = True
