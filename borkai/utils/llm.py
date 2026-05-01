"""
Low-level LLM call helpers.
All LLM interactions in the system go through these functions.
"""
import re
import json
import time
import openai

# Hard limit on combined prompt size sent to the API (~120k chars ≈ ~30k tokens).
# Protects against runaway article content blowing up the context window.
_MAX_PROMPT_CHARS = 120_000


def _sanitize(text) -> str:
    """
    Remove characters that cause OpenAI 400/500 errors:
      - None / non-string input (converted to "")
      - null bytes
      - lone surrogates (unpaired UTF-16 surrogates from web scraping)
      - ASCII control characters (except tab \x09, newline \x0a, CR \x0d)

    Python 3.14 tightened json.dumps — lone surrogates now raise ValueError
    instead of silently producing invalid JSON.  We catch that here with a
    final JSON-safety probe and fall back to ASCII-safe encoding if needed.
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    if not text:
        return text

    # Step 1: replace lone surrogates via encode/decode round-trip
    try:
        text.encode("utf-8")          # fast path — no surrogates
    except (UnicodeEncodeError, UnicodeDecodeError):
        text = text.encode("utf-8", errors="replace").decode("utf-8", errors="replace")

    # Step 2: strip null bytes and ASCII control characters
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

    # Step 3: final JSON-safety probe (Python 3.14 strict mode)
    try:
        json.dumps(text, ensure_ascii=False)
    except (ValueError, UnicodeEncodeError):
        # Fallback: ASCII-only representation — loses non-ASCII but is always safe
        text = text.encode("ascii", errors="replace").decode("ascii")

    return text


def call_llm(
    client: openai.OpenAI,
    model: str,
    system: str,
    prompt: str,
    max_tokens: int = 4096,
    expect_json: bool = False,
) -> str:
    """
    Make a single LLM call and return the raw text response.

    When expect_json=True, uses response_format=json_object to guarantee
    valid JSON output without truncation or formatting issues.
    Note: the system or user prompt must contain the word 'json' (case-insensitive)
    when using json_object mode — all our prompts already satisfy this.

    Retries once on 500/503 (transient server errors) after a short delay.
    Sanitizes input to prevent 500s caused by malformed Unicode from web scraping.
    """
    system = _sanitize(system)
    prompt = _sanitize(prompt)

    # Hard truncate if combined content is absurdly large
    if len(system) + len(prompt) > _MAX_PROMPT_CHARS:
        allowed = _MAX_PROMPT_CHARS - len(system) - 200  # leave buffer
        if allowed > 0:
            prompt = prompt[:allowed] + "\n\n[... content truncated to fit context limit ...]"

    kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    )
    if expect_json:
        kwargs["response_format"] = {"type": "json_object"}

    last_err = None
    for attempt in range(3):
        try:
            response = client.chat.completions.create(**kwargs)
            return response.choices[0].message.content

        except openai.RateLimitError as e:
            # 429 insufficient_quota — account is out of credits, no point retrying
            if "insufficient_quota" in str(e) or "quota" in str(e).lower():
                raise RuntimeError(
                    "OpenAI quota exceeded: your account has no remaining credits.\n"
                    "Add credits at https://platform.openai.com/settings/billing"
                ) from e
            # Regular rate-limit (too many requests/min) — back off and retry
            if attempt < 2:
                last_err = e
                wait = 15 * (attempt + 1)
                print(f"      OpenAI 429 (rate limit) on attempt {attempt+1}, retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise

        except openai.BadRequestError as e:
            # 400 — OpenAI cannot parse our request body.
            # Most common cause: lone surrogates or other characters that survive
            # _sanitize() but cause json.dumps to produce an invalid body (Python 3.14+).
            # Retry ONCE with an ASCII-only fallback that is guaranteed to be safe.
            if attempt == 0:
                last_err = e
                print(f"      OpenAI 400 (bad request body) — retrying with ASCII-safe content...")
                for msg in kwargs["messages"]:
                    content = msg.get("content")
                    if isinstance(content, str):
                        msg["content"] = content.encode("ascii", errors="replace").decode("ascii")
                continue
            raise

        except openai.InternalServerError as e:
            # 500 — transient server error, retry with backoff
            last_err = e
            if attempt < 2:
                wait = 5 * (attempt + 1)
                print(f"      OpenAI 500 on attempt {attempt+1}, retrying in {wait}s...")
                time.sleep(wait)

        except openai.APIStatusError as e:
            if e.status_code in (502, 503, 529) and attempt < 2:
                last_err = e
                wait = 5 * (attempt + 1)
                print(f"      OpenAI {e.status_code} on attempt {attempt+1}, retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise

    raise last_err  # all retries exhausted


def parse_json_response(text: str) -> dict:
    """
    Parse a JSON object from an LLM response.

    Handles three cases:
      1. Response is plain JSON
      2. Response is JSON wrapped in ```json ... ``` code block
      3. JSON object is embedded somewhere in a prose response
    """
    # 1. Direct parse
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # 2. Code block: ```json ... ``` or ``` ... ```
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3. First { ... } block in text
    match = re.search(r"(\{[\s\S]*\})", text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    raise ValueError(
        f"Could not parse JSON from LLM response.\n"
        f"--- First 600 chars of response ---\n{text[:600]}"
    )
