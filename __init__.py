"""Run Hermes browser tools on an isolated Cloudbrowser Chrome desktop."""

from __future__ import annotations

import json
import logging
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from agent.browser_provider import BrowserProvider
from agent.secret_scope import get_secret

API_ROOT = "https://cloudbrowser.tv/api/v1"
API_HOST = "cloudbrowser.tv"
KEY_NAME = "CLOUDBROWSER_API_KEY"
REQUEST_TIMEOUT = 10
OPERATION_TIMEOUT = 180
OPERATION_INTERVAL = 0.5
log = logging.getLogger(__name__)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class _ApiError(RuntimeError):
    def __init__(self, status: int, busy: bool = False):
        super().__init__(f"Cloudbrowser API returned HTTP {status}")
        self.status = status
        self.busy = busy


class _TransportError(RuntimeError):
    pass


def _request(key: str, method: str, path: str, *, body=None, idempotency_key=None) -> dict:
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    request = Request(
        f"{API_ROOT}{path}",
        data=None if body is None else json.dumps(body).encode(),
        headers=headers,
        method=method,
    )
    try:
        with build_opener(_NoRedirect()).open(request, timeout=REQUEST_TIMEOUT) as response:
            result = json.load(response)
    except HTTPError as error:
        try:
            busy = error.code == 409 and json.load(error).get("error", {}).get("code") == "busy"
        except (ValueError, TypeError, OSError, AttributeError):
            busy = False
        finally:
            error.close()
        raise _ApiError(error.code, busy) from None
    except (OSError, URLError):
        raise _TransportError("Could not reach the Cloudbrowser API") from None
    except ValueError:
        raise RuntimeError("The Cloudbrowser API returned invalid JSON") from None
    if not isinstance(result, dict):
        raise RuntimeError("The Cloudbrowser API returned an invalid response")
    return result


def _operation_id(operation: dict, field: str) -> str:
    value = operation.get(field)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"The Cloudbrowser operation response is missing {field}")
    return value


def _wait(key: str, operation: dict, deadline: float) -> None:
    operation_path = "/operations/" + quote(_operation_id(operation, "id"), safe="")
    while operation.get("status") in {"pending", "running"}:
        if time.monotonic() >= deadline:
            raise RuntimeError("The Cloudbrowser operation took too long")
        time.sleep(OPERATION_INTERVAL)
        operation = _request(key, "GET", operation_path)
    if operation.get("status") != "succeeded":
        raise RuntimeError("The Cloudbrowser operation failed")


def _delete(key: str, browser_id: str, *, best_effort: bool = False) -> None:
    path = "/browsers/" + quote(browser_id, safe="")
    idempotency_key = str(uuid.uuid4())
    deadline = time.monotonic() + OPERATION_TIMEOUT
    while True:
        try:
            operation = _request(key, "DELETE", path, idempotency_key=idempotency_key)
            break
        except _ApiError as error:
            if error.status == 404:
                return
            if best_effort or not error.busy or time.monotonic() >= deadline:
                raise
        except _TransportError:
            if best_effort or time.monotonic() >= deadline:
                raise
        time.sleep(OPERATION_INTERVAL)
    if not best_effort:
        _wait(key, operation, deadline)


def _cdp_url(data: dict, browser_id: str) -> str:
    value = data.get("cdpUrl")
    if isinstance(value, str):
        try:
            url = urlsplit(value)
            if (
                url.scheme == "wss"
                and url.hostname == API_HOST
                and url.port in {443, None}
                and url.username is None
                and url.password is None
                and url.path == "/connect/" + quote(browser_id, safe="")
                and "token" in parse_qs(url.query)
                and not url.fragment
            ):
                return value
        except ValueError:
            pass
    raise RuntimeError("Cloudbrowser did not supply a secure browser endpoint")


class CloudbrowserProvider(BrowserProvider):
    name = "cloudbrowser"
    display_name = "Cloudbrowser"

    def is_available(self) -> bool:
        return bool(get_secret(KEY_NAME))

    def get_setup_schema(self) -> dict:
        return {
            "name": self.display_name,
            "badge": "cloud",
            "tag": "An isolated remote Chrome desktop for each browser session",
            "env_vars": [{
                "key": KEY_NAME,
                "prompt": "Cloudbrowser API key",
                "url": "https://cloudbrowser.tv/docs/api",
            }],
        }

    def create_session(self, task_id: str) -> dict:
        key = get_secret(KEY_NAME)
        if not key:
            raise ValueError("Set CLOUDBROWSER_API_KEY using hermes tools")
        marker = str(uuid.uuid4())
        request = {"body": {"name": f"Hermes {marker}"}, "idempotency_key": marker}
        deadline = time.monotonic() + OPERATION_TIMEOUT
        try:
            operation = _request(key, "POST", "/browsers", **request)
        except _TransportError:
            operation = _request(key, "POST", "/browsers", **request)
        browser_id = _operation_id(operation, "browserId")
        try:
            _wait(key, operation, deadline)
            path = "/browsers/" + quote(browser_id, safe="") + "/grants"
            grant = _request(key, "POST", path, body={"audience": "cdp", "permission": "control"})
            url = _cdp_url(grant, browser_id)
        except RuntimeError:
            try:
                _delete(key, browser_id)
            except RuntimeError:
                log.warning("Cloudbrowser could not confirm cleanup of desktop %s", browser_id)
            raise
        return {"session_name": f"cloudbrowser-{marker}", "bb_session_id": browser_id, "cdp_url": url, "features": {}}

    def close_session(self, session_id: str) -> bool:
        key = get_secret(KEY_NAME)
        if not key:
            return False
        try:
            _delete(key, session_id)
        except RuntimeError:
            log.warning("Cloudbrowser could not confirm cleanup of desktop %s", session_id)
            return False
        return True

    def emergency_cleanup(self, session_id: str) -> None:
        key = get_secret(KEY_NAME)
        if key:
            try:
                _delete(key, session_id, best_effort=True)
            except RuntimeError:
                log.warning("Could not request emergency cleanup of Cloudbrowser desktop %s", session_id)


def register(ctx) -> None:
    ctx.register_browser_provider(CloudbrowserProvider())
