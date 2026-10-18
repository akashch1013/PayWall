"""RFC 9457 problem details, produced by PayWall's own route class.

``ProblemRoute`` wraps every PayWall endpoint, so a host app that mounts the router gets
problem+json errors, request ids and access logs without registering any exception handler or
middleware of its own (and without PayWall touching the host's other routes).
"""

import logging
import re
import time
import uuid
from collections import defaultdict
from collections.abc import Callable, Coroutine
from http import HTTPStatus
from typing import Any

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException

from paywall.errors import ErrorCode, PayWallError
from paywall.observability import request_id_var

logger = logging.getLogger("paywall.api")

PROBLEM_MEDIA_TYPE = "application/problem+json"
REQUEST_ID_HEADER = "X-Request-ID"
# Incoming ids are echoed into logs and headers, so only a conservative charset is accepted.
_VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")


def problem_body(code: ErrorCode, detail: str, **extensions: Any) -> dict[str, Any]:
    return {
        "type": f"urn:paywall:error:{code.value.lower()}",
        "title": code.summary,
        "status": code.status,
        "detail": detail,
        "code": code.value,
        "request_id": request_id_var.get(),
        **extensions,
    }


def problem_response(code: ErrorCode, detail: str, **extensions: Any) -> JSONResponse:
    return JSONResponse(
        problem_body(code, detail, **extensions),
        status_code=code.status,
        media_type=PROBLEM_MEDIA_TYPE,
    )


def _validation_problem(error: RequestValidationError) -> JSONResponse:
    # Only location, message and type: echoing the rejected input could leak secrets into logs.
    issues = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in error.errors()]
    return problem_response(ErrorCode.VALIDATION_ERROR, "The request is invalid.", errors=issues)


class ProblemRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def handle(request: Request) -> Response:
            incoming = request.headers.get(REQUEST_ID_HEADER, "")
            request_id = (
                incoming if _VALID_REQUEST_ID.fullmatch(incoming) else f"req_{uuid.uuid4().hex}"
            )
            # Also kept on the request, for error handlers that run after this route returns.
            request.state.request_id = request_id
            token = request_id_var.set(request_id)
            started = time.perf_counter()
            log = {"method": request.method, "path": request.url.path}
            status = 500
            try:
                try:
                    response = await handler(request)
                except PayWallError as error:
                    response = problem_response(error.code, error.detail)
                except RequestValidationError as error:
                    response = _validation_problem(error)
                except HTTPException as error:
                    # Raised by the host's own auth (or by FastAPI itself): the host's handlers
                    # render it in the host's format; PayWall only adds its request id.
                    status = error.status_code
                    error.headers = {**(error.headers or {}), REQUEST_ID_HEADER: request_id}
                    raise
                except Exception:
                    logger.exception("unhandled error", extra=log)
                    raise
                status = response.status_code
                response.headers[REQUEST_ID_HEADER] = request_id
                return response
            finally:
                logger.info(
                    "%s %s %s",
                    request.method,
                    request.url.path,
                    status,
                    extra={
                        **log,
                        "status": status,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    },
                )
                request_id_var.reset(token)

        return handle


# Every PayWall route requires a credential, so all of them can answer with these.
AUTH_ERRORS = (ErrorCode.UNAUTHORIZED, ErrorCode.FORBIDDEN)

PROBLEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["type", "title", "status", "detail", "code", "request_id"],
    "properties": {
        "type": {"type": "string", "description": "urn:paywall:error:<code>"},
        "title": {"type": "string"},
        "status": {"type": "integer"},
        "detail": {"type": "string"},
        "code": {"type": "string", "enum": [c.value for c in ErrorCode]},
        "request_id": {"type": "string"},
        "errors": {
            "type": "array",
            "description": "Only for VALIDATION_ERROR: which inputs were rejected and why.",
            "items": {"type": "object"},
        },
    },
}


def problem_responses(*codes: ErrorCode) -> dict[int | str, dict[str, Any]]:
    """OpenAPI ``responses`` for a route: one entry per status, listing the codes it can return.

    VALIDATION_ERROR is always included; it also replaces FastAPI's default 422 schema, which
    does not match what PayWall actually returns.
    """
    by_status: dict[int, list[ErrorCode]] = defaultdict(list)
    for code in dict.fromkeys((*codes, ErrorCode.VALIDATION_ERROR)):  # dedupe, keep order
        by_status[code.status].append(code)
    return {
        status: {
            "description": f"{HTTPStatus(status).phrase}: {', '.join(codes)}",
            "content": {
                PROBLEM_MEDIA_TYPE: {
                    "schema": PROBLEM_SCHEMA,
                    "examples": {
                        code.value: {
                            "value": problem_body(code, code.summary) | {"request_id": "req_…"}
                        }
                        for code in codes
                    },
                }
            },
        }
        for status, codes in sorted(by_status.items())
    }
