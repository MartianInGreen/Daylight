-- Tests for the unicode-symbols launcher providers.
--
-- Run from the repository root with the Lua 5.4 interpreter:
--
--   lua5.4 tests/run.lua
--
-- The entry scripts are plain Lua plus `--!nonstrict` comments, so they run
-- under Lua 5.4 with a small host stub. That exercises the real ranking,
-- table parsing, UTF-8 helpers, and activation path without starting Noctalia.

local function sourcePath()
  if arg ~= nil and arg[0] ~= nil then
    return arg[0]
  end
  if debug.info ~= nil then
    return debug.info(1, "s")
  end
  return debug.getinfo(1, "S").source
end

local scriptPath = sourcePath():gsub("^[@=]", "")
local scriptDir = scriptPath:match("^(.*)/tests/[^/]+$")
if scriptDir == nil then
  scriptDir = "."
elseif scriptDir == "" then
  scriptDir = "."
end
local pluginDir = scriptDir .. "/unicode-symbols"
if io.open(pluginDir .. "/plugin.toml", "rb") == nil then
  io.stderr:write("run this script from the repository root (lua5.4 tests/run.lua)\n")
  os.exit(2)
end

local failures = 0
local assertions = 0

local function fail(message)
  failures = failures + 1
  io.stderr:write("FAIL: " .. message .. "\n")
end

local function check(condition, message)
  assertions = assertions + 1
  if not condition then
    fail(message)
  end
end

local function equal(actual, expected, message)
  assertions = assertions + 1
  if actual ~= expected then
    fail(message .. " (expected " .. tostring(expected) .. ", got " .. tostring(actual) .. ")")
  end
end

-- ── host stub ───────────────────────────────────────────────────────────

local settings = { notify_on_copy = false, max_results = 50 }
local copied = {}
local notifications = {}
local lastQuery = nil
local lastResults = nil

local function readFile(path)
  local file = io.open(pluginDir .. "/" .. path, "rb")
  if file == nil then
    return nil, "missing " .. path
  end
  local contents = file:read("a")
  file:close()
  return contents
end

local host = {
  readFile = readFile,
  -- The provider starts three asynchronous index reads when it loads. The
  -- test completes them immediately, in order, with the same signature.
  readFileAsync = function(path, callback)
    local contents, err = readFile(path)
    callback(contents, err)
    return true
  end,
  getConfig = function(key)
    return settings[key]
  end,
  tr = function(key, subst)
    local text = key
    if subst ~= nil and subst.name ~= nil then
      text = text .. " " .. subst.name
    end
    return text
  end,
  copyToClipboard = function(text, mime)
    copied[#copied + 1] = { text = text, mime = mime }
    return true
  end,
  notify = function(title, body)
    notifications[#notifications + 1] = { title = title, body = body }
  end,
  notifyError = function(title, body)
    notifications[#notifications + 1] = { title = title, body = body, error = true }
  end,
  log = function() end,
  fuzzyScore = function() return nil end,
}

local launcher = {
  setResults = function(query, results)
    lastQuery = query
    lastResults = results
  end,
  setQuery = function() end,
}

noctalia = host
_G.noctalia = host
_G.launcher = launcher

-- Luau resolves require() relative to the calling file and caches modules per
-- entry. The test only loads top-level modules, so resolving against the
-- plugin directory is equivalent.
local moduleCache = {}
function require(path)
  local relative = path:gsub("^%./", "")
  if moduleCache[relative] == nil then
    local chunk = assert(loadfile(pluginDir .. "/" .. relative))
    moduleCache[relative] = chunk()
  end
  return moduleCache[relative]
end

local function loadEntry(filename)
  moduleCache = {}
  lastQuery = nil
  lastResults = nil
  onQuery = nil
  onActivate = nil
  local chunk = assert(loadfile(pluginDir .. "/" .. filename))
  chunk()
  check(type(onQuery) == "function", filename .. " defines onQuery")
  check(type(onActivate) == "function", filename .. " defines onActivate")
  return onQuery, onActivate
end

local function query(onQuery, text)
  onQuery(text)
  check(lastQuery == text, "setResults echoes the query " .. string.format("%q", text))
  return lastResults or {}
end

-- ── /unicode ────────────────────────────────────────────────────────────

local unicodeQuery, unicodeActivate = loadEntry("unicode.luau")

do
  local rows = query(unicodeQuery, "")
  check(#rows > 20, "empty query lists popular characters")
  equal(rows[1].title, "unicode.hint", "empty query starts with a hint row")
  equal(rows[2].badge, "→", "the first popular character is a rightwards arrow")
end

do
  local rows = query(unicodeQuery, "2192")
  equal(rows[1].title, "RIGHTWARDS ARROW", "U+2192 resolves by code point")
  equal(rows[1].badge, "→", "the code point row shows the character")
  equal(rows[1].subtitle, "U+2192 · Arrows", "the code point row shows the block")
end

do
  local rows = query(unicodeQuery, "U+1F600")
  equal(rows[1].title, "GRINNING FACE", "U+1F600 resolves")
  equal(rows[1].badge, "😀", "the emoji is used as the row badge")
end

do
  local rows = query(unicodeQuery, "→")
  equal(rows[1].title, "RIGHTWARDS ARROW", "pasting a character resolves it")
end

do
  local rows = query(unicodeQuery, "latin capital letter a")
  equal(rows[1].title, "LATIN CAPITAL LETTER A", "an exact name ranks first")
end

do
  local rows = query(unicodeQuery, "rightwards arrow")
  check(#rows >= 1, "name search returns rows")
  local seen = false
  for i = 1, math.min(#rows, 20) do
    if rows[i].title == "RIGHTWARDS ARROW" then
      seen = true
    end
  end
  check(seen, "RIGHTWARDS ARROW is in the top 20 for 'rightwards arrow'")
end

do
  local rows = query(unicodeQuery, "arrow")
  local seen = false
  for i = 1, math.min(#rows, 20) do
    if rows[i].title == "RIGHTWARDS ARROW" then
      seen = true
    end
  end
  check(seen, "RIGHTWARDS ARROW is in the top 20 for 'arrow'")
end

do
  local rows = query(unicodeQuery, "4E00")
  equal(rows[1].title, "CJK UNIFIED IDEOGRAPH-4E00", "CJK ideographs get an algorithmic name")
  equal(rows[1].badge, "一", "the ideograph renders as the badge")
end

do
  local rows = query(unicodeQuery, "AC00")
  equal(rows[1].title, "HANGUL SYLLABLE GA", "Hangul syllables get an algorithmic name")
end

do
  local rows = query(unicodeQuery, "combining acute accent")
  equal(rows[1].title, "COMBINING ACUTE ACCENT", "combining marks are searchable")
  equal(rows[1].badge, "◌́", "combining marks are shown on a dotted circle")
end

do
  local rows = query(unicodeQuery, "tab")
  local matches = 0
  for i = 1, #rows do
    if rows[i].subtitle:match("^U%+0009 ") or rows[i].subtitle == "U+0009" then
      matches = matches + 1
    end
  end
  equal(matches, 1, "an alias match does not duplicate the same character")
end

do
  local rows = query(unicodeQuery, "greek omega")
  local seen = false
  for i = 1, math.min(#rows, 20) do
    if rows[i].title == "GREEK SMALL LETTER OMEGA" then
      seen = true
    end
  end
  check(seen, "GREEK SMALL LETTER OMEGA is in the top 20 for 'greek omega'")
end

do
  local rows = query(unicodeQuery, "zzzzqqqq")
  equal(rows[1].title, "no_matches", "an unknown name reports no matches")
end

do
  settings.max_results = 5
  local rows = query(unicodeQuery, "arrow")
  check(#rows <= 6, "max_results bounds the name matches (exact rows may add one)")
  settings.max_results = 50
end

do
  copied = {}
  notifications = {}
  settings.notify_on_copy = false
  unicodeActivate("→")
  equal(#copied, 1, "activation copies the character")
  equal(copied[1].text, "→", "the copied text is the character")
  equal(copied[1].mime, "text/plain", "the clipboard MIME type is text/plain")
  equal(#notifications, 0, "no notification when notify_on_copy is off")

  settings.notify_on_copy = true
  unicodeActivate("→")
  equal(#notifications, 1, "a notification is shown when enabled")
  check(notifications[1].body:find("RIGHTWARDS ARROW", 1, true) ~= nil,
    "the notification names the copied character")
  settings.notify_on_copy = false
end

do
  copied = {}
  unicodeActivate("")
  equal(#copied, 0, "activating a hint row does nothing")
end

-- ── /symb ───────────────────────────────────────────────────────────────

local symbQuery, symbActivate = loadEntry("symb.luau")

do
  local rows = query(symbQuery, "")
  equal(#rows, 728, "the empty query lists every symbol")
  equal(rows[1].category, "Arrows", "browse order starts with Arrows")
  equal(rows[#rows].category, "Letterlike", "browse order ends with Letterlike")
end

do
  local rows = query(symbQuery, "currency")
  check(#rows >= 30, "the currency group is searchable by name")
  equal(rows[1].category, "Currency", "currency results carry the category label")
end

do
  local rows = query(symbQuery, "times")
  equal(rows[1].badge, "×", "an alias finds the multiplication sign")
end

do
  local rows = query(symbQuery, "cmd")
  equal(rows[1].badge, "⌘", "an alias finds the command key symbol")
end

do
  local rows = query(symbQuery, "2192")
  equal(rows[1].badge, "→", "a code point finds the curated symbol")
end

do
  local rows = query(symbQuery, "€")
  equal(rows[1].title, "EURO SIGN", "pasting a symbol resolves it")
end

do
  local rows = query(symbQuery, "zzzzqqqq")
  equal(rows[1].title, "no_matches", "an unknown symbol reports no matches")
end

do
  copied = {}
  settings.notify_on_copy = false
  symbActivate("→")
  equal(#copied, 1, "activating a symbol copies it")
  equal(copied[1].text, "→", "the copied text is the symbol")
  equal(copied[1].mime, "text/plain", "the symbol clipboard MIME type is text/plain")
end

-- The index loads asynchronously; a query that arrives first must show a
-- loading row and then be answered from the read callbacks.
do
  local deferred = {}
  local realAsync = noctalia.readFileAsync
  noctalia.readFileAsync = function(path, callback)
    deferred[#deferred + 1] = { path = path, callback = callback }
    return true
  end

  moduleCache = {}
  loadfile(pluginDir .. "/unicode.luau")()

  local loadingRows = query(onQuery, "arrow")
  equal(loadingRows[1].title, "unicode.loading", "a query during the async load shows a loading row")
  equal(#deferred, 3, "the three index segments are requested asynchronously")

  local browseRows = query(onQuery, "")
  check(browseRows[1].title == "unicode.hint", "the empty query works while the index is still loading")
  local browseTable = lastResults

  for i = 1, 2 do
    deferred[i].callback(assert(readFile(deferred[i].path)), nil)
  end
  check(lastResults == browseTable, "results wait for every segment")

  deferred[3].callback(assert(readFile(deferred[3].path)), nil)
  local ready = false
  for i = 1, math.min(#lastResults, 20) do
    if lastResults[i].title == "RIGHTWARDS ARROW" then
      ready = true
    end
  end
  check(ready, "the pending query is answered once the index is ready")

  noctalia.readFileAsync = realAsync
end

-- ── summary ─────────────────────────────────────────────────────────────

if failures > 0 then
  io.stderr:write(string.format("\n%d of %d assertions failed\n", failures, assertions))
  os.exit(1)
end
io.write(string.format("ok - %d assertions passed\n", assertions))
