#!/usr/bin/env python3
"""Validate the committed data tables and the manifest that points at them.

Run from the repository root:

    python3 tests/test_data.py

Checks that the manifest, translations, and generated tables agree with each
other, without starting Noctalia. `tools/build_unicode_data.py --check`
separately proves the tables still match the upstream UCD.
"""

from __future__ import annotations

import bisect
import json
import re
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = REPO_ROOT / "unicode-symbols"
DATA_DIR = PLUGIN_DIR / "data"

TRANSLATION_KEY_SEGMENT = re.compile(r"^[a-z0-9-][a-z0-9_-]*$")
LAUNCHER_PREFIX = re.compile(r"^[a-z]+$")

failures: list[str] = []
checks = 0


def check(condition: bool, message: str) -> None:
    global checks
    checks += 1
    if not condition:
        failures.append(message)


def read_tsv(path: Path) -> list[list[str]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        rows.append(line.split("\t"))
    return rows


def resolve_key(bundle: dict, dotted: str) -> bool:
    node = bundle
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return isinstance(node, str)


def translation_keys(node, prefix: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    keys: list[tuple[str, ...]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            keys.append(prefix + (key,))
            keys.extend(translation_keys(value, prefix + (key,)))
    return keys


def main() -> int:
    manifest = tomllib.loads((PLUGIN_DIR / "plugin.toml").read_text(encoding="utf-8"))
    (PLUGIN_DIR / "README.md").read_text(encoding="utf-8")
    bundle = json.loads((PLUGIN_DIR / "translations" / "en.json").read_text(encoding="utf-8"))

    # ── manifest shape ─────────────────────────────────────────────────
    check(manifest.get("id") == "martianingreen/unicode-symbols", "manifest id")
    check(re.fullmatch(r"\d+\.\d+\.\d+", manifest.get("version", "")) is not None, "semantic version")
    check(isinstance(manifest.get("plugin_api"), int), "plugin_api is an integer")
    check(manifest.get("plugin_api", 0) >= 23, "plugin_api covers noctalia.readFileAsync")
    check(len(manifest.get("description", "")) <= 120, "description is at most 120 characters")

    providers = manifest.get("launcher_provider", [])
    check(len(providers) == 2, "exactly two launcher providers")
    by_prefix = {entry.get("prefix"): entry for entry in providers}
    check(set(by_prefix) == {"unicode", "symb"}, "provider prefixes are unicode and symb")
    for entry in providers:
        check(LAUNCHER_PREFIX.fullmatch(entry.get("prefix", "")) is not None, "prefix is lowercase letters")
        check(entry.get("include_in_global_search") is False, "providers stay out of global search")
        entry_path = PLUGIN_DIR / entry["entry"]
        check(entry_path.is_file(), f"{entry['entry']} exists")
        source = entry_path.read_text(encoding="utf-8")
        for callback in ("function onQuery(", "function onActivate("):
            check(callback in source, f"{entry['entry']} defines {callback[9:-1]}")
        check("require(\"./lib/util.luau\")" in source, f"{entry['entry']} uses the shared helpers")

    # ── translations ───────────────────────────────────────────────────
    keys: list[str] = []
    for setting in manifest.get("setting", []):
        keys.extend([setting["label_key"], setting["description_key"]])
    for dotted in keys:
        check(resolve_key(bundle, dotted), f"translations/en.json resolves {dotted}")

    for parts in translation_keys(bundle):
        segment = parts[-1]
        check(TRANSLATION_KEY_SEGMENT.fullmatch(segment) is not None, f"translation key segment {segment!r}")

    # ── unicode table ──────────────────────────────────────────────────
    unicode_rows = read_tsv(DATA_DIR / "unicode.tsv")
    check(len(unicode_rows) > 40000, "unicode.tsv holds every named character")
    check(all(len(row) == 4 for row in unicode_rows), "unicode.tsv rows have four columns")
    unicode_by_code: dict[int, tuple[str, str]] = {}
    previous = -1
    for row in unicode_rows:
        name, hex_code, category = row[0], row[1], row[2]
        code = int(hex_code, 16)
        check(code > previous, f"unicode.tsv is sorted at U+{hex_code}")
        previous = code
        check(0 <= code <= 0x10FFFF, f"U+{hex_code} is a valid scalar range")
        check(re.fullmatch(r"[A-Z][a-z]", category) is not None, f"U+{hex_code} has a general category")
        check(name != "", f"U+{hex_code} has a name")
        check(re.fullmatch(r"[0-9A-F]{4,6}", hex_code) is not None, f"U+{hex_code} hex column")
        check("\t" not in name and "|" not in name, f"U+{hex_code} name has no separators")
        unicode_by_code[code] = (name, category)
    check(len(unicode_by_code) == len(unicode_rows), "unicode.tsv has no duplicate code points")

    # The plugin searches fixed 97-byte records instead of parsing this table
    # inside its 25 ms callback. Derive them again and check the committed
    # index byte-for-byte against unicode.tsv.
    index_names = ["unicode-0.idx", "unicode-1.idx", "unicode-2.idx"]
    check(not (DATA_DIR / "unicode.idx").exists(), "obsolete single index is gone")

    index_rows: list[tuple[str, str, str]] = []
    for filename in index_names:
        path = DATA_DIR / filename
        check(path.is_file(), f"{filename} exists")
        content = path.read_bytes()
        check(len(content) <= 4 * 1024 * 1024, f"{filename} fits the 4 MiB async read limit")
        check(len(content) % 97 == 0, f"{filename} is a whole number of 97-byte records")
        for offset in range(0, len(content), 97):
            record = content[offset : offset + 97]
            length = record[88]
            name = record[:length].decode("ascii")
            check(record[length:88] == b"\0" * (88 - length), f"{filename} record padding at byte {offset}")
            hex_code = record[89:95].decode("ascii")
            category = record[95:97].decode("ascii")
            check(re.fullmatch(r"[0-9A-F]{6}", hex_code) is not None, f"{filename} hex field at byte {offset}")
            check(re.fullmatch(r"[A-Z][a-z]", category) is not None, f"{filename} category at byte {offset}")
            index_rows.append((name, hex_code, category))

    check(len(index_rows) == len(unicode_rows), "index records match the unicode table row count")
    for index_row, unicode_row in zip(index_rows, unicode_rows):
        check(index_row[0] == unicode_row[0], f"index name for U+{unicode_row[1]} matches unicode.tsv")
        check(int(index_row[1], 16) == int(unicode_row[1], 16), f"index code point for {index_row[0]} matches")
        check(index_row[2] == unicode_row[2], f"index category for U+{index_row[1]} matches")

    alias_rows = read_tsv(DATA_DIR / "aliases.tsv")
    check(len(alias_rows) > 400, "aliases.tsv lists the formal Unicode aliases")
    check(all(len(row) == 4 for row in alias_rows), "aliases.tsv rows have four columns")
    seen_aliases: set[tuple[str, int]] = set()
    for row in alias_rows:
        alias, hex_code, name, category = row
        code = int(hex_code, 16)
        check(alias != "" and "\t" not in alias, f"alias for U+{hex_code} is valid")
        check((alias, code) not in seen_aliases, f"alias {alias} for U+{hex_code} appears once")
        seen_aliases.add((alias, code))
        check(code in unicode_by_code, f"alias {alias} points at a named character")
        if code in unicode_by_code:
            check(unicode_by_code[code] == (name, category), f"alias {alias} carries the right name and category")

    popular_rows = read_tsv(DATA_DIR / "popular.tsv")
    check(len(popular_rows) >= 30, "popular.tsv lists the empty-query characters")
    check(all(len(row) == 4 for row in popular_rows), "popular.tsv rows have four columns")
    popular_codes = [int(row[1], 16) for row in popular_rows]
    check(len(popular_codes) == len(set(popular_codes)), "popular.tsv has no duplicate code points")
    for row in popular_rows:
        code = int(row[1], 16)
        check(code in unicode_by_code, f"popular U+{row[1]} is in unicode.tsv")
        check(unicode_by_code[code][0] == row[0], f"popular U+{row[1]} name matches unicode.tsv")

    for expected in ("NULL", "LATIN CAPITAL LETTER A", "RIGHTWARDS ARROW", "GRINNING FACE", "COMBINING ACUTE ACCENT"):
        check(any(name == expected for name, _ in unicode_by_code.values()), f"unicode.tsv contains {expected}")

    # Every named character should still be inside a Unicode block.
    blocks = read_tsv(DATA_DIR / "blocks.tsv")
    check(all(len(row) == 3 for row in blocks), "blocks.tsv rows have three columns")
    previous_stop = -1
    for row in blocks:
        start, stop = int(row[0], 16), int(row[1], 16)
        check(start > previous_stop, f"blocks.tsv is sorted at U+{row[0]}")
        check(start <= stop, f"block {row[2]} has a valid range")
        previous_stop = stop

    block_starts = [int(row[0], 16) for row in blocks]

    def block_of(code: int) -> str | None:
        index = bisect.bisect_right(block_starts, code) - 1
        if index >= 0 and int(blocks[index][1], 16) >= code:
            return blocks[index][2]
        return None

    missing_block = [row for row in unicode_rows if block_of(int(row[1], 16)) is None]
    check(not missing_block, f"{len(missing_block)} characters have no block")

    # ── symbol table ───────────────────────────────────────────────────
    symbol_rows = read_tsv(DATA_DIR / "symbols.tsv")
    check(len(symbol_rows) >= 700, "symbols.tsv holds the curated set")
    check(all(len(row) == 4 for row in symbol_rows), "symbols.tsv rows have four columns")

    categories = [category["label"] for category in by_prefix["symb"].get("category", [])]
    check(len(categories) == len(set(categories)), "category labels are unique")
    group_order: list[str] = []
    seen_codes: set[int] = set()
    for row in symbol_rows:
        code = int(row[0], 16)
        check(code not in seen_codes, f"symbol U+{row[0]} appears once")
        seen_codes.add(code)
        check(row[1] in categories, f"symbol U+{row[0]} uses a declared category")
        if not group_order or group_order[-1] != row[1]:
            group_order.append(row[1])
        check(row[2] != "", f"symbol U+{row[0]} has a name")
        check(code in unicode_by_code, f"symbol U+{row[0]} is a named Unicode character")
        if code in unicode_by_code:
            check(unicode_by_code[code][0] == row[2], f"symbol U+{row[0]} name matches UnicodeData")

    check(group_order == categories, "symbols.tsv group order matches the manifest categories")
    check(len(seen_codes) == len(symbol_rows), "symbols.tsv has no duplicate code points")

    # ── glyphs ─────────────────────────────────────────────────────────
    tabler_path = Path("/usr/share/noctalia/assets/fonts/tabler.json")
    if tabler_path.is_file():
        tabler = json.loads(tabler_path.read_text(encoding="utf-8"))
        glyphs = {entry.get("glyph") for entry in providers if entry.get("glyph")}
        glyphs |= {category.get("glyph") for category in by_prefix["symb"].get("category", [])}
        glyphs.add(manifest.get("icon"))
        for glyph in sorted(glyphs):
            check(glyph in tabler, f"glyph {glyph!r} exists in the bundled Tabler set")

    if failures:
        for message in failures:
            print(f"FAIL: {message}", file=sys.stderr)
        print(f"\n{len(failures)} of {checks} checks failed", file=sys.stderr)
        return 1
    print(f"ok - {checks} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
