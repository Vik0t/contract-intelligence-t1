"""NuExtract3 extraction through the public Hugging Face Gradio Space.

This backend is intentionally separate from the local CUDA backend.  The Space
is useful for experiments and model comparison, but it is not a production
SLA: it may sleep, queue requests, rate-limit callers, or change its API.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
import json
import re
import time
from typing import Any

from gradio_client import Client

from src.document_ir import DocumentIR
from src.extraction.validation import validate_model_result
from src.local_extraction import (
    CONTRACT_TEMPLATE,
    INSTRUCTIONS,
    parse_json_output,
    postprocess_extraction,
    validate_extraction,
)

DEFAULT_SPACE_ID = "numind/NuExtract3"
DEFAULT_API_NAME = "/on_extract_click"

COMPACT_INSTRUCTIONS = """
Извлеки поля из основного русскоязычного договора и верни только JSON по шаблону.
Ничего не выдумывай: если значение не найдено, используй null или пустой список.
Не путай основной договор с приложениями, счетами и письмами.
contract_type выбирай только из списка в шаблоне по заголовку и предмету договора.
term — дата окончания срока договора, возврата займа или периода услуг; игнорируй даты
оплаты, платежей, гарантии, уведомлений и претензий. Для каждого значения evidence —
короткая дословная цитата, page_number — номер страницы после метки PAGE N.
""".strip()


def build_retrieved_context(text: str, max_chars: int = 3000) -> str:
    """Keep high-value page fragments under the public Space context limit.

    The public Space reserves most of its 18k context for a hard-coded
    15k-token output budget. This selector therefore spends the small remaining
    input budget on the title/parties, term, identifiers, amount and VAT cues.
    """
    if max_chars < 1:
        return ""

    page_markers = list(re.finditer(r"PAGE\s+\d+", text, re.IGNORECASE))

    def marker_before(position: int) -> str:
        markers = [item for item in page_markers if item.start() <= position]
        return markers[-1].group(0) if markers else ""

    def make_fragment(match: re.Match[str], before: int, after: int) -> str:
        start = max(0, match.start() - before)
        end = min(len(text), match.end() + after)
        marker = marker_before(match.start())
        return f"{marker}\n{text[start:end]}".strip()

    candidates: list[str] = []
    first_page = re.search(r"PAGE\s+1", text, re.IGNORECASE)
    if first_page:
        next_page = re.search(r"PAGE\s+2", text[first_page.end() :], re.IGNORECASE)
        end = first_page.end() + next_page.start() if next_page else len(text)
        candidates.append(text[first_page.start() : min(end, first_page.start() + 850)])

    term_match = None
    for pattern in (
        r"срок\s+возврата",
        r"срок\s+действия",
        r"срок\s+до",
        r"действует\s+до",
        r"возврат\w*\s+сумм\w*\s+.*?до",
    ):
        term_match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if term_match:
            break
    if term_match:
        candidates.append(make_fragment(term_match, 100, 420))

    identifier_matches = list(re.finditer(r"ИНН\s*[:№]?", text, re.IGNORECASE))
    for match in identifier_matches[:2]:
        candidates.append(make_fragment(match, 110, 210))

    amount_match = re.search(
        r"(?:размер\w*|сумм\w*|стоимост\w*|цен\w*).{0,240}?(?:руб\w*|₽)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if amount_match:
        candidates.append(make_fragment(amount_match, 70, 80))

    vat_match = re.search(r"без\s+НДС|НДС|налог\w*", text, re.IGNORECASE)
    if vat_match:
        candidates.append(make_fragment(vat_match, 120, 180))

    result: list[str] = []
    seen: set[str] = set()
    total = 0
    for candidate in candidates:
        normalized = " ".join(candidate.split())
        if not normalized or normalized in seen or total >= max_chars:
            continue
        seen.add(normalized)
        remaining = max_chars - total
        result.append(candidate[:remaining])
        total += min(len(candidate), remaining)
    return "\n\n".join(result)


@dataclass(frozen=True)
class HFSpaceUsage:
    """Timing and request-size information returned by the remote backend."""

    elapsed_sec: float
    input_chars: int
    output_chars: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    reasoning_chars: int
    status_text: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "elapsed_sec": self.elapsed_sec,
            "input_chars": self.input_chars,
            "output_chars": self.output_chars,
            "estimated_input_tokens": self.estimated_input_tokens,
            "estimated_output_tokens": self.estimated_output_tokens,
            "reasoning_chars": self.reasoning_chars,
            "status_text": self.status_text,
        }


@dataclass(frozen=True)
class HFSpaceExtraction:
    """Parsed extraction plus raw Space output for experiment inspection."""

    result: dict[str, Any]
    raw_output: str
    reasoning: str | None
    usage: HFSpaceUsage


def _estimate_tokens(text: str) -> int:
    """Return a stable, dependency-free token estimate for remote requests."""
    # This is deliberately not presented as provider billing usage.  The Space
    # API does not return tokenizer counts, so words provide a transparent
    # lower-cost approximation for benchmark comparisons.
    return max(0, len(text.split()))


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _unwrap_space_output(value: Any) -> str:
    """Unwrap Gradio Markdown updates before parsing the model response."""
    if isinstance(value, dict):
        nested = value.get("value")
        return _as_text(nested if nested is not None else value)

    text = _as_text(value)
    stripped = text.strip()
    if stripped.startswith("{") and "'value'" in stripped:
        try:
            decoded = ast.literal_eval(stripped)
        except (SyntaxError, ValueError):
            decoded = None
        if isinstance(decoded, dict) and "value" in decoded:
            return _as_text(decoded["value"])
    return text


class HFSpaceNuExtractBackend:
    """Call NuExtract3 through its public Gradio Space API.

    The current Space exposes ``/on_extract_click`` with six inputs:
    instructions, NuExtract template, text, optional image, temperature and
    reasoning flag.  ``view_api()`` can be used to verify this contract if the
    Space is updated.
    """

    def __init__(
        self,
        *,
        space_id: str = DEFAULT_SPACE_ID,
        api_name: str = DEFAULT_API_NAME,
        client: Any | None = None,
        connect_timeout: float | None = 30.0,
    ) -> None:
        self.space_id = space_id
        self.api_name = api_name
        self._client = client
        self.connect_timeout = connect_timeout

    @property
    def client(self) -> Any:
        if self._client is None:
            kwargs: dict[str, Any] = {}
            if self.connect_timeout is not None:
                kwargs["httpx_kwargs"] = {"timeout": self.connect_timeout}
            self._client = Client(self.space_id, **kwargs)
        return self._client

    def view_api(self) -> Any:
        """Return the Space API description for diagnostics."""
        return self.client.view_api(return_format="dict")

    def extract_fields_from_text(
        self,
        text: str,
        document_ir: DocumentIR | None = None,
        *,
        instructions: str | None = None,
        template: dict[str, Any] = CONTRACT_TEMPLATE,
        context_image: str | None = None,
        temperature: float = 0.0,
        reasoning: bool = False,
        prompt_mode: str = "production",
        context_mode: str = "full",
        context_chars: int = 3000,
    ) -> HFSpaceExtraction:
        """Extract contract fields from text and measure the full API call.

        ``context_image`` is optional for the text-only experiment.  The Space
        accepts a filepath or public URL when image context is needed.
        """
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be a non-empty string")
        if not 0 <= temperature <= 1:
            raise ValueError("temperature must be between 0 and 1")
        if prompt_mode not in {"production", "compact"}:
            raise ValueError("prompt_mode must be 'production' or 'compact'")
        if context_mode not in {"full", "retrieved"}:
            raise ValueError("context_mode must be 'full' or 'retrieved'")
        if context_chars < 1:
            raise ValueError("context_chars must be positive")

        instructions = instructions or (
            INSTRUCTIONS if prompt_mode == "production" else COMPACT_INSTRUCTIONS
        )
        template_text = json.dumps(template, ensure_ascii=False, indent=2)
        request_text = (
            text
            if context_mode == "full"
            else build_retrieved_context(text, max_chars=context_chars)
        )
        prompt_text = instructions + "\n" + template_text + "\n" + request_text
        started = time.perf_counter()
        response = self.client.predict(
            instructions,
            template_text,
            request_text,
            context_image,
            temperature,
            reasoning,
            api_name=self.api_name,
        )
        elapsed = time.perf_counter() - started

        if not isinstance(response, (list, tuple)) or len(response) < 2:
            raise ValueError(
                "NuExtract3 Space returned an unexpected response: "
                f"{type(response).__name__}"
            )

        reasoning_text = _as_text(response[0]).strip() or None
        raw_output = _unwrap_space_output(response[1]).strip()
        status_text = (
            _unwrap_space_output(response[2]).strip() or None
            if len(response) > 2
            else None
        )

        if not raw_output:
            diagnostic = {
                "reasoning": (reasoning_text or "")[:2000],
                "status": (status_text or "")[:8000],
                "response_type": type(response).__name__,
                "response_length": len(response),
            }
            raise ValueError(
                "NuExtract3 Space returned an empty output: "
                + json.dumps(diagnostic, ensure_ascii=False)
            )

        try:
            parsed = parse_json_output(raw_output)
        except Exception as exc:
            raise ValueError(
                "NuExtract3 Space returned invalid or incomplete JSON"
            ) from exc
        if not isinstance(parsed, dict):
            raise ValueError("NuExtract3 Space returned JSON, but not an object")

        parsed = postprocess_extraction(parsed, text)
        if document_ir is not None:
            parsed = validate_extraction(parsed, document_ir)
        parsed = validate_model_result(parsed, text)
        parsed['_provenance'] = {'model': None, 'model_runtime': 'huggingface-space',
                                 'model_revision': None, 'model_revision_source': 'unknown',
                                 'space_id': self.space_id, 'api_name': self.api_name,
                                 'instructions': instructions, 'template': template, 'prompts': [prompt_text],
                                 'parameters': {'temperature': temperature, 'reasoning': reasoning,
                                                'prompt_mode': prompt_mode, 'context_mode': context_mode, 'context_chars': context_chars}}

        usage = HFSpaceUsage(
            elapsed_sec=round(elapsed, 3),
            input_chars=len(prompt_text),
            output_chars=len(raw_output),
            estimated_input_tokens=_estimate_tokens(prompt_text),
            estimated_output_tokens=_estimate_tokens(raw_output),
            reasoning_chars=len(reasoning_text or ""),
            status_text=status_text,
        )
        return HFSpaceExtraction(
            result=parsed,
            raw_output=raw_output,
            reasoning=reasoning_text,
            usage=usage,
        )
