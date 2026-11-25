"""Merge new translations into a catalogue: python -m tests.i18n_add ti new_strings.json
The JSON file maps English text to the translation. Existing entries are replaced; order is kept sorted."""
import json
import sys

from elf_archive import i18n


def merge(lang, additions):
    path = i18n.CATALOG_DIR / f"{lang}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    meta = data.pop("_meta", None)
    data.update(additions)
    out = {"_meta": meta} if meta else {}
    out.update(dict(sorted(data.items(), key=lambda kv: kv[0].lower())))
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return len(additions)


if __name__ == "__main__":
    lang, src = sys.argv[1], sys.argv[2]
    print(merge(lang, json.loads(open(src, encoding="utf-8").read())), "entries merged into", lang)
