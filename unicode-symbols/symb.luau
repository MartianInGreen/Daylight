--!nonstrict
-- /symb - browse and search a curated set of common symbols.
--
-- The set is grouped (Arrows, Math, Sets & Logic, Currency, ...). A query
-- matches the Unicode name, the everyday aliases ("times", "cmd", "gbp"),
-- and the group name, so `/symb currency` lists the currency group. Selecting
-- a result copies the character.
--
-- The table is small, but it is still read with readFileAsync() at plugin
-- start so the first query never pays for the parse inside its 25 ms
-- callback. A query that arrives before the read completes shows a loading
-- row and is answered from the callback.

local util = require("./lib/util.luau")

local DEFAULT_LIMIT = 50
local BROWSE_LIMIT = 1000
local TIME_BUDGET = 0.014

-- Parallel arrays, filled from data/symbols.tsv.
local codePoints = {}
local names = {}
local groups = {}
local aliasLists = {}
local rowCache = {}
local byCodePoint = {}

local loaded = false
local loadError = nil
local syncFallback = false
local pendingQuery = nil

local function applyTable(raw)
  for line in raw:gmatch("[^\n]+") do
    if line:sub(1, 1) ~= "#" then
      local hex, group, name, extra = line:match("^(%x+)\t([^\t]+)\t([^\t]*)\t([^\t]*)$")
      if hex ~= nil then
        local codepoint = tonumber(hex, 16)
        if codepoint ~= nil then
          local index = #codePoints + 1
          codePoints[index] = codepoint
          names[index] = name
          groups[index] = group
          if extra ~= "" then
            local list = {}
            for alias in extra:gmatch("%S+") do
              list[#list + 1] = alias:upper()
            end
            aliasLists[index] = list
          end
          byCodePoint[codepoint] = index
        end
      end
    end
  end
end

local function loadTable()
  if loaded then
    return true
  end
  if loadError ~= nil then
    return false
  end
  local raw = noctalia.readFile("data/symbols.tsv")
  if raw == nil then
    loadError = "data/symbols.tsv"
    return false
  end
  applyTable(raw)
  if #codePoints == 0 then
    loadError = "data/symbols.tsv"
    return false
  end
  loaded = true
  return true
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

local function rowForIndex(index)
  local cached = rowCache[index]
  if cached ~= nil then
    return cached
  end
  local codepoint = codePoints[index]
  local row = {
    id = util.utf8Encode(codepoint),
    title = names[index],
    subtitle = groups[index] .. " · U+" .. util.hex(codepoint),
    badge = util.utf8Encode(codepoint),
    category = groups[index],
  }
  rowCache[index] = row
  return row
end

local function addRow(rows, seen, index)
  if index == nil or seen[index] then
    return
  end
  seen[index] = true
  rows[#rows + 1] = rowForIndex(index)
end

local function browseRows()
  local rows = {}
  for index = 1, #codePoints do
    if #rows >= BROWSE_LIMIT then
      break
    end
    rows[#rows + 1] = rowForIndex(index)
  end
  return rows
end

local function searchRows(query)
  local rows = {}
  local seen = {}
  local raw = util.trim(query)
  local deadline = os.clock() + TIME_BUDGET

  local codepoint = util.parseCodepoint(raw)
  if codepoint ~= nil then
    addRow(rows, seen, byCodePoint[codepoint])
  end

  local decoded = util.decodeAll(raw)
  local hasNonAscii = raw:find("[\128-\255]") ~= nil
  if #decoded > 0 and #decoded <= 8 and (#decoded == 1 or hasNonAscii) then
    for i = 1, #decoded do
      addRow(rows, seen, byCodePoint[decoded[i]])
    end
  end

  local normalized = util.normalize(raw)
  if normalized ~= "" then
    local tokens = util.tokens(normalized)
    local limit = maxResults()
    local candidates = {}
    for index = 1, #codePoints do
      local score = util.score(names[index], normalized, tokens)
      local groupScore = util.score(groups[index]:upper(), normalized, tokens)
      if groupScore ~= nil and (score == nil or groupScore > score) then
        score = groupScore
      end
      local aliasScore = util.bestAliasScore(aliasLists[index], normalized, tokens)
      if aliasScore ~= nil and (score == nil or aliasScore > score) then
        score = aliasScore
      end
      if score ~= nil then
        util.insertCandidate(candidates, { index = index, score = score }, limit)
      end
      if index % 256 == 0 and os.clock() > deadline then
        break
      end
    end
    for i = 1, #candidates do
      addRow(rows, seen, candidates[i].index)
    end
  end

  if #rows == 0 then
    rows[1] = {
      id = "",
      title = noctalia.tr("no_matches"),
      subtitle = noctalia.tr("symb.no_matches_hint"),
      glyph = "mood-empty",
    }
  end
  return rows
end

local function runQuery(query)
  if util.trim(query) == "" then
    launcher.setResults(query, browseRows())
    return
  end
  launcher.setResults(query, searchRows(query))
end

local function onLoaded(contents)
  if contents == nil then
    loadError = "data/symbols.tsv"
    return
  end
  applyTable(contents)
  if #codePoints == 0 then
    loadError = "data/symbols.tsv"
    return
  end
  loaded = true
  if pendingQuery ~= nil then
    local query = pendingQuery
    pendingQuery = nil
    runQuery(query)
  end
end

if not noctalia.readFileAsync("data/symbols.tsv", onLoaded) then
  -- The async queue is full (four reads per runtime). This table is tiny;
  -- fall back to reading it on the first query instead of failing.
  syncFallback = true
end

function onQuery(query)
  if not loaded then
    if syncFallback and loadTable() then
      runQuery(query)
      return
    end
    if loadError ~= nil then
      launcher.setResults(query, {
        {
          id = "",
          title = noctalia.tr("symb.data_error"),
          subtitle = noctalia.tr("symb.data_error_hint"),
          glyph = "alert-triangle",
        },
      })
      return
    end
    pendingQuery = query
    launcher.setResults(query, {
      {
        id = "",
        title = noctalia.tr("symb.loading"),
        subtitle = noctalia.tr("symb.loading_hint"),
        glyph = "loader",
      },
    })
    return
  end

  runQuery(query)
end

function onActivate(id)
  if id == nil or id == "" then
    return
  end

  local decoded = util.decodeAll(id)
  local label = id
  if #decoded == 1 then
    local index = byCodePoint[decoded[1]]
    if index ~= nil then
      label = names[index]
    end
  end

  noctalia.copyToClipboard(id, "text/plain")
  if notifyOnCopy() then
    noctalia.notify(noctalia.tr("title"), noctalia.tr("notify.copied", { name = label }))
  end
end
