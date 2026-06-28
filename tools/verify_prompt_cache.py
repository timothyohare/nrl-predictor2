"""Prove prompt caching fires on Haiku 4.5 for the ReAct-loop pattern.

Isolates the exact lever primary.py now uses: a top-level `cache_control` kwarg
on ChatAnthropic, forwarded to the direct Anthropic API as automatic
"cache the last cacheable block" caching. No DynamoDB / agent state needed.

It sends a >4096-token prefix twice (Haiku 4.5's cacheable-prefix floor):
  - call 1 should WRITE the cache  -> cache_creation > 0, cache_read == 0
  - call 2 should READ it          -> cache_read > 0

Run with the real key:
    AWS:  ANTHROPIC_API_KEY=$(aws secretsmanager get-secret-value \
            --secret-id nrl-predictor/anthropic-api-key --query SecretString --output text) \
          python tools/verify_prompt_cache.py
    or just set ANTHROPIC_API_KEY in the environment first.
"""
import os
import sys

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from scrapers.shared.constants import HAIKU_MODEL

if not os.environ.get("ANTHROPIC_API_KEY"):
    sys.exit("Set ANTHROPIC_API_KEY first (see module docstring).")

# A stable prefix comfortably over Haiku 4.5's 4096-token floor (~6k tokens).
BIG_PREFIX = ("You are an NRL analyst. Reference facts:\n"
              + "\n".join(f"- Fact {i}: stable filler line for the cacheable prefix." for i in range(900)))

llm = ChatAnthropic(
    model=HAIKU_MODEL,
    max_tokens=64,
    cache_control={"type": "ephemeral"},  # the lever primary.py binds in the loop
)

msgs = [SystemMessage(content=BIG_PREFIX), HumanMessage(content="Reply with the single word OK.")]


def details(resp):
    d = (resp.usage_metadata or {}).get("input_token_details", {}) or {}
    return d.get("cache_creation", 0), d.get("cache_read", 0)


c1, r1 = details(llm.invoke(msgs))
c2, r2 = details(llm.invoke(msgs))  # identical prefix -> should read the cache
print(f"call 1: cache_creation={c1}  cache_read={r1}")
print(f"call 2: cache_creation={c2}  cache_read={r2}")
print("PASS — caching works on Haiku" if r2 > 0 else
      "FAIL — cache_read still 0; check version (need langchain-anthropic>=1.4) / model / prefix size")
sys.exit(0 if r2 > 0 else 1)
