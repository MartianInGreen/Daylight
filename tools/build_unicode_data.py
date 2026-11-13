#!/usr/bin/env python3
"""Build the data tables shipped with the `unicode-symbols` Noctalia plugin.

The plugin is a pair of launcher providers:

  /unicode  search every named Unicode character by name, code point, or by
            pasting the character itself
  /symb     browse and search a curated set of common symbols (math, arrows,
            currency, punctuation, ...) grouped by category

Inputs are the public Unicode Character Database files (UnicodeData.txt,
Blocks.txt, NameAliases.txt) fetched from unicode.org and cached under
tools/.ucd-cache/. The generated tables are committed, so building the plugin
never needs the network.

Outputs (unicode-symbols/data/):

  unicode.tsv   name <TAB> code-hex <TAB> general-category <TAB> aliases
  unicode-N.idx fixed 97-byte records built from unicode.tsv (see below)
  aliases.tsv   formal Unicode name alias <TAB> code-hex <TAB> name <TAB> category
  popular.tsv   the same four columns as unicode.tsv, in empty-query order
  blocks.tsv    start-hex <TAB> end-hex <TAB> block name
  symbols.tsv   code-hex <TAB> group label <TAB> name <TAB> aliases

The unicode-N.idx files are what the plugin searches. Noctalia gives each
callback 25 ms of CPU time, which is not enough to parse 41k TSV lines, so each
index stores one fixed-size record per character:

  bytes  0..87   name, NUL padded
  byte   88      name length in bytes
  bytes  89..94  code point as six zero-padded uppercase hex digits
  bytes  95..96  general category

Fixed records let /unicode find a word in the index as plain text and jump
straight to the record, without parsing the table up front. The records are
split into three files by code point (BMP, supplementary plane, planes 3+)
because noctalia.readFileAsync() reads at most 4 MiB per call; each segment
stays well below that limit as Unicode grows. unicode.tsv is committed next to
them as the readable source of truth; this script derives one from the other
and tests/test_data.py checks they agree.

Every file carries a header naming the Unicode version it was built from.
Aliases are separated by `|` so they can contain spaces. The curated symbol
set is validated against UnicodeData.txt: an unknown code point or a duplicate
entry fails the build instead of shipping a table that disagrees with itself.

The Unicode data files are used under the Unicode License V3; a copy is
committed as unicode-symbols/data/UNICODE-LICENSE.txt.
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DATA = REPO_ROOT / "unicode-symbols" / "data"
DEFAULT_CACHE = Path(__file__).resolve().parent / ".ucd-cache"

UCD_URL = "https://www.unicode.org/Public/UCD/latest/ucd/"
UCD_FILES = ("UnicodeData.txt", "Blocks.txt", "NameAliases.txt", "ReadMe.txt")

# Code point ranges that UnicodeData.txt stores as a First/Last pair. They are
# left out of unicode.tsv and named algorithmically by the plugin, so a code
# point query still resolves them without shipping 200k near-identical rows.
# (The Hangul syllable range gets its real algorithmic name; the ideograph
# ranges use the standard "CJK UNIFIED IDEOGRAPH-XXXX" form.)
ALGORITHMIC_RANGE_LABELS = {
    "CJK Ideograph Extension A": "CJK UNIFIED IDEOGRAPH-{code}",
    "CJK Ideograph": "CJK UNIFIED IDEOGRAPH-{code}",
    "CJK Ideograph Extension B": "CJK UNIFIED IDEOGRAPH-{code}",
    "CJK Ideograph Extension C": "CJK UNIFIED IDEOGRAPH-{code}",
    "CJK Ideograph Extension D": "CJK UNIFIED IDEOGRAPH-{code}",
    "CJK Ideograph Extension E": "CJK UNIFIED IDEOGRAPH-{code}",
    "CJK Ideograph Extension F": "CJK UNIFIED IDEOGRAPH-{code}",
    "CJK Ideograph Extension G": "CJK UNIFIED IDEOGRAPH-{code}",
    "CJK Ideograph Extension H": "CJK UNIFIED IDEOGRAPH-{code}",
    "CJK Ideograph Extension I": "CJK UNIFIED IDEOGRAPH-{code}",
    "CJK Ideograph Extension J": "CJK UNIFIED IDEOGRAPH-{code}",
    "Tangut Ideograph": "TANGUT IDEOGRAPH-{code}",
    "Tangut Ideograph Supplement": "TANGUT IDEOGRAPH-{code}",
    "Jurchen Character": "JURCHEN CHARACTER-{code}",
    "Seal Character": "SEAL CHARACTER-{code}",
}

# Characters listed by /unicode when the query is empty, in display order.
POPULAR = [
    "2192", "2190", "2191", "2193", "2194", "21D2", "21D4",
    "221E", "00B1", "00D7", "00F7", "2260", "2248", "2264", "2265",
    "221A", "2211", "222B", "03C0", "00B0", "00B5",
    "20AC", "00A3", "00A5", "00A9", "00AE", "2122",
    "2026", "2014", "2013", "2022", "2713", "2605", "2665",
    "221D", "2261",
]

# ── /symb groups ────────────────────────────────────────────────────────
# Browse order is the order below; each symbol belongs to exactly one group.
# The labels must match the [[launcher_provider.category]] labels in
# plugin.toml (tests/test_data.py enforces it).
GROUPS: list[tuple[str, list[str]]] = [
    (
        "Arrows",
        [
            "2190", "2191", "2192", "2193", "2194", "2195", "2196", "2197", "2198", "2199",
            "21A0", "21A4", "21A6", "21A9", "21AA", "21B5", "21BA", "21BB", "21C4", "21C6",
            "21CB", "21CC", "21D0", "21D1", "21D2", "21D3", "21D4", "21D5",
            "21E0", "21E1", "21E2", "21E3", "21E6", "21E8", "21E9",
            "27F5", "27F6", "27F7", "27F8", "27F9", "27FA", "27FB", "27FC",
            "2905", "2933", "2934", "2935", "2936", "2937",
            "2B05", "2B06", "2B07", "2B08", "2B09", "2B0A", "2B0B", "2B0C", "2B0D",
            "2794", "2799", "279A", "279B", "279C", "279D", "279E", "279F", "27A0", "27A1",
            "27A2", "27A3", "27A4", "27A5", "27A6", "27A7", "27A8", "27A9", "27AA", "27AB",
            "27AC", "27AD", "27AE", "27AF", "27B0", "27B1", "27B2", "27B3", "27B4", "27B5",
            "27B6", "27B7", "27B8", "27B9", "27BA", "27BB", "27BC", "27BD", "27BE", "27BF",
        ],
    ),
    (
        "Math",
        [
            "002B", "2212", "00D7", "00F7", "00B1", "2213", "003D", "2260", "2248", "2245",
            "2261", "2262", "2263", "003C", "003E", "2264", "2265", "2266", "2267", "226A",
            "226B", "226E", "226F", "2270", "2271", "221D", "221E", "221A", "221B", "221C",
            "2211", "220F", "2210", "222B", "222C", "222D", "222E", "222F", "2230", "2231",
            "2232", "2233", "2202", "2207", "2206",
            "2243", "224A", "2250", "2251", "2252", "2253", "2268", "2269", "2272", "2273",
            "2274", "2275", "2276", "2277", "2278", "2279", "227A", "227B", "227C", "227D",
            "227E", "227F", "2280", "2281",
            "22C5", "2218", "00B7", "2219", "2032", "2033", "2034", "2044", "2215",
            "0025", "2030", "2031", "2223", "2224", "2236", "2237", "223C", "223D",
        ],
    ),
    (
        "Sets & Logic",
        [
            "2208", "2209", "220B", "220C", "2282", "2283", "2284", "2285", "2286", "2287",
            "2288", "2289", "228A", "228B", "222A", "2229", "22C3", "22C2", "2216", "2205",
            "2200", "2203", "2204", "00AC", "2227", "2228", "22BB", "22BC", "22BD",
            "2295", "2296", "2297", "2298", "2299", "229A", "229B", "229D", "229E", "229F",
            "22A0", "22A1", "2234", "2235", "22A2", "22A3", "22A8", "22AC",
            "2135", "2136", "2137", "2138",
        ],
    ),
    (
        "Geometry",
        [
            "00B0", "2220", "2221", "2222", "22BE", "22BF", "22A5", "22A4", "2225", "2226",
            "2312", "2313", "2314",
        ],
    ),
    (
        "Superscript & Subscript",
        [
            "2070", "00B9", "00B2", "00B3", "2074", "2075", "2076", "2077", "2078", "2079",
            "207A", "207B", "207C", "207D", "207E", "207F", "2071",
            "2080", "2081", "2082", "2083", "2084", "2085", "2086", "2087", "2088", "2089",
            "208A", "208B", "208C", "208D", "208E",
            "2090", "2091", "2092", "2093", "2094", "2095", "2096", "2097", "2098", "2099",
            "209A", "209B", "209C",
        ],
    ),
    (
        "Fractions",
        [
            "00BC", "00BD", "00BE", "2150", "2151", "2152", "2153", "2154", "2155", "2156",
            "2157", "2158", "2159", "215A", "215B", "215C", "215D", "215E", "215F",
        ],
    ),
    (
        "Greek",
        [
            "0391", "0392", "0393", "0394", "0395", "0396", "0397", "0398", "0399", "039A",
            "039B", "039C", "039D", "039E", "039F", "03A0", "03A1", "03A3", "03A4", "03A5",
            "03A6", "03A7", "03A8", "03A9",
            "03B1", "03B2", "03B3", "03B4", "03B5", "03B6", "03B7", "03B8", "03B9", "03BA",
            "03BB", "03BC", "03BD", "03BE", "03BF", "03C0", "03C1", "03C2", "03C3", "03C4",
            "03C5", "03C6", "03C7", "03C8", "03C9",
            "03D0", "03D1", "03D2", "03D5", "03D6", "03F0", "03F1", "03F4", "03F5",
        ],
    ),
    (
        "Currency",
        [
            "0024", "00A2", "00A3", "00A4", "00A5",
            "20A0", "20A1", "20A2", "20A3", "20A4", "20A5", "20A6", "20A7", "20A8", "20A9",
            "20AA", "20AB", "20AC", "20AD", "20AE", "20AF", "20B0", "20B1", "20B2", "20B3",
            "20B4", "20B5", "20B6", "20B7", "20B8", "20B9", "20BA", "20BB", "20BC", "20BD",
            "20BE", "20BF",
            "09F3", "0AF1", "0BF9", "17DB",
        ],
    ),
    (
        "Punctuation",
        [
            "2010", "2011", "2012", "2013", "2014", "2015", "2016", "2017", "2018", "2019",
            "201A", "201B", "201C", "201D", "201E", "201F", "2020", "2021", "2022", "2023",
            "2024", "2025", "2026", "2027", "2038", "2039", "203A", "203B", "203D", "2041",
            "2042", "2043", "204F", "2057",
            "00A1", "00A7", "00B6", "00AB", "00BB", "00BF",
        ],
    ),
    (
        "Brackets",
        [
            "2329", "232A", "3008", "3009", "27E8", "27E9", "27EA", "27EB", "27EC", "27ED",
            "27EE", "27EF", "2308", "2309", "230A", "230B",
            "2983", "2984", "2985", "2986", "2987", "2988", "2989", "298A", "298B", "298C",
            "298D", "298E", "298F", "2990", "2991", "2992", "2993", "2994", "2995", "2996",
            "2997", "2998", "301A", "301B", "2E28", "2E29",
        ],
    ),
    (
        "Shapes",
        [f"{cp:04X}" for cp in range(0x25A0, 0x2600)]
        + ["2B1B", "2B1C", "2B24", "2B25", "2B26", "2B27", "2B28", "2B29", "2B2A", "2B2B",
           "2B2C", "2B2D", "2B2E", "2B2F"],
    ),
    (
        "Signs",
        [
            "2713", "2714", "2715", "2716", "2717", "2718", "271D", "2720", "2721",
            "2726", "2727", "2728", "2729", "272A", "272D", "272E", "272F", "2730", "2731",
            "2732", "2733", "2734", "273D", "273F", "2740", "2744", "274C", "274E",
            "2753", "2754", "2755", "2757", "2763", "2764", "2765", "2766", "2767",
            "2605", "2606", "2660", "2663", "2665", "2666", "26A0", "26A1", "2620", "2622",
            "2623", "262E", "262F", "2639", "263A", "263B", "2640", "2642", "26A5", "26A6",
            "26A7", "26B2", "267B", "267E", "269B", "269C",
        ],
    ),
    (
        "Keys",
        [
            "2318", "2325", "2303", "21E4", "21E5", "21E7", "21EA", "232B", "2326", "238B",
            "23CE", "2423", "2327", "23CF", "2324", "2328",
        ],
    ),
    (
        "Music",
        [
            "2669", "266A", "266B", "266C", "266D", "266E", "266F",
            "1D11E", "1D121", "1D122", "1D12A", "1D12B",
            "1D13D", "1D13E", "1D13F", "1D140", "1D141",
        ],
    ),
    (
        "Letterlike",
        [
            "2102", "210B", "210E", "210F", "2111", "2113", "2115", "2118", "2119", "211A",
            "211B", "211C", "211D", "2124", "2126", "2127", "212B", "212E",
            "2103", "2109", "2121", "2116", "2117", "2120", "2122",
            "00A9", "00AE", "00B5",
        ],
    ),
]

# Extra search terms for symbols whose everyday name is not in the Unicode
# name ("times" for MULTIPLICATION SIGN, "cmd" for PLACE OF INTEREST SIGN, ...).
# The formal Unicode name and the group label are always searchable too.
SYMBOL_ALIASES = {
    "2190": "left west back previous",
    "2191": "up north",
    "2192": "right east forward next to yields",
    "2193": "down south",
    "2194": "left right swap horizontal",
    "2195": "up down vertical",
    "2196": "up left northwest",
    "2197": "up right northeast",
    "2198": "down right southeast",
    "2199": "down left southwest",
    "21A0": "onto surjective",
    "21A4": "maps from",
    "21A6": "maps to mapsto",
    "21A9": "return reply undo back",
    "21AA": "forward redo",
    "21B5": "return enter newline",
    "21BA": "anticlockwise counterclockwise undo",
    "21BB": "clockwise redo refresh reload",
    "21C4": "swap exchange",
    "21C6": "swap exchange",
    "21CB": "equilibrium reversible reaction",
    "21CC": "equilibrium reversible reaction",
    "21D0": "double left implies",
    "21D2": "double right implies logic",
    "21D4": "iff if and only if equivalence",
    "27F9": "long implies",
    "27FA": "long iff equivalence",
    "27FB": "long maps from",
    "27FC": "long maps to mapsto",
    "2933": "mapsto",
    "2934": "turn up",
    "2935": "turn down",
    "2B05": "left",
    "2B06": "up",
    "2B07": "down",
    "2B08": "up right",
    "2B09": "up left",
    "2B0A": "down right",
    "2B0B": "down left",
    "2B0C": "left right swap",
    "2B0D": "up down",
    "27A1": "right emoji",
    "27A4": "pointer right",
    "002B": "plus add addition",
    "2212": "minus subtract subtraction",
    "00D7": "times multiply multiplication",
    "00F7": "divide division obelus",
    "00B1": "plus minus plusminus pm",
    "2213": "minus plus minusplus mp",
    "2260": "not equal neq inequality",
    "2248": "approx approximately almost equal",
    "2245": "congruent isomorphic",
    "2261": "equivalent identical triple equals",
    "2264": "less than or equal leq le",
    "2265": "greater than or equal geq ge",
    "226A": "much less",
    "226B": "much greater",
    "221D": "proportional",
    "221E": "infinity infinite lemniscate",
    "221A": "sqrt square root radical",
    "221B": "cube root cbrt",
    "221C": "fourth root",
    "2211": "sum summation sigma",
    "220F": "product prod",
    "2210": "coproduct",
    "222B": "integral int calculus",
    "222C": "double integral",
    "222D": "triple integral",
    "222E": "contour integral",
    "222F": "surface integral",
    "2230": "volume integral",
    "2202": "partial derivative del",
    "2207": "nabla grad gradient",
    "2206": "increment laplace",
    "22C5": "dot product cdot",
    "2218": "ring operator compose",
    "00B7": "middle dot interpunct",
    "2219": "bullet operator dot",
    "2032": "prime minute feet arcminute",
    "2033": "double prime second inches arcsecond",
    "2034": "triple prime",
    "2044": "fraction slash",
    "2215": "division slash",
    "0025": "percent percentage",
    "2030": "per mille permille promille",
    "2031": "basis point per ten thousand bps",
    "2223": "divides divisor",
    "2224": "does not divide",
    "2208": "in element of member belongs",
    "2209": "not in",
    "220B": "contains",
    "220C": "does not contain",
    "2282": "subset proper",
    "2283": "superset proper",
    "2286": "subset equal",
    "2287": "superset equal",
    "222A": "union cup",
    "2229": "intersection cap",
    "22C3": "union",
    "22C2": "intersection",
    "2216": "set minus difference",
    "2205": "empty set null emptyset",
    "2200": "for all forall",
    "2203": "exists there exists some",
    "2204": "not exists",
    "00AC": "not negation",
    "2227": "and logical and wedge conjunction",
    "2228": "or logical or vee disjunction",
    "22BB": "xor exclusive or",
    "22BC": "nand",
    "22BD": "nor",
    "2295": "xor circled plus direct sum",
    "2297": "circled times tensor",
    "2234": "therefore thus",
    "2235": "because since",
    "22A2": "turnstile proves",
    "22A8": "models entails",
    "2135": "aleph",
    "2136": "beth",
    "2137": "gimel",
    "2138": "daleth",
    "00B0": "degree deg temperature",
    "2220": "angle",
    "22A5": "perpendicular orthogonal",
    "2225": "parallel",
    "2312": "arc",
    "2313": "segment",
    "2314": "sector",
    "2032": "prime minute feet",
    "00B2": "squared superscript two",
    "00B3": "cubed superscript three",
    "2070": "superscript zero",
    "03C0": "pi",
    "03A0": "capital pi",
    "03C6": "phi",
    "03D5": "phi symbol",
    "03B5": "epsilon",
    "03F5": "epsilon symbol",
    "03B8": "theta",
    "03D1": "theta symbol",
    "03C3": "sigma",
    "03C2": "final sigma",
    "03A3": "capital sigma sum",
    "03BC": "mu micro",
    "03A9": "omega ohm",
    "03C9": "omega",
    "0024": "dollar usd money",
    "00A2": "cent money",
    "00A3": "pound sterling gbp money",
    "00A4": "currency money",
    "00A5": "yen yuan jpy cny money",
    "20AC": "euro eur money",
    "20B9": "rupee inr money",
    "20BD": "ruble rub money",
    "20BF": "bitcoin btc crypto",
    "20A9": "won krw",
    "20AA": "shekel ils",
    "20BA": "lira try",
    "20B4": "hryvnia uah",
    "20B1": "peso php",
    "20AB": "dong vnd",
    "20B5": "cedi",
    "20B8": "tenge",
    "20A6": "naira",
    "20AD": "kip",
    "20AE": "tugrik",
    "20A7": "peseta",
    "20A4": "lira",
    "20A3": "franc",
    "20A1": "colon",
    "20A2": "cruzeiro",
    "20AF": "drachma",
    "20B2": "guarani",
    "20B3": "austral",
    "20B6": "livre",
    "20B7": "spesmilo",
    "20BB": "nordic mark",
    "20BC": "manat",
    "20BE": "lari",
    "09F3": "taka bangladesh",
    "0AF1": "rupee gujarati",
    "0BF9": "rupee tamil",
    "17DB": "riel cambodia",
    "2013": "en dash ndash",
    "2014": "em dash mdash",
    "2018": "left single quote apostrophe open",
    "2019": "right single quote apostrophe close",
    "201C": "left double quote open",
    "201D": "right double quote close",
    "201E": "low double quote german",
    "2020": "dagger footnote",
    "2021": "double dagger footnote",
    "2022": "bullet point list",
    "2026": "ellipsis dots dot dot dot",
    "2039": "angle quote guillemet",
    "203A": "angle quote guillemet",
    "00AB": "guillemet french quote",
    "00BB": "guillemet french quote",
    "00A1": "inverted exclamation spanish",
    "00BF": "inverted question spanish",
    "00A7": "section sign law",
    "00B6": "pilcrow paragraph",
    "203B": "reference mark",
    "203D": "interrobang",
    "2042": "asterism",
    "2043": "hyphen bullet",
    "2057": "quadruple prime",
    "2308": "ceiling round up",
    "2309": "ceiling round up",
    "230A": "floor round down",
    "230B": "floor round down",
    "27E8": "angle bracket bra ket",
    "27E9": "angle bracket bra ket",
    "2329": "angle bracket",
    "232A": "angle bracket",
    "3008": "cjk angle bracket",
    "3009": "cjk angle bracket",
    "27EA": "double angle bracket",
    "27EB": "double angle bracket",
    "2983": "curly bracket",
    "2984": "curly bracket",
    "301A": "square bracket",
    "301B": "square bracket",
    "2713": "check tick yes ok",
    "2714": "check tick yes ok",
    "2715": "cross x no",
    "2716": "cross x no",
    "2717": "cross x no",
    "2718": "cross x no",
    "271D": "cross latin",
    "2720": "cross maltese",
    "2721": "star of david",
    "2726": "star four pointed",
    "2727": "star four pointed outline",
    "2744": "snowflake",
    "274C": "cross no",
    "274E": "cross no",
    "2764": "heart love",
    "2605": "star filled",
    "2606": "star outline empty",
    "2660": "spade card",
    "2663": "club card",
    "2665": "heart card love",
    "2666": "diamond card",
    "26A0": "warning",
    "26A1": "lightning bolt high voltage",
    "2620": "radioactive",
    "2622": "biohazard",
    "262E": "peace",
    "262F": "yin yang",
    "2640": "female venus woman",
    "2642": "male mars man",
    "267B": "recycle recycling",
    "267E": "infinity permanent",
    "269B": "atom",
    "269C": "fleur de lis",
    "2318": "command cmd",
    "2325": "option alt",
    "2303": "control ctrl",
    "21E4": "tab",
    "21E5": "tab",
    "21E7": "shift",
    "21EA": "caps lock",
    "232B": "backspace delete",
    "2326": "delete forward del",
    "238B": "escape esc",
    "23CE": "return enter",
    "2423": "space",
    "2327": "clear",
    "23CF": "eject",
    "2324": "clear",
    "2328": "keyboard",
    "2669": "note quarter",
    "266A": "note eighth music",
    "266B": "notes beamed music",
    "266C": "notes music",
    "266D": "flat",
    "266E": "natural",
    "266F": "sharp",
    "1D11E": "treble clef g clef",
    "1D121": "alto clef c clef",
    "1D122": "bass clef f clef",
    "1D12A": "double sharp",
    "1D12B": "double flat",
    "1D13D": "quarter rest",
    "1D13E": "eighth rest",
    "1D13F": "sixteenth rest",
    "1D140": "thirty-second rest",
    "1D141": "sixty-fourth rest",
    "2102": "complex numbers c",
    "210B": "hamiltonian h",
    "210E": "planck constant h",
    "210F": "h bar planck",
    "2111": "imaginary part im",
    "2113": "script l liter litre",
    "2115": "natural numbers n",
    "2118": "weierstrass p power set",
    "2119": "prime numbers p",
    "211A": "rational numbers q",
    "211B": "riemann r",
    "211C": "real part re",
    "211D": "real numbers r",
    "2124": "integers z",
    "2126": "ohm omega",
    "2127": "mho",
    "212B": "angstrom",
    "212E": "estimated",
    "2103": "celsius degree c",
    "2109": "fahrenheit degree f",
    "2121": "telephone tel",
    "2116": "numero number no",
    "2117": "phonogram sound recording copyright",
    "2120": "service mark sm",
    "2122": "trademark tm",
    "00A9": "copyright",
    "00AE": "registered",
    "00B5": "micro mu",
}


def fetch_ucd(cache: Path) -> dict[str, str]:
    """Return the UCD file contents, downloading anything missing."""
    cache.mkdir(parents=True, exist_ok=True)
    texts: dict[str, str] = {}
    for name in UCD_FILES:
        path = cache / name
        if not path.exists():
            url = UCD_URL + name
            print(f"downloading {url}")
            with urllib.request.urlopen(url) as response:
                path.write_bytes(response.read())
        texts[name] = path.read_text(encoding="utf-8")
    return texts


def parse_unicode_data(text: str) -> tuple[dict[int, tuple[str, str]], list[tuple[int, int, str]]]:
    entries: dict[int, tuple[str, str]] = {}
    ranges: list[tuple[int, int, str]] = []
    pending: tuple[int, str] | None = None
    for line in text.splitlines():
        if not line:
            continue
        fields = line.split(";")
        cp = int(fields[0], 16)
        name, category = fields[1], fields[2]
        if name.endswith(", First>"):
            pending = (cp, name[1:-8])
        elif name.endswith(", Last>"):
            if pending is None:
                raise ValueError(f"range end without start at U+{cp:04X}")
            ranges.append((pending[0], cp, pending[1]))
            pending = None
        else:
            entries[cp] = (name, category)
    return entries, ranges


def parse_aliases(text: str) -> dict[int, list[tuple[str, str]]]:
    aliases: dict[int, list[tuple[str, str]]] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        cp, alias, kind = line.split(";")[:3]
        aliases.setdefault(int(cp, 16), []).append((alias, kind))
    return aliases


def parse_blocks(text: str) -> list[tuple[int, int, str]]:
    blocks = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        span, name = line.split(";")
        start, end = span.strip().split("..")
        blocks.append((int(start, 16), int(end, 16), name.strip()))
    return blocks


def unicode_version(readme: str) -> str:
    match = re.search(
        r"version\s+(\d+\.\d+\.\d+)\s+of\s+the\s+Unicode Character Database",
        readme,
    )
    if not match:
        raise ValueError("could not read the UCD version from ReadMe.txt")
    return match.group(1)


def excluded_code_points(ranges: list[tuple[int, int, str]]) -> set[int]:
    """Code points that get an algorithmic name instead of a table row."""
    excluded: set[int] = set()
    for start, end, label in ranges:
        if label in ALGORITHMIC_RANGE_LABELS:
            excluded.update(range(start, end + 1))
    return excluded


def unicode_entries(
    entries: dict[int, tuple[str, str]],
    aliases: dict[int, list[tuple[str, str]]],
    ranges: list[tuple[int, int, str]],
) -> list[tuple[str, str, str, list[str]]]:
    excluded = excluded_code_points(ranges)
    rows: list[tuple[str, str, str, list[str]]] = []
    for cp in sorted(entries):
        if cp in excluded:
            continue
        name, category = entries[cp]
        if name == "<control>":
            # Control characters are not searchable by "<control>"; use the
            # formal ISO 6429 alias (NULL, ESCAPE, ...) and keep the rest of
            # the aliases as search terms.
            control = [alias for alias, kind in aliases.get(cp, []) if kind == "control"]
            if not control:
                continue
            display = control[0]
            extra = [alias for alias, _kind in aliases.get(cp, []) if alias != display]
        else:
            display = name
            extra = [alias for alias, _kind in aliases.get(cp, [])]
        rows.append((display, f"{cp:04X}", category, extra))
    print(f"unicode table: {len(rows)} named characters")
    return rows


def build_unicode_table(rows: list[tuple[str, str, str, list[str]]], version: str) -> str:
    lines = [
        f"# Unicode character names, generated from UnicodeData.txt (Unicode {version})",
        "# format: name <TAB> code-hex <TAB> general-category <TAB> aliases (| separated)",
        "# The name comes first so the plugin can search the file as plain text and",
        "# only parse the lines it actually shows.",
        "# Ranges with algorithmic names (CJK ideographs, Hangul, Tangut, ...) are",
        "# omitted here and named by the plugin on demand; query them by code point.",
    ]
    for name, hex_code, category, extra in rows:
        lines.append(f"{name}\t{hex_code}\t{category}\t{'|'.join(extra)}")
    return "\n".join(lines) + "\n"


INDEX_NAME_FIELD = 88
INDEX_RECORD = INDEX_NAME_FIELD + 1 + 6 + 2


def build_unicode_index(rows: list[tuple[str, str, str, list[str]]], first: int, last: int) -> bytes:
    index = bytearray()
    count = 0
    for name, hex_code, category, _extra in rows:
        codepoint = int(hex_code, 16)
        if codepoint < first or codepoint >= last:
            continue
        encoded = name.encode("ascii")
        if len(encoded) > INDEX_NAME_FIELD:
            raise SystemExit(f"name is longer than {INDEX_NAME_FIELD} bytes: {name!r}")
        index += encoded
        index += b"\0" * (INDEX_NAME_FIELD - len(encoded))
        index.append(len(encoded))
        index += f"{codepoint:06X}".encode("ascii")
        index += category.encode("ascii")
        count += 1
    if len(index) != count * INDEX_RECORD:
        raise SystemExit("index record size drifted from the documented layout")
    print(f"unicode index {first:04X}-{last - 1:04X}: {count} records, {len(index)} bytes")
    return bytes(index)


# noctalia.readFileAsync() caps a read at 4 MiB, so the records are split by
# code point range. Each range is far below the cap and the whole table is
# searched by scanning the files one after another.
INDEX_SEGMENTS = [
    ("unicode-0.idx", 0x000000, 0x010000),
    ("unicode-1.idx", 0x010000, 0x020000),
    ("unicode-2.idx", 0x020000, 0x110000),
]


def build_alias_table(
    unicode_rows: list[tuple[str, str, str, list[str]]],
    aliases: dict[int, list[tuple[str, str]]],
    version: str,
) -> str:
    by_code = {int(hex_code, 16): (name, category) for name, hex_code, category, _extra in unicode_rows}
    rows: set[tuple[str, int]] = set()
    for cp, items in aliases.items():
        if cp not in by_code:
            continue
        for alias, _kind in items:
            rows.add((alias, cp))
    lines = [
        f"# Formal Unicode name aliases, generated from NameAliases.txt (Unicode {version})",
        "# format: alias <TAB> code-hex <TAB> name <TAB> general-category",
        "# Self-contained so an alias search never has to look the character up.",
    ]
    for alias, cp in sorted(rows):
        name, category = by_code[cp]
        lines.append(f"{alias}\t{cp:04X}\t{name}\t{category}")
    print(f"aliases.tsv: {len(rows)} aliases")
    return "\n".join(lines) + "\n"


def build_popular_table(entries: dict[int, tuple[str, str]], version: str) -> str:
    lines = [
        f"# /unicode empty-query characters, generated from UnicodeData.txt (Unicode {version})",
        "# format: name <TAB> code-hex <TAB> general-category <TAB> aliases (| separated)",
    ]
    for raw in POPULAR:
        cp = int(raw, 16)
        if cp not in entries:
            raise SystemExit(f"popular character U+{cp:04X} is not assigned")
        name, category = entries[cp]
        if name == "<control>":
            raise SystemExit(f"popular character U+{cp:04X} is a control character")
        lines.append(f"{name}\t{cp:04X}\t{category}\t")
    print(f"popular.tsv: {len(POPULAR)} characters")
    return "\n".join(lines) + "\n"


def build_block_table(blocks: list[tuple[int, int, str]], version: str) -> str:
    lines = [
        f"# Unicode blocks, generated from Blocks.txt (Unicode {version})",
        "# format: start-hex <TAB> end-hex <TAB> block name",
    ]
    for start, end, name in blocks:
        lines.append(f"{start:04X}\t{end:04X}\t{name}")
    print(f"blocks.tsv: {len(blocks)} blocks")
    return "\n".join(lines) + "\n"


def build_symbol_table(
    entries: dict[int, tuple[str, str]],
    excluded: set[int],
    version: str,
) -> str:
    seen: dict[int, str] = {}
    rows: list[str] = []
    for label, code_points in GROUPS:
        for raw in code_points:
            cp = int(raw, 16)
            if cp in seen:
                raise SystemExit(f"duplicate symbol U+{cp:04X} in '{seen[cp]}' and '{label}'")
            seen[cp] = label
            if cp in excluded:
                raise SystemExit(f"U+{cp:04X} ({label}) has an algorithmic name; pick another symbol")
            if cp not in entries:
                raise SystemExit(f"U+{cp:04X} ({label}) is not assigned in UnicodeData.txt")
            name, _category = entries[cp]
            if name == "<control>":
                raise SystemExit(f"U+{cp:04X} ({label}) is a control character")
            aliases = SYMBOL_ALIASES.get(raw.upper(), "")
            rows.append(f"{cp:04X}\t{label}\t{name}\t{aliases}")

    unknown = sorted(set(SYMBOL_ALIASES) - {row.split("\t")[0] for row in rows})
    if unknown:
        raise SystemExit("SYMBOL_ALIASES mentions code points outside GROUPS: " + ", ".join(unknown))

    print(f"symbols.tsv: {len(rows)} symbols in {len(GROUPS)} groups")
    lines = [
        f"# Curated symbols for /symb, validated against UnicodeData.txt (Unicode {version})",
        "# format: code-hex <TAB> group <TAB> name <TAB> extra search aliases",
    ]
    return "\n".join(lines + rows) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--cache",
        type=Path,
        default=DEFAULT_CACHE,
        help="directory holding the downloaded UCD files (default: tools/.ucd-cache)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="build in memory and compare with the committed tables without writing",
    )
    args = parser.parse_args()

    texts = fetch_ucd(args.cache)
    version = unicode_version(texts["ReadMe.txt"])
    entries, ranges = parse_unicode_data(texts["UnicodeData.txt"])
    aliases = parse_aliases(texts["NameAliases.txt"])
    blocks = parse_blocks(texts["Blocks.txt"])

    unicode_rows = unicode_entries(entries, aliases, ranges)
    outputs = {
        "unicode.tsv": build_unicode_table(unicode_rows, version).encode("utf-8"),
        "aliases.tsv": build_alias_table(unicode_rows, aliases, version).encode("utf-8"),
        "popular.tsv": build_popular_table(entries, version).encode("utf-8"),
        "blocks.tsv": build_block_table(blocks, version).encode("utf-8"),
        "symbols.tsv": build_symbol_table(entries, excluded_code_points(ranges), version).encode("utf-8"),
    }
    for filename, first, last in INDEX_SEGMENTS:
        outputs[filename] = build_unicode_index(unicode_rows, first, last)

    if not args.check:
        stale = PLUGIN_DATA / "unicode.idx"
        if stale.exists():
            stale.unlink()
            print(f"removed obsolete {stale.relative_to(REPO_ROOT)}")

    status = 0
    for filename, content in outputs.items():
        path = PLUGIN_DATA / filename
        if args.check:
            existing = path.read_bytes() if path.exists() else b""
            if existing != content:
                print(f"{path.relative_to(REPO_ROOT)} is out of date", file=sys.stderr)
                status = 1
            else:
                print(f"{path.relative_to(REPO_ROOT)} is up to date")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            print(f"wrote {path.relative_to(REPO_ROOT)}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
