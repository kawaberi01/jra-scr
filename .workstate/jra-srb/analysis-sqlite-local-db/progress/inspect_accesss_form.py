import sys
from pathlib import Path

from bs4 import BeautifulSoup

path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/jradb_accessS_select_post_live.html")
text = path.read_text(encoding="shift_jis", errors="ignore")
soup = BeautifulSoup(text, "html.parser")

for idx, form in enumerate(soup.select("form"), start=1):
    print(f"form[{idx}] action={form.get('action')} method={form.get('method')}")
    for node in form.select("input, select, textarea"):
        print(
            "field",
            node.name,
            node.get("type"),
            node.get("name"),
            node.get("value"),
        )
        if node.name == "select":
            for option in node.select("option"):
                print(
                    "option",
                    node.get("name"),
                    option.get("value"),
                    option.get_text(" ", strip=True),
                    option.has_attr("selected"),
                )

print("onclick_samples")
for link in soup.select("[onclick]")[:50]:
    print(link.get("onclick"))
