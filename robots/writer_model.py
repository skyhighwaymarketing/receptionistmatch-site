"""Writer model settings, copied from longevity-dose-agent (Michael 2026-10-29: every writer on Claude Opus 5.5, effort medium).

"Writer" = every call that produces text that ships or picks what ships: the post itself,
its topic/title/meta, claim and citation rewrites, topic brainstorms, and the internal-link
sentence. Judges and selectors keep their own models.

Opus 5.5 rules (claude-api skill, checked 2026-10-29): thinking is always on and counts
against max_tokens (so give it room); effort goes in output_config; forced tool_choice
("tool"/"any") returns a 400, so writer_tool_call asks with tool_choice "auto" plus an
explicit instruction and retries once if the model answers in prose instead.
"""
WRITER_MODEL = "claude-opus-5-5"
WRITER_THINKING = {"type": "adaptive"}
WRITER_EFFORT = {"effort": "medium"}
WRITER_MIN_TOKENS = 16000


def writer_tool_call(client, **kw):
    """Streamed client.messages call for a single structured tool call on the writer model."""
    choice = kw.pop("tool_choice", None) or {}
    name = choice.get("name") or kw["tools"][0]["name"]
    kw.update(model=WRITER_MODEL, thinking=WRITER_THINKING, output_config=WRITER_EFFORT,
              max_tokens=max(kw.get("max_tokens", 0), WRITER_MIN_TOKENS), tool_choice={"type": "auto"})
    kw["messages"] = list(kw["messages"]) + [
        {"role": "user", "content": f"Answer only by calling the {name} tool, exactly once."}]
    resp = None
    for attempt in (1, 2):
        # Stream: the SDK refuses non-streaming calls whose max_tokens could run past 10 min
        # (24000 does; first live run 2026-11-12 died on that ValueError before any API call).
        with client.messages.stream(**kw) as stream:
            resp = stream.get_final_message()
        if any(b.type == "tool_use" and b.name == name for b in resp.content):
            return resp
        print(f"  {name}: no tool call on attempt {attempt} (stop_reason {resp.stop_reason})"
              + ("; retrying" if attempt == 1 else ""))
    return resp
