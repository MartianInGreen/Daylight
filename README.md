# Daylight

Noctalia plugins and tools.

## Plugins

| Plugin | What it does |
| --- | --- |
| [`unicode-symbols`](unicode-symbols/) | Adds `/unicode` (search every named Unicode character by name, code point, or pasted character) and `/symb` (browse common math, arrow, currency, and other symbols by category) to the launcher. |

## Installation

Point Noctalia at this repository as a plugin source and enable the plugin:

```sh
noctalia msg plugins source add daylight git https://github.com/MartianInGreen/Daylight
noctalia msg plugins enable martianingreen/unicode-symbols
```

For local development, add the checkout as a `path` source instead, so edits
hot-reload:

```sh
noctalia msg plugins source add daylight-dev path ~/Projects/Daylight
noctalia msg plugins enable martianingreen/unicode-symbols
```

Then open the launcher and type `/unicode arrow` or `/symb currency`. See the
plugin's [README](unicode-symbols/README.md) for the query syntax and settings.

## Development

Each plugin is one top-level directory named after the part of its id after the
`/`, with a `plugin.toml` manifest, its Luau entry scripts, a README, a
thumbnail, and translations.

Tests for `unicode-symbols` run without Noctalia:

```sh
lua5.4 tests/run.lua        # provider behavior with a host stub
python3 tests/test_data.py  # manifest, translations, and table consistency
noctalia plugins lint unicode-symbols
```

The Unicode tables are committed. `unicode-symbols/data/unicode.tsv` is the
readable source; the fixed-record `unicode-N.idx` files the plugin searches are
derived from it. To rebuild everything from the Unicode Character Database, run
`python3 tools/build_unicode_data.py`; pass `--check` to verify the committed
data is current without writing anything.

## License

MIT, except the generated Unicode tables under `unicode-symbols/data/`, which
are distributed under the [Unicode License V3](unicode-symbols/data/UNICODE-LICENSE.txt).
