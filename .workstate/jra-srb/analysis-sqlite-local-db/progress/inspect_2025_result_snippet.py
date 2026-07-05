from pathlib import Path

text = Path("data/jradb_accessS_race_202501050611_live.html").read_text(encoding="utf-8")
start = text.find("race_result_unit")
print(text[start : start + 5000].encode("unicode_escape").decode("ascii"))
