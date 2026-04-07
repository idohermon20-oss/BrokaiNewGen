"""
Low-level LLM call helpers.
All LLM interactions in the system go through these functions.
"""
import re
import json
import openai


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
    """
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

    response = client.chat.completions.create(**kwargs)
    return response.choices[0].message.content


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
