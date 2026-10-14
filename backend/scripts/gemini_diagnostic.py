"""Explicit, isolated Gemini connectivity diagnostics.

This script is intentionally not imported by the application. Both commands make
real Gemini API requests and must only be run manually.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from typing import Any
from urllib.parse import quote

import httpx
from google import genai
from google.genai import types
from google.genai.errors import APIError

DEFAULT_MODEL = "gemini-3.5-flash-lite"
API_VERSION = "v1beta"
DEVELOPER_API_BASE_URL = "https://generativelanguage.googleapis.com"
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_ -]?key|token|credential|authorization)\b\s*[:=]\s*[^\s,;]+"
)


def _status_code(error: BaseException) -> Any:
    return getattr(error, "code", None) or getattr(error, "status_code", None)


class DiagnosticConfigurationError(RuntimeError):
    """A local configuration problem detected before making an API request."""


def _safe_local_message(error: BaseException, api_key: str = "") -> str:
    message = str(error).strip() or "No additional explanation was provided."
    if api_key:
        message = message.replace(api_key, "[REDACTED]")
    message = _SECRET_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}=[REDACTED]", message
    )
    return message[:500]


def _api_key() -> str:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise DiagnosticConfigurationError(
            "GEMINI_API_KEY is not set in this process. Run the script through "
            "Docker Compose so compose.yaml loads the root .env file."
        )
    return api_key


def _client(api_key: str) -> genai.Client:
    # Keep this explicit so model listing and generation cannot silently use
    # different API versions if a future SDK default changes.
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(api_version=API_VERSION),
    )


def generate() -> int:
    model = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
    started = time.perf_counter()
    print(f"Testing one direct generate_content call with model: {model}", flush=True)
    try:
        api_key = _api_key()
    except DiagnosticConfigurationError as error:
        print(
            f"Local configuration error: {_safe_local_message(error)}", file=sys.stderr
        )
        return 2

    try:
        client = _client(api_key)
    except Exception as error:
        print(
            "Local client initialization error: "
            f"type={type(error).__name__} explanation={_safe_local_message(error, api_key)}",
            file=sys.stderr,
        )
        return 2

    try:
        response = client.models.generate_content(
            model=model,
            contents="Reply with exactly: OK",
            config=types.GenerateContentConfig(
                temperature=0,
                max_output_tokens=8,
            ),
        )
    except APIError as error:
        print(
            "Gemini provider error: "
            f"type={type(error).__name__} status={_status_code(error)} "
            f"explanation={_safe_local_message(error, api_key)} "
            f"duration_s={time.perf_counter() - started:.3f}",
            file=sys.stderr,
        )
        return 1
    except (httpx.TimeoutException, httpx.TransportError) as error:
        print(
            "Network/transport error before a Gemini response was received: "
            f"type={type(error).__name__} duration_s={time.perf_counter() - started:.3f}",
            file=sys.stderr,
        )
        return 1
    except Exception as error:
        print(
            "Local SDK runtime error while preparing or processing the request: "
            f"type={type(error).__name__} "
            f"explanation={_safe_local_message(error, api_key)} "
            f"duration_s={time.perf_counter() - started:.3f}",
            file=sys.stderr,
        )
        return 2
    finally:
        client.close()

    text = (response.text or "").strip()
    print(
        f"Diagnostic succeeded in {time.perf_counter() - started:.3f}s; "
        f"response_received={bool(text)}"
    )
    return 0


def list_models() -> int:
    configured_model = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
    print("Models visible to this API key that advertise generateContent:")
    try:
        api_key = _api_key()
        client = _client(api_key)
    except DiagnosticConfigurationError as error:
        print(
            f"Local configuration error: {_safe_local_message(error)}", file=sys.stderr
        )
        return 2
    except Exception as error:
        print(
            "Local client initialization error: "
            f"type={type(error).__name__} explanation={_safe_local_message(error)}",
            file=sys.stderr,
        )
        return 2

    try:
        visible = []
        for model in client.models.list():
            actions = set(model.supported_actions or [])
            if "generateContent" in actions:
                visible.append(model.name or "")
    except APIError as error:
        print(
            f"Gemini provider error while listing models: type={type(error).__name__} "
            f"status={_status_code(error)} "
            f"explanation={_safe_local_message(error, api_key)}",
            file=sys.stderr,
        )
        return 1
    except (httpx.TimeoutException, httpx.TransportError) as error:
        print(
            f"Network/transport error while listing models: type={type(error).__name__}",
            file=sys.stderr,
        )
        return 1
    except Exception as error:
        print(
            "Local SDK runtime error while listing models: "
            f"type={type(error).__name__} explanation={_safe_local_message(error, api_key)}",
            file=sys.stderr,
        )
        return 2
    finally:
        client.close()

    for name in sorted(visible):
        marker = (
            "  <-- configured"
            if name.removeprefix("models/") == configured_model
            else ""
        )
        print(f"- {name}{marker}")
    print(
        f"Configured model visible: {any(name.removeprefix('models/') == configured_model for name in visible)}"
    )
    return 0


def rest_generate() -> int:
    """Make the same minimal request without using the Google GenAI SDK."""
    model = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
    started = time.perf_counter()
    print(
        f"Testing one direct REST generateContent call with model: {model} "
        f"api_version={API_VERSION}",
        flush=True,
    )
    try:
        api_key = _api_key()
    except DiagnosticConfigurationError as error:
        print(
            f"Local configuration error: {_safe_local_message(error)}", file=sys.stderr
        )
        return 2

    encoded_model = quote(model.removeprefix("models/"), safe="-._")
    url = (
        f"{DEVELOPER_API_BASE_URL}/{API_VERSION}/models/"
        f"{encoded_model}:generateContent"
    )
    try:
        response = httpx.post(
            url,
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": "Reply with exactly: OK"}]}],
                "generationConfig": {"temperature": 0, "maxOutputTokens": 8},
            },
            timeout=60,
        )
    except (httpx.TimeoutException, httpx.TransportError) as error:
        print(
            "REST network/transport error: "
            f"type={type(error).__name__} duration_s={time.perf_counter() - started:.3f}",
            file=sys.stderr,
        )
        return 1
    except Exception as error:
        print(
            "Local REST diagnostic error: "
            f"type={type(error).__name__} explanation={_safe_local_message(error, api_key)}",
            file=sys.stderr,
        )
        return 2

    if not response.is_success:
        try:
            error_body = response.json().get("error", {})
            explanation = str(
                error_body.get("message") or "No provider explanation returned."
            )
            provider_status = str(error_body.get("status") or "unknown")
        except (ValueError, AttributeError):
            explanation = "The provider returned a non-JSON error response."
            provider_status = "unknown"
        print(
            "Gemini REST provider error: "
            f"http_status={response.status_code} provider_status={provider_status} "
            f"explanation={_safe_local_message(RuntimeError(explanation), api_key)} "
            f"duration_s={time.perf_counter() - started:.3f}",
            file=sys.stderr,
        )
        return 1

    print(
        f"REST diagnostic succeeded in {time.perf_counter() - started:.3f}s; "
        "response_received=True"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one explicit Gemini SDK diagnostic outside LangGraph."
    )
    parser.add_argument("command", choices=("generate", "list-models", "rest-generate"))
    args = parser.parse_args()
    if args.command == "generate":
        return generate()
    if args.command == "rest-generate":
        return rest_generate()
    return list_models()


if __name__ == "__main__":
    raise SystemExit(main())
