"""Auditable stdlib-only OpenAI Responses transport for the frozen receiver.

No call occurs at import or construction time.  The caller must explicitly
inject this object into ``ControlledReceiverHarness`` after a separate audit and
authorization.  Provider response bodies and credentials are never included in
exceptions or returned evidence.
"""

from __future__ import annotations

import base64
import json
import socket
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping

from glee_eval.experiments.controlled_receiver import (
    ReceiverContract,
    TransportResult,
    Usage,
    canonical_json_bytes,
)


OPENAI_RESPONSES_ENDPOINT = "https://api.openai.com/v1/responses"
FROZEN_MODEL = "gpt-4.1-2025-04-14"
INPUT_MICROUSD_PER_TOKEN = 2
OUTPUT_MICROUSD_PER_TOKEN = 8
ADAPTER_SCHEMA = "glee.research.openai_responses_adapter.gpt41.v1"
MAX_BILLABLE_INPUT_TOKEN_UPPER_BOUND = 2048


class OpenAIAdapterError(RuntimeError):
    """Fail-closed provider error whose message contains no response or secret bytes."""


OpenFunction = Callable[..., Any]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def _direct_open(request: urllib.request.Request, *, timeout: float, context: ssl.SSLContext) -> Any:
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=context),
        _NoRedirect(),
    )
    return opener.open(request, timeout=timeout)


def _decode_prompt(value: str, name: str) -> str:
    try:
        return base64.b64decode(value.encode("ascii"), validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError, UnicodeEncodeError) as exc:
        raise OpenAIAdapterError(f"frozen {name} prompt is not valid UTF-8 base64") from exc


def _exact_object(value: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OpenAIAdapterError("receiver request envelope is not valid JSON") from exc
    if not isinstance(parsed, dict) or canonical_json_bytes(parsed) != value:
        raise OpenAIAdapterError("receiver request envelope is not canonical JSON")
    return parsed


def load_protected_api_key(path: str | Path, *, repository_root: str | Path) -> str:
    """Read a nonempty key from a mode-0600-style regular file outside Git."""

    key_path = Path(path).expanduser().resolve(strict=True)
    repository = Path(repository_root).resolve(strict=True)
    try:
        key_path.relative_to(repository)
    except ValueError:
        pass
    else:
        raise OpenAIAdapterError("API key file must be outside the repository")
    stat = key_path.stat()
    if not key_path.is_file() or stat.st_mode & 0o077:
        raise OpenAIAdapterError("API key file must be regular and inaccessible to group/other")
    key = key_path.read_text(encoding="utf-8").strip()
    if not key or "\n" in key or "\r" in key:
        raise OpenAIAdapterError("API key file must contain exactly one nonempty line")
    return key


class OpenAIResponsesTransport:
    """Translate frozen receiver envelopes into one strict Responses API call."""

    def __init__(
        self,
        contract: ReceiverContract,
        api_key: str,
        *,
        opener: OpenFunction | None = None,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        if (
            contract.provider != "openai"
            or contract.version != FROZEN_MODEL
            or contract.model != "gpt-4.1"
        ):
            raise OpenAIAdapterError("adapter requires the frozen GPT-4.1 receiver identity")
        if not isinstance(api_key, str) or not api_key.strip():
            raise OpenAIAdapterError("a nonempty API key is required")
        self.contract = contract
        self._api_key = api_key.strip()
        self._opener = opener or _direct_open
        self._ssl_context = ssl_context or ssl.create_default_context()

    def _provider_payload(self, outbound: Mapping[str, Any]) -> dict[str, Any]:
        identity = outbound.get("receiver_identity")
        if not isinstance(identity, Mapping) or identity.get("version") != FROZEN_MODEL:
            raise OpenAIAdapterError("receiver envelope changed the frozen provider identity")
        decoding = outbound.get("decoding_parameters")
        expected_decoding = {
            "temperature": 0,
            "top_p": 1,
            "max_output_tokens": 16,
            "response_format": "strict_json_schema",
        }
        if decoding != expected_decoding:
            raise OpenAIAdapterError("receiver envelope changed frozen decoding parameters")
        inputs = outbound.get("inputs")
        if not isinstance(inputs, Mapping):
            raise OpenAIAdapterError("receiver envelope lacks frozen input fields")
        system = _decode_prompt(str(outbound.get("system_prompt_b64") or ""), "system")
        user = _decode_prompt(str(outbound.get("user_prompt_b64") or ""), "user")
        user_payload = f"{user}\n\ninputs={canonical_json_bytes(inputs).decode('utf-8')}"
        payload = {
            "model": FROZEN_MODEL,
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": system}]},
                {"role": "user", "content": [{"type": "input_text", "text": user_payload}]},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "receiver_decision_v1",
                    "strict": True,
                    "schema": dict(self.contract.output_schema),
                }
            },
            "temperature": 0,
            "top_p": 1,
            "max_output_tokens": 16,
            "seed": int(outbound.get("seed")),
            "store": False,
        }
        if len(canonical_json_bytes(payload)) > MAX_BILLABLE_INPUT_TOKEN_UPPER_BOUND:
            raise OpenAIAdapterError(
                "provider payload exceeds the conservative pre-reservation token upper bound"
            )
        return payload

    @staticmethod
    def _output_text(response: Mapping[str, Any]) -> bytes:
        if response.get("status") != "completed":
            raise OpenAIAdapterError("Responses API result was not completed")
        texts: list[str] = []
        refusals = 0
        output = response.get("output")
        if not isinstance(output, list):
            raise OpenAIAdapterError("Responses API result lacks output items")
        for item in output:
            if not isinstance(item, Mapping) or item.get("type") != "message":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, Mapping):
                    continue
                if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                    texts.append(str(part["text"]))
                elif part.get("type") == "refusal":
                    refusals += 1
        if refusals:
            return canonical_json_bytes({"decision": "refuse"})
        if len(texts) != 1:
            raise OpenAIAdapterError("Responses API result must contain exactly one output_text")
        return texts[0].encode("utf-8")

    @staticmethod
    def _usage(response: Mapping[str, Any]) -> Usage:
        usage = response.get("usage")
        if not isinstance(usage, Mapping):
            raise OpenAIAdapterError("Responses API result lacks exact token usage")
        try:
            input_tokens = int(usage["input_tokens"])
            output_tokens = int(usage["output_tokens"])
        except (KeyError, TypeError, ValueError) as exc:
            raise OpenAIAdapterError("Responses API token usage is malformed") from exc
        if input_tokens < 0 or output_tokens < 0:
            raise OpenAIAdapterError("Responses API token usage is negative")
        return Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_microusd=(
                input_tokens * INPUT_MICROUSD_PER_TOKEN
                + output_tokens * OUTPUT_MICROUSD_PER_TOKEN
            ),
        )

    def __call__(self, outbound_bytes: bytes, timeout_seconds: float) -> TransportResult:
        outbound = _exact_object(outbound_bytes)
        if outbound.get("contract_sha256") != self.contract.sha256:
            raise OpenAIAdapterError("receiver request is bound to another contract")
        payload = canonical_json_bytes(self._provider_payload(outbound))
        request = urllib.request.Request(
            OPENAI_RESPONSES_ENDPOINT,
            data=payload,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "glee-wave5e-receiver/1",
            },
            method="POST",
        )
        started = time.monotonic()
        try:
            response = self._opener(
                request, timeout=float(timeout_seconds), context=self._ssl_context
            )
            with response:
                status = int(getattr(response, "status", response.getcode()))
                final_url = str(response.geturl())
                raw = response.read()
        except (TimeoutError, socket.timeout) as exc:
            raise TimeoutError("OpenAI Responses request timed out") from exc
        except urllib.error.HTTPError as exc:
            raise OpenAIAdapterError(f"OpenAI Responses HTTP status {int(exc.code)}") from None
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise TimeoutError("OpenAI Responses request timed out") from exc
            raise OpenAIAdapterError("OpenAI Responses transport failed") from None
        except OSError:
            raise OpenAIAdapterError("OpenAI Responses transport failed") from None
        elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
        if status != 200:
            raise OpenAIAdapterError(f"OpenAI Responses HTTP status {status}")
        if final_url != OPENAI_RESPONSES_ENDPOINT:
            raise OpenAIAdapterError("OpenAI Responses request was redirected")
        try:
            document = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OpenAIAdapterError("OpenAI Responses result is not valid JSON") from exc
        if not isinstance(document, Mapping):
            raise OpenAIAdapterError("OpenAI Responses result is not an object")
        returned_model = str(document.get("model") or "")
        if returned_model != FROZEN_MODEL:
            raise OpenAIAdapterError("OpenAI Responses result reports another model snapshot")
        return TransportResult(
            response_bytes=self._output_text(document),
            usage=self._usage(document),
            elapsed_ms=elapsed_ms,
            consumed_fields=(self.contract.candidate_text_field,),
        )


__all__ = [
    "ADAPTER_SCHEMA",
    "FROZEN_MODEL",
    "INPUT_MICROUSD_PER_TOKEN",
    "MAX_BILLABLE_INPUT_TOKEN_UPPER_BOUND",
    "OPENAI_RESPONSES_ENDPOINT",
    "OUTPUT_MICROUSD_PER_TOKEN",
    "OpenAIAdapterError",
    "OpenAIResponsesTransport",
    "load_protected_api_key",
]
