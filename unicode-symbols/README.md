# Unicode & Symbols

Two launcher providers for the characters you need but cannot type. `/unicode`
searches every named Unicode character by name, code point, or by pasting the
character itself; `/symb` browses a curated set of common math, arrow,
currency, punctuation, and other symbols by category. Selecting a result copies
it to the clipboard.

## Plugin

| Field | Value |
| --- | --- |
| ID | `martianingreen/unicode-symbols` |
| Entries | Launcher providers: `unicode`, `symb` |
| Launcher Prefixes | `/unicode`, `/symb` |

## Requirements

Noctalia with plugin API 23 or newer (the providers load their tables with
`noctalia.readFileAsync()`). No external commands, network access, or extra
packages are needed.

## Usage

Open the launcher and type a prefix. Everything after it is the query, and
pressing Enter on a result copies that character.

### `/unicode`

| Query | Finds |
| --- | --- |
| `/unicode arrow` | every character whose name contains "arrow", best matches first |
| `/unicode latin capital letter a` | `A` (U+0041) |
| `/unicode 2192` | `→` (U+2192) |
| `/unicode U+1F600` | `😀` (U+1F600) |
| `/unicode →` | the character you pasted |

Names are matched word by word in any order, so `/unicode greek small letter
omega` and `/unicode omega greek` both work. A code point can be written as
`2192`, `U+2192`, or `0x2192`. Ranges that Unicode names algorithmically (CJK
ideographs, Hangul syllables, Tangut, Jurchen, seal characters, private-use
areas) are not stored in the table, but you can still reach them by code point
or by pasting the character: `/unicode 4E00` shows `CJK UNIFIED IDEOGRAPH-4E00`
and `/unicode AC00` shows `HANGUL SYLLABLE GA`.

With no query the provider lists a few popular characters so the copy action is
one Enter away.

### `/symb`

With no query, `/symb` lists the curated set in group order. The launcher's
category filter bar narrows it to one group. Typing searches the Unicode name,
everyday aliases, and the group name:

```
/symb currency      → € £ ¥ ₹ ₽ ₿ ...
/symb times         → ×
/symb cmd           → ⌘
/symb right arrow   → →
/symb 2192          → →
/symb ∞             → the character you pasted
```

Groups: Arrows, Math, Sets & Logic, Geometry, Superscript & Subscript,
Fractions, Greek, Currency, Punctuation, Brackets, Shapes, Signs, Keys, Music,
Letterlike.

## Settings

| Setting | Type | Default | Description |
| --- | --- | --- | --- |
| `notify_on_copy` | `bool` | `false` | Show a notification naming the character after it is copied. |
| `max_results` | `int` | `50` | Maximum number of name matches a search returns (5-200). Code-point and pasted-character rows are added on top of this. |

## Notes

- No network access and no external commands. Both providers read the tables in
  `data/` with the plugin filesystem API, and the only write is the clipboard
  copy.
- `/unicode` searches `data/unicode-0.idx`, `unicode-1.idx`, and
  `unicode-2.idx`: fixed-size records split by code point range so each file
  stays below the 4 MiB `readFileAsync()` limit. They are loaded
  asynchronously when the plugin starts; if a query arrives first, the provider
  shows a loading row and updates the results from the read callback. The
  readable source of the same data is `data/unicode.tsv`.
- `/symb` reads its small table asynchronously too, so its first query never
  parses inside the 25 ms callback budget.
- Characters that render as nothing get no badge: control and format characters,
  spaces, and unassigned code points show their name and code point instead.
  Combining marks are drawn on a dotted circle.
- Neither provider is part of the un-prefixed global search, so a stray letter
  does not fill the launcher with thousands of characters.

### Data provenance

The tables are generated from the Unicode Character Database (Unicode 18.0.0)
by `tools/build_unicode_data.py` at the repository root. That script also
documents the fixed-record index layout:

```sh
python3 tools/build_unicode_data.py           # regenerate every table
python3 tools/build_unicode_data.py --check   # verify the committed tables
```

The Unicode data files are used under the Unicode License V3; the license text
is in [`data/UNICODE-LICENSE.txt`](data/UNICODE-LICENSE.txt).
