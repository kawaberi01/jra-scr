from pathlib import Path
import sys

from jra_srb.extractors import parse_result_race_navigation

path = Path(sys.argv[1])
text = path.read_text(encoding="shift_jis", errors="ignore")
mapping = parse_result_race_navigation(text)
print(sorted(mapping.items()))
