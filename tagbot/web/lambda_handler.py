"""AWS Lambda handler that adapts API Gateway REST events to Flask/WSGI."""
import io
import sys
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

from tagbot.web import app


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Translate an API Gateway REST event into a WSGI request."""
    body = (event.get("body") or "").encode("utf-8")
    environ: Dict[str, Any] = {
        "REQUEST_METHOD": event["httpMethod"],
        "SCRIPT_NAME": "",
        "PATH_INFO": event.get("path", "/"),
        "QUERY_STRING": urlencode(event.get("queryStringParameters") or {}),
        "CONTENT_LENGTH": str(len(body)),
        "SERVER_NAME": "lambda",
        "SERVER_PORT": "443",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "wsgi.version": (1, 0),
        "wsgi.url_scheme": "https",
        "wsgi.input": io.BytesIO(body),
        "wsgi.errors": sys.stderr,
        "wsgi.multithread": False,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
        "context": context,
    }
    for key, value in (event.get("headers") or {}).items():
        wsgi_key = key.upper().replace("-", "_")
        if wsgi_key == "CONTENT_TYPE":
            environ["CONTENT_TYPE"] = value
        elif wsgi_key == "CONTENT_LENGTH":
            environ["CONTENT_LENGTH"] = value
        else:
            environ[f"HTTP_{wsgi_key}"] = value

    status_ref: List[str] = []
    headers_ref: List[List[Tuple[str, str]]] = []

    def start_response(
        status: str,
        response_headers: List[Tuple[str, str]],
        exc_info: Optional[Any] = None,
    ) -> None:
        status_ref.append(status)
        headers_ref.append(response_headers)

    result = app(environ, start_response)
    try:
        body_bytes = b"".join(result)
    finally:
        if hasattr(result, "close"):
            result.close()

    return {
        "statusCode": int(status_ref[0].split(" ", 1)[0]),
        "headers": dict(headers_ref[0]),
        "body": body_bytes.decode("utf-8"),
    }
