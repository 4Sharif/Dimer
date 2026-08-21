"""Provider diagnostics shared by command-line interfaces."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from dimer.config import (
    DataLocality,
    DimerConfig,
    ToolProtocol,
    get_provider_config,
    provider_data_locality,
    provider_tool_protocol,
)
from dimer.providers.base import (
    ModelMessage,
    ModelProvider,
    ToolSchema,
    create_provider,
    parse_json_tool_response,
    tool_result_message,
)
from dimer.safety.pii import redact_sensitive_text


CheckStatus = Literal["pass", "fail", "not checked"]

_PROBE_VALUE = "DIMER_DOCTOR_PROBE"
_PROBE_RESULT = "DIMER_DOCTOR_RESULT_7F3A"
_PROBE_TOOL = ToolSchema(
    name="dimer_doctor_echo",
    description="Return the supplied diagnostic value unchanged.",
    input_schema={
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
        "additionalProperties": False,
    },
)


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: CheckStatus
    detail: str


@dataclass(frozen=True)
class DoctorReport:
    provider: str
    model: str
    endpoint: str
    data_locality: DataLocality | Literal["unknown"]
    checks: tuple[DoctorCheck, ...]

    @property
    def ok(self) -> bool:
        return all(check.status != "fail" for check in self.checks)


def _probe_prompt(tool_protocol: ToolProtocol) -> str:
    if tool_protocol == "native":
        return (
            f"Call {_PROBE_TOOL.name} exactly once with value {_PROBE_VALUE}. "
            "Do not answer directly. After its result, reply exactly with the "
            "returned value."
        )
    return (
        "Return only this JSON tool call with no prose: "
        f'{{"type":"tool_call","tool_name":"{_PROBE_TOOL.name}",'
        f'"arguments":{{"value":"{_PROBE_VALUE}"}}}}. '
        "After receiving the JSON tool result, return only "
        '{"type":"final","content":"<the returned value>"}.'
    )


def _check_tool_round_trip(
    provider: ModelProvider,
    config: DimerConfig,
    provider_name: str,
    model: str,
) -> tuple[DoctorCheck, DoctorCheck]:
    try:
        tool_protocol = provider_tool_protocol(config, provider_name, model)
        probe_messages = [
            ModelMessage(role="user", content=_probe_prompt(tool_protocol))
        ]
        tools = [_PROBE_TOOL] if tool_protocol == "native" else None
        tool_response = provider.generate(
            probe_messages,
            tools=tools,
            model=model,
            temperature=0,
        )
        executable_response = tool_response
        if tool_protocol == "json" and tool_response.content:
            recovered = parse_json_tool_response(tool_response.content)
            if recovered is not None:
                executable_response = recovered
        if len(executable_response.tool_calls) != 1:
            raise ValueError(
                "The provider did not return exactly one diagnostic tool call. "
                "Check the configured tool protocol for this model."
            )
        tool_call = executable_response.tool_calls[0]
        if tool_call.name != _PROBE_TOOL.name or tool_call.arguments != {
            "value": _PROBE_VALUE
        }:
            raise ValueError(
                "The provider returned the wrong diagnostic tool name or arguments. "
                "Check the configured tool protocol for this model."
            )
    except Exception as exc:
        return (
            DoctorCheck("tool call", "fail", redact_sensitive_text(str(exc))),
            DoctorCheck(
                "tool result",
                "not checked",
                "Fix tool calling before returning a tool result.",
            ),
        )

    tool_call_check = DoctorCheck(
        "tool call",
        "pass",
        f"Provider produced the expected {tool_protocol} tool call.",
    )
    observation = {
        "type": "tool_result",
        "tool_name": _PROBE_TOOL.name,
        "success": True,
        "result": {"value": _PROBE_RESULT},
    }
    result_message = tool_result_message(tool_protocol, tool_call, observation)

    try:
        final_response = provider.generate(
            [*probe_messages, tool_response.message, result_message],
            tools=tools,
            model=model,
            temperature=0,
        )
        if final_response.tool_calls:
            raise ValueError(
                "The provider requested another tool instead of summarizing the "
                "diagnostic tool result."
            )
        if tool_protocol == "json":
            try:
                final_payload = json.loads(final_response.content or "")
            except json.JSONDecodeError as exc:
                raise ValueError(
                    "The provider did not return the required JSON final envelope."
                ) from exc
            summary_matches = final_payload == {
                "type": "final",
                "content": _PROBE_RESULT,
            }
        else:
            summary_matches = final_response.content == _PROBE_RESULT
        if not summary_matches:
            raise ValueError(
                "The provider did not summarize the diagnostic tool result. "
                f"Expected {_PROBE_RESULT}."
            )
    except Exception as exc:
        result_check = DoctorCheck(
            "tool result",
            "fail",
            redact_sensitive_text(str(exc)),
        )
    else:
        result_check = DoctorCheck(
            "tool result",
            "pass",
            "Provider accepted and summarized the diagnostic tool result.",
        )
    return tool_call_check, result_check


def run_doctor(
    config: DimerConfig,
    *,
    provider: ModelProvider | None = None,
) -> DoctorReport:
    """Check provider setup, basic completion, and one deterministic tool round trip."""
    provider_name = config.default_provider
    provider_config = get_provider_config(config, provider_name)
    model = str(provider_config.get("model", config.default_model))
    endpoint = redact_sensitive_text(
        str(provider_config.get("base_url", "not configured"))
    )
    locality: DataLocality | Literal["unknown"] = "unknown"

    try:
        locality = provider_data_locality(config, provider_name)
        selected_provider = provider or create_provider(provider_name, config)
        model = str(getattr(selected_provider, "default_model", model))
        endpoint = redact_sensitive_text(
            str(getattr(selected_provider, "base_url", endpoint))
        )
    except Exception as exc:
        return DoctorReport(
            provider=provider_name,
            model=model,
            endpoint=endpoint,
            data_locality=locality,
            checks=(
                DoctorCheck(
                    "configuration",
                    "fail",
                    redact_sensitive_text(str(exc)),
                ),
                DoctorCheck(
                    "basic completion",
                    "not checked",
                    "Fix configuration before testing the provider.",
                ),
                DoctorCheck(
                    "tool call",
                    "not checked",
                    "Fix configuration before testing tool calling.",
                ),
                DoctorCheck(
                    "tool result",
                    "not checked",
                    "Fix configuration before returning a tool result.",
                ),
            ),
        )

    checks = [
        DoctorCheck(
            "configuration",
            "pass",
            f"Selected provider '{provider_name}' and model '{model}'.",
        )
    ]
    try:
        response = selected_provider.generate(
            [
                ModelMessage(
                    role="user",
                    content="Reply with OK to confirm basic completion.",
                )
            ],
            model=model,
            temperature=0,
        )
        if not (response.content or "").strip():
            raise ValueError(
                "The provider returned no text for the basic completion. "
                "Check that the selected model is loaded and can generate text."
            )
    except Exception as exc:
        completion_passed = False
        checks.append(
            DoctorCheck(
                "basic completion",
                "fail",
                redact_sensitive_text(str(exc)),
            )
        )
    else:
        completion_passed = True
        checks.append(
            DoctorCheck(
                "basic completion",
                "pass",
                "Provider reachable; selected model returned a completion.",
            )
        )
    if not completion_passed:
        checks.extend(
            (
                DoctorCheck(
                    "tool call",
                    "not checked",
                    "Fix basic completion before testing tool calling.",
                ),
                DoctorCheck(
                    "tool result",
                    "not checked",
                    "Fix basic completion before returning a tool result.",
                ),
            )
        )
    else:
        checks.extend(
            _check_tool_round_trip(
                selected_provider,
                config,
                provider_name,
                model,
            )
        )
    return DoctorReport(
        provider=provider_name,
        model=model,
        endpoint=endpoint,
        data_locality=locality,
        checks=tuple(checks),
    )
