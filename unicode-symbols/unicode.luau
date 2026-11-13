--!nonstrict
-- /unicode - search every named Unicode character.
--
-- Query forms, all handled in onQuery:
--   arrow            name search (words can be in any order)
--   2192 / u+2192    code point lookup (4-6 hex digits)
--   →                paste or type the character itself
--
-- Selecting a result copies the character. The data covers every named code
-- point from UnicodeData.txt except the ranges with algorithmic names (CJK
-- ideographs, Hangul syllables, Tangut, private use); those are still
-- reachable by code point or by pasting the character and are named on demand
-- by lib/util.luau.
--
-- Noctalia gives a callback 25 ms of CPU time, which is far too little to
-- parse 41k text rows. data/unicode-N.idx therefore holds fixed 97-byte
-- records (name, length, six-digit code point, category), split into three
-- files by code point so each stays under the 4 MiB readFileAsync limit. A
-- word is found by searching an index as plain text; the hit position gives
-- the record by arithmetic, so only matching characters are decoded. The
-- index is loaded asynchronously at plugin start; a query that arrives first
-- shows a loading row and is answered from the read callback.

local util = require("./lib/util.luau")

local DEFAULT_LIMIT = 50
local BROWSE_LIMIT = 40
-- Upper bound on candidate records inspected for one query. Long queries
-- finish at their handful of matches; the cap only matters for one- or
-- two-letter searches.
local CANDIDATE_CAP = 1200
-- Time we allow the scan, starting when the query callback is entered. The
-- host's budget is 25 ms; the margin covers row building after the scan.
local TIME_BUDGET = 0.014

local RECORD_SIZE = 97
local NAME_FIELD = 88
local LENGTH_OFFSET = 88 -- 0-based within the record
local HEX_OFFSET = 89
local CATEGORY_OFFSET = 95

local SEGMENT_FIRST = { 0x000000, 0x010000, 0x020000 }
local SEGMENT_COUNT = 3

local indexData = { nil, nil, nil }
local segmentState = { "idle", "idle", "idle" }
local segmentsReady = 0
local pendingQuery = nil
local blocks = nil
local popular = nil
local aliases = nil
local hexCache = {}

local function hex6(codepoint)
  return string.format("%06X", codepoint)
end

local function parseRow(line)
  if line == nil then
    return nil
  end
  local name, hex, category = line:match("^([^\t]*)\t(%x+)\t(%a%a)")
  if name == nil then
    return nil
  end
  return { name = name, hex = hex, category = category }
end

-- Small tables: read synchronously when the entry starts, so the empty query
-- and subtitles work before the index has finished loading.
local function loadMetadata()
  if blocks ~= nil then
    return
  end

  local blockText = noctalia.readFile("data/blocks.tsv")
  if blockText ~= nil then
    blocks = {}
    for line in blockText:gmatch("[^\n]+") do
      if line:sub(1, 1) ~= "#" then
        local startHex, stopHex, name = line:match("^(%x+)\t(%x+)\t(.+)$")
        if startHex ~= nil then
          blocks[#blocks + 1] = {
            start = tonumber(startHex, 16),
            stop = tonumber(stopHex, 16),
            name = name,
          }
        end
      end
    end
  end

  local popularText = noctalia.readFile("data/popular.tsv")
  if popularText ~= nil then
    popular = {}
    for line in popularText:gmatch("[^\n]+") do
      if line:sub(1, 1) ~= "#" then
        local row = parseRow(line)
        if row ~= nil then
          popular[#popular + 1] = row
        end
      end
    end
  end

  aliases = {}
  local aliasText = noctalia.readFile("data/aliases.tsv")
  if aliasText ~= nil then
    for line in aliasText:gmatch("[^\n]+") do
      if line:sub(1, 1) ~= "#" then
        local alias, hex, name, category = line:match("^([^\t]*)\t(%x+)\t([^\t]*)\t(%a%a)$")
        if alias ~= nil then
          -- Index records use six hex digits; normalize here so the alias
          -- rows deduplicate against name-search rows.
          aliases[#aliases + 1] = {
            alias = alias,
            name = name,
            hex = hex6(tonumber(hex, 16)),
            category = category,
          }
        end
      end
    end
  end
end

local function maxResults()
  local configured = noctalia.getConfig("max_results")
  if type(configured) == "number" then
    return math.max(5, math.min(200, math.floor(configured)))
  end
  return DEFAULT_LIMIT
end

local function notifyOnCopy()
  return noctalia.getConfig("notify_on_copy") == true
end

local function segmentFor(codepoint)
  if codepoint < SEGMENT_FIRST[2] then
    return 1
  end
  if codepoint < SEGMENT_FIRST[3] then
    return 2
  end
  return 3
end

local function recordAt(segment, base)
  local data = indexData[segment]
  if data == nil then
    return nil
  end
  local length = data:byte(base + LENGTH_OFFSET + 1)
  if length == nil or length == 0 then
    return nil
  end
  return {
    name = data:sub(base + 1, base + length),
    hex = data:sub(base + HEX_OFFSET + 1, base + HEX_OFFSET + 6),
    category = data:sub(base + CATEGORY_OFFSET + 1, base + CATEGORY_OFFSET + 2),
  }
end

-- Code point columns are six aligned digits, so a plain-text search followed
-- by an alignment check identifies the record without parsing anything.
local function fetchEntry(codepoint)
  local segment = segmentFor(codepoint)
  local data = indexData[segment]
  if data == nil then
    return nil
  end
  local hex = hex6(codepoint)
  local cached = hexCache[hex]
  if cached == nil then
    local base = nil
    local search = 1
    while true do
      local position = data:find(hex, search, true)
      if position == nil then
        break
      end
      if (position - 1) % RECORD_SIZE == HEX_OFFSET then
        base = position - 1 - HEX_OFFSET
        break
      end
      search = position + 1
    end
    if base == nil then
      cached = false
    else
      cached = { segment = segment, base = base }
    end
    hexCache[hex] = cached
  end
  if cached == false then
    return nil
  end
  return recordAt(cached.segment, cached.base)
end

local function entryForCodepoint(codepoint)
  if not util.isValidScalar(codepoint) then
    return nil
  end

  local entry = fetchEntry(codepoint)
  if entry == nil then
    local name, category = util.generatedFor(codepoint)
    if name == nil then
      name = noctalia.tr("unicode.unassigned")
      category = "Cn"
    end
    entry = { name = name, hex = hex6(codepoint), category = category }
  end
  return entry
end

local function subtitleFor(entry)
  local codepoint = tonumber(entry.hex, 16)
  local subtitle = "U+" .. util.hex(codepoint)
  if blocks ~= nil then
    local block = util.blockAt(blocks, codepoint)
    if block ~= nil then
      subtitle = subtitle .. " · " .. block
    end
  end
  return subtitle
end

local function rowFor(entry)
  local codepoint = tonumber(entry.hex, 16)
  return {
    id = util.utf8Encode(codepoint),
    title = entry.name,
    subtitle = subtitleFor(entry),
    badge = util.badgeFor(codepoint, entry.category),
  }
end

local function addRow(rows, seen, entry)
  if entry == nil or seen[entry.hex] then
    return
  end
  seen[entry.hex] = true
  rows[#rows + 1] = rowFor(entry)
end

local function longestToken(tokens)
  local best = tokens[1]
  for i = 2, #tokens do
    if #tokens[i] > #best then
      best = tokens[i]
    end
  end
  return best
end

-- Search every loaded index for one word, decode the records it starts in,
-- and rank them. Hits that are not inside a name field are skipped by
-- arithmetic (no parsing). `deadline` is an os.clock() value.
local function scan(needle, normalized, tokens, limit, deadline, candidates, seen)
  local inspected = 0
  local steps = 0

  for segment = 1, SEGMENT_COUNT do
    local data = indexData[segment]
    if data ~= nil then
      local position = 0
      while inspected < CANDIDATE_CAP do
        position = data:find(needle, position + 1, true)
        if position == nil then
          break
        end
        steps = steps + 1
        if steps % 200 == 0 and (steps > 50000 or os.clock() > deadline) then
          return candidates
        end

        local offset = (position - 1) % RECORD_SIZE
        if offset < NAME_FIELD then
          local base = position - 1 - offset
          local key = segment * 10000000 + base
          if not seen[key] then
            local entry = recordAt(segment, base)
            if entry ~= nil then
              local score = util.score(entry.name, normalized, tokens)
              if score ~= nil then
                inspected = inspected + 1
                seen[key] = true
                util.insertCandidate(candidates, { entry = entry, score = score }, limit)
              end
            end
          end
        end
      end
    end
    if inspected >= CANDIDATE_CAP or os.clock() > deadline then
      break
    end
  end

  return candidates
end

local function addAliasMatches(candidates, normalized, tokens, limit, seen, deadline)
  if aliases == nil or normalized == "" then
    return
  end
  for i = 1, #aliases do
    local alias = aliases[i]
    if not seen[alias.hex] then
      local score = util.score(alias.alias, normalized, tokens)
      if score ~= nil then
        seen[alias.hex] = true
        -- Aliases rank just below an exact formal name. The row shows the
        -- formal name; the alias only widened the search.
        local entry = { name = alias.name, hex = alias.hex, category = alias.category }
        util.insertCandidate(candidates, { entry = entry, score = score - 1 }, limit)
      end
    end
    if i % 128 == 0 and os.clock() > deadline then
      break
    end
  end
end

local function browseRows()
  local rows = {
    {
      id = "",
      title = noctalia.tr("unicode.hint"),
      subtitle = noctalia.tr("unicode.hint_subtitle"),
      glyph = "info-circle",
    },
  }
  local seen = {}
  for i = 1, #(popular or {}) do
    if #rows > BROWSE_LIMIT then
      break
    end
    local entry = popular[i]
    if not seen[entry.hex] then
      seen[entry.hex] = true
      local row = rowFor(entry)
      row.subtitle = noctalia.tr("unicode.popular") .. " · " .. subtitleFor(entry)
      rows[#rows + 1] = row
    end
  end
  return rows
end

local function searchRows(query, deadline)
  local rows = {}
  local seen = {}
  local rawQuery = util.trim(query)

  -- Code point lookup: 2192, U+2192, 0x2192. A query under four hex digits
  -- stays a name search so "abc" still finds names containing those letters.
  local codepoint = util.parseCodepoint(rawQuery)
  if codepoint ~= nil then
    addRow(rows, seen, entryForCodepoint(codepoint))
  end

  -- A single typed/pasted character, or any query containing non-ASCII
  -- characters, resolves the characters themselves before the name search.
  local decoded = util.decodeAll(rawQuery)
  local hasNonAscii = rawQuery:find("[\128-\255]") ~= nil
  if #decoded > 0 and #decoded <= 8 and (#decoded == 1 or hasNonAscii) then
    for i = 1, #decoded do
      addRow(rows, seen, entryForCodepoint(decoded[i]))
    end
  end

  local normalized = util.normalize(rawQuery)
  if normalized ~= "" then
    local limit = maxResults()
    local tokens = util.tokens(normalized)
    local candidates

    -- Names usually contain the words in the order they are typed, so try
    -- the whole phrase first; it hits far fewer records than a single word.
    candidates = {}
    local candidateKeys = {}
    if #tokens > 1 then
      -- The words are usually adjacent in a Unicode name ("greek small
      -- letter omega"), which is cheap to scan for. If that does not fill
      -- the list, check the longest word too so word-order variants and
      -- names with different filler still show up.
      scan(normalized, normalized, tokens, limit, deadline, candidates, candidateKeys)
      if #candidates < limit then
        scan(longestToken(tokens), normalized, tokens, limit, deadline, candidates, candidateKeys)
      end
    else
      scan(normalized, normalized, tokens, limit, deadline, candidates, candidateKeys)
    end

    local candidateSeen = {}
    for i = 1, #candidates do
      candidateSeen[candidates[i].entry.hex] = true
    end
    addAliasMatches(candidates, normalized, tokens, limit, candidateSeen, deadline)
    for i = 1, #candidates do
      addRow(rows, seen, candidates[i].entry)
    end
  end

  if #rows == 0 then
    rows[1] = {
      id = "",
      title = noctalia.tr("no_matches"),
      subtitle = noctalia.tr("unicode.no_matches_hint"),
      glyph = "mood-empty",
    }
  end
  return rows
end

local function runQuery(query)
  if util.trim(query) == "" then
    launcher.setResults(query, browseRows())
  else
    launcher.setResults(query, searchRows(query, os.clock() + TIME_BUDGET))
  end
end

local function startSegment(segment)
  if segmentState[segment] ~= "idle" then
    return
  end
  segmentState[segment] = "loading"
  local accepted = noctalia.readFileAsync(string.format("data/unicode-%d.idx", segment - 1), function(contents)
    if contents == nil then
      segmentState[segment] = "error"
      return
    end
    indexData[segment] = contents
    segmentState[segment] = "ready"
    segmentsReady = segmentsReady + 1
    if segmentsReady == SEGMENT_COUNT and pendingQuery ~= nil then
      local query = pendingQuery
      pendingQuery = nil
      runQuery(query)
    end
  end)
  if not accepted then
    segmentState[segment] = "idle"
  end
end

loadMetadata()
for segment = 1, SEGMENT_COUNT do
  startSegment(segment)
end

function onQuery(query)
  if util.trim(query) == "" then
    launcher.setResults(query, browseRows())
    return
  end

  if segmentsReady < SEGMENT_COUNT then
    for segment = 1, SEGMENT_COUNT do
      if segmentState[segment] == "error" then
        launcher.setResults(query, {
          {
            id = "",
            title = noctalia.tr("unicode.data_error"),
            subtitle = noctalia.tr("unicode.data_error_hint"),
            glyph = "alert-triangle",
          },
        })
        return
      end
    end
    pendingQuery = query
    launcher.setResults(query, {
      {
        id = "",
        title = noctalia.tr("unicode.loading"),
        subtitle = noctalia.tr("unicode.loading_hint"),
        glyph = "loader",
      },
    })
    return
  end

  launcher.setResults(query, searchRows(query, os.clock() + TIME_BUDGET))
end

function onActivate(id)
  if id == nil or id == "" then
    return
  end

  local copied = util.decodeAll(id)
  local label = id
  if #copied == 1 then
    local entry = fetchEntry(copied[1])
    if entry ~= nil then
      label = entry.name .. " (U+" .. util.hex(copied[1]) .. ")"
    elseif util.generatedFor(copied[1]) ~= nil then
      label = util.generatedFor(copied[1]) .. " (U+" .. util.hex(copied[1]) .. ")"
    end
  end

  noctalia.copyToClipboard(id, "text/plain")
  if notifyOnCopy() then
    noctalia.notify(noctalia.tr("title"), noctalia.tr("notify.copied", { name = label }))
  end
end
