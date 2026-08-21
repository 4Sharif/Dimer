"""Shared HTTP transport behavior for model providers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlparse

import httpx

from dimer.providers.base import ProviderError
from dimer.safety.pii import redact_sensitive_text


MODEL_REQUEST_TIMEOUT_SECONDS = 300.0


@dataclass(frozen=True)
class ProviderRequestContext:
    provider: str
    base_url: str
    model: str

    @property
    def display_name(self) -> str:
        return {
            "lmstudio": "LM Studio",
            "ollama": "Ollama",
        }.get(self.provider, self.provider)

    def error(self, message: str) -> ProviderError:
        """Redact the complete user-facing message, including endpoint and model."""
        return ProviderError(redact_sensitive_text(message))


def _is_loopback_url(base_url: str) -> bool:
    hostname = urlparse(base_url).hostname
    if hostname == "localhost" or (hostname and hostname.endswith(".localhost")):
        return True
    if not hostname:
        return False
    try:
        return ip_address(hostname).is_loopback
    except ValueError:
        return False


def _unreachable_error(context: ProviderRequestContext) -> ProviderError:
    if _is_loopback_url(context.base_url):
        remedy = (
            "Start the local server, confirm the model is available, and check "
            f"base_url under [providers.{context.provider}], then retry."
        )
    else:
        remedy = (
            "Confirm the provider service is running and reachable, check "
            f"base_url under [providers.{context.provider}], then retry."
        )
    return context.error(
        f"Could not reach {context.display_name} at {context.base_url} for model "
        f"'{context.model}'. {remedy}"
    )


def _timeout_error(context: ProviderRequestContext) -> ProviderError:
    return context.error(
        f"{context.display_name} timed out after {MODEL_REQUEST_TIMEOUT_SECONDS:g} "
        f"seconds while calling {context.base_url} for model '{context.model}'. "
        "Check server load and model responsiveness, or choose a smaller model, "
        "then retry."
    )


def _transport_error(context: ProviderRequestContext) -> ProviderError:
    return context.error(
        f"Transport error while contacting {context.display_name} at {context.base_url} "
        f"for model '{context.model}'. Check base_url under "
        f"[providers.{context.provider}], inspect the provider server logs, and verify "
        "network or proxy settings, then retry."
    )


def _error_detail(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    error = data.get("error")
    if isinstance(error, dict):
        detail = error.get("message") or error.get("detail") or error.get("code")
    else:
        detail = error
    if not isinstance(detail, str) or not detail.strip():
        return None
    return " ".join(detail.split())[:400]


def _http_error(
    context: ProviderRequestContext,
    status_code: int,
    detail: str | None,
    request_id: str | None,
) -> ProviderError:
    model_not_found = (
        status_code == 404
        and detail is not None
        and "model" in detail.lower()
        and any(
            term in detail.lower()
            for term in ("not found", "does not exist", "unknown")
        )
    )
    if model_not_found:
        lead = (
            f"{context.display_name} rejected model '{context.model}' "
            f"(HTTP {status_code}) at {context.base_url}."
        )
    else:
        lead = (
            f"{context.display_name} request for model '{context.model}' failed "
            f"(HTTP {status_code}) at {context.base_url}."
        )
    if detail:
        lead = f"{lead} Provider message: {detail}."
    if request_id:
        lead = f"{lead} Provider request ID {request_id}."

    if model_not_found and context.provider == "ollama":
        remedy = (
            f"Run `ollama list`; if the model is absent, run "
            f"`ollama pull {context.model}`. Then update the model under "
            "[providers.ollama] or retry."
        )
    elif model_not_found and context.provider == "lmstudio":
        remedy = (
            "Confirm the model is loaded in LM Studio, then update the model under "
            "[providers.lmstudio] or retry."
        )
    elif status_code == 429:
        remedy = "Wait and retry, or review the provider's rate limit and quota."
    elif status_code in {401, 403}:
        remedy = (
            "Check the API credential and permissions configured under "
            f"[providers.{context.provider}], then retry."
        )
    elif status_code >= 500:
        remedy = "Check the provider server logs and health, then retry."
    elif status_code == 404:
        remedy = (
            f"Check base_url under [providers.{context.provider}] and confirm the "
            "endpoint supports the configured chat API, then retry."
        )
    else:
        remedy = (
            f"Check the endpoint and model under [providers.{context.provider}], "
            "then retry."
        )
    return context.error(f"{lead} {remedy}")


def invalid_response_error(
    context: ProviderRequestContext,
    problem: str,
) -> ProviderError:
    if context.provider == "ollama":
        remedy = (
            "Confirm the Ollama server is current and the configured model is "
            "available, then retry."
        )
    else:
        remedy = (
            "Confirm the endpoint implements OpenAI-compatible Chat Completions and "
            "the configured model is loaded, then retry."
        )
    return context.error(
        f"{context.display_name} returned an invalid response from {context.base_url} "
        f"for model '{context.model}'. {problem} {remedy}"
    )


def malformed_tool_arguments_error(
    context: ProviderRequestContext,
    tool_name: str,
) -> ProviderError:
    return context.error(
        f"{context.display_name} returned malformed tool arguments for '{tool_name}' "
        f"from {context.base_url} using model '{context.model}'. Retry once; if this "
        'model does not reliably support native tool calls, set tool_protocol = "json" '
        "for this provider/model pair."
    )


def decode_tool_function(
    tool_call_data: Any,
    context: ProviderRequestContext,
) -> tuple[str, dict[str, Any]]:
    """Validate and decode one provider-native function call."""
    if not isinstance(tool_call_data, dict):
        raise invalid_response_error(
            context,
            "Response did not match the expected response schema.",
        )
    function_data = tool_call_data.get("function")
    if not isinstance(function_data, dict):
        raise invalid_response_error(
            context,
            "Response did not match the expected response schema.",
        )
    tool_name = function_data.get("name")
    if not isinstance(tool_name, str) or not tool_name.strip():
        raise invalid_response_error(
            context,
            "Response did not match the expected response schema.",
        )
    arguments = function_data.get("arguments", {})
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise malformed_tool_arguments_error(context, tool_name) from exc
    if not isinstance(arguments, dict):
        raise malformed_tool_arguments_error(context, tool_name)
    return tool_name, arguments


def post_provider_json(
    *,
    context: ProviderRequestContext,
    path: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> tuple[dict[str, Any], str | None]:
    """POST one provider request and normalize transport-level failures."""
    endpoint = f"{context.base_url}{path}"
    with httpx.Client(
        timeout=MODEL_REQUEST_TIMEOUT_SECONDS,
        transport=transport,
    ) as client:
        try:
            response = client.post(endpoint, headers=headers, json=payload)
        except httpx.ConnectError as exc:
            raise _unreachable_error(context) from exc
        except httpx.TimeoutException as exc:
            raise _timeout_error(context) from exc
        except httpx.RequestError as exc:
            raise _transport_error(context) from exc

    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        try:
            detail = _error_detail(response.json())
        except ValueError:
            detail = None
        raise _http_error(
            context,
            response.status_code,
            detail,
            response.headers.get("x-request-id"),
        ) from exc

    try:
        data = response.json()
    except json.JSONDecodeError as exc:
        raise invalid_response_error(
            context,
            "Response body was not valid JSON.",
        ) from exc
    if not isinstance(data, dict):
        raise invalid_response_error(
            context,
            "Response did not match the expected response schema.",
        )
    return data, response.headers.get("x-request-id")
