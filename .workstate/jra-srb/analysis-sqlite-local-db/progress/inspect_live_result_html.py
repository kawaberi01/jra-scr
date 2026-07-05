import sys
from pathlib import Path
import re

path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/jra_result_202501050611.html")
extra_tokens = sys.argv[2:]
raw = path.read_bytes()
print(f"bytes={len(raw)}")
print(f"head_bytes={raw[:32]!r}")
text = raw.decode("utf-8", errors="ignore")

for token in [
    "<table",
    "refund_area",
    "race_result_unit",
    'td class="place"',
    'table class="basic narrow-xy striped"',
]:
    print(f"{token}={text.find(token)}")
for token in extra_tokens:
    idx = text.find(token)
    print(f"extra:{token}={idx}")
    if idx >= 0:
        snippet = text[max(0, idx - 120) : idx + 240]
        print(snippet.encode("unicode_escape").decode("ascii"))

start = text.find("<table")
if start >= 0:
    print(text[start : start + 1200])
else:
    print(text[:1200])

matches = re.findall(r"pw01s\w+(?:/\w+)?", text)
print(f"pw01s_matches={len(matches)}")
for item in matches[:40]:
    print(f"match={item}")
