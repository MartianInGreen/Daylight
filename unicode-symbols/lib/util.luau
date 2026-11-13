--!nonstrict
-- Shared helpers for the two launcher providers.
--
-- Everything here is pure Lua: UTF-8 conversion (the plugin host does not
-- expose a UTF-8 library to entry scripts), query normalization, the ranking
-- used by both providers, and the algorithmic names for the Unicode ranges
-- that the bundled table leaves out (CJK ideographs, Hangul, Tangut, ...).

local M = {}

-- Leading/trailing whitespace plus the separators people type between words.
local SEPARATOR = "[%s%-_/,.:;%(%)%[%]{}%+%*%?!\"'’]+"

function M.trim(text)
  return (text:gsub("^%s+", ""):gsub("%s+$", ""))
end

-- Uppercase, separators collapsed to single spaces. Unicode names are ASCII
-- uppercase with spaces and hyphens, so this is the form we match against.
function M.normalize(text)
  local upper = text:upper()
  local spaced = upper:gsub(SEPARATOR, " ")
  return M.trim((spaced:gsub("%s+", " ")))
end

function M.tokens(normalized)
  local list = {}
  for word in normalized:gmatch("%S+") do
    list[#list + 1] = word
  end
  return list
end

-- U+XXXX, at least four hex digits so that ordinary words like "beef" still
-- read as a name search, and at most six so U+10FFFF fits.
function M.parseCodepoint(text)
  local body = M.trim(text):lower()
  body = body:gsub("^u%+", "", 1):gsub("^0x", "", 1):gsub("^u", "", 1)
  if #body < 4 or #body > 6 or not body:match("^%x+$") then
    return nil
  end
  local codepoint = tonumber(body, 16)
  if codepoint == nil then
    return nil
  end
  return codepoint
end

function M.isValidScalar(codepoint)
  if codepoint < 0 or codepoint > 0x10FFFF then
    return false
  end
  return codepoint < 0xD800 or codepoint > 0xDFFF
end

function M.hex(codepoint)
  return string.format("%04X", codepoint)
end

function M.utf8Encode(codepoint)
  if codepoint < 0x80 then
    return string.char(codepoint)
  end
  if codepoint < 0x800 then
    return string.char(
      0xC0 + math.floor(codepoint / 0x40),
      0x80 + codepoint % 0x40
    )
  end
  if codepoint < 0x10000 then
    return string.char(
      0xE0 + math.floor(codepoint / 0x1000),
      0x80 + math.floor(codepoint / 0x40) % 0x40,
      0x80 + codepoint % 0x40
    )
  end
  return string.char(
    0xF0 + math.floor(codepoint / 0x40000),
    0x80 + math.floor(codepoint / 0x1000) % 0x40,
    0x80 + math.floor(codepoint / 0x40) % 0x40,
    0x80 + codepoint % 0x40
  )
end

-- Decode every valid UTF-8 sequence in a string, skipping stray continuation
-- bytes. Used to turn a pasted character into the code point to look up.
function M.decodeAll(text)
  local codepoints = {}
  local index = 1
  local length = string.len(text)
  while index <= length do
    local byte = text:byte(index)
    local codepoint = nil
    local size = 1
    if byte < 0x80 then
      codepoint = byte
    elseif byte >= 0xF0 and byte <= 0xF7 then
      codepoint = byte - 0xF0
      size = 4
    elseif byte >= 0xE0 and byte <= 0xEF then
      codepoint = byte - 0xE0
      size = 3
    elseif byte >= 0xC0 and byte <= 0xDF then
      codepoint = byte - 0xC0
      size = 2
    end

    if codepoint ~= nil and size > 1 then
      local complete = true
      for offset = 1, size - 1 do
        local nextByte = text:byte(index + offset)
        if nextByte == nil or nextByte < 0x80 or nextByte > 0xBF then
          complete = false
          break
        end
        codepoint = codepoint * 0x40 + (nextByte - 0x80)
      end
      if complete and M.isValidScalar(codepoint) then
        codepoints[#codepoints + 1] = codepoint
        index = index + size
      else
        index = index + 1
      end
    elseif codepoint ~= nil then
      codepoints[#codepoints + 1] = codepoint
      index = index + 1
    else
      index = index + 1
    end
  end
  return codepoints
end

-- Rows show the character itself as the badge. Combining marks get a dotted
-- circle so they are visible, and characters that render as nothing (controls,
-- format characters, spaces) fall back to the provider glyph.
function M.isVisible(category)
  if category == nil or category == "" then
    return false
  end
  if category == "Zl" or category == "Zp" or category == "Zs" then
    return false
  end
  local group = category:sub(1, 1)
  return group ~= "C"
end

function M.badgeFor(codepoint, category)
  if not M.isVisible(category) then
    return nil
  end
  local character = M.utf8Encode(codepoint)
  if category:sub(1, 1) == "M" then
    return "◌" .. character -- U+25CC DOTTED CIRCLE
  end
  return character
end

-- Ranking shared by both providers.
--
-- text is the searchable uppercase text (a Unicode name, or a symbol row's
-- name + aliases + group), q the normalized query and tokens its words:
--   10000  exact name
--    8xxx  name starts with the query
--    7xxx  the query starts a word in the name
--    5xxx  the query appears anywhere
--    1xxx  every query word appears, scoring word starts higher
--      0   no match
local function boundaryBefore(text, position)
  if position <= 1 then
    return true
  end
  local previous = text:sub(position - 1, position - 1)
  return previous == " " or previous == "-" or previous == "(" or previous == "/"
end

function M.score(text, query, tokens)
  if text == query then
    return 10000
  end

  local position = text:find(query, 1, true)
  if position ~= nil then
    local score = 5000
    if position == 1 then
      score = 8000
    elseif boundaryBefore(text, position) then
      score = 7000
    end
    return score - math.min(position, 400) - math.min(#text, 400)
  end

  local total = 0
  for i = 1, #tokens do
    local token = tokens[i]
    local at = text:find(token, 1, true)
    if at == nil then
      return nil
    end
    total = total + 100
    if boundaryBefore(text, at) then
      total = total + 150
    end
  end
  return total - math.min(#text, 200)
end

-- Aliases are secondary search names. They score like names, minus one so an
-- exact formal name still wins a tie.
function M.bestAliasScore(aliasList, query, tokens)
  if aliasList == nil then
    return nil
  end
  local best = nil
  for i = 1, #aliasList do
    local score = M.score(aliasList[i], query, tokens)
    if score ~= nil then
      score = score - 1
      if best == nil or score > best then
        best = score
      end
    end
  end
  return best
end

-- Keep the best `limit` candidates in descending score order. Insertion into
-- a short list is cheaper than sorting every match: a one-letter query can
-- match tens of thousands of names.
function M.insertCandidate(candidates, candidate, limit)
  local count = #candidates
  if count >= limit and candidate.score <= candidates[count].score then
    return
  end
  local index = count
  while index >= 1 and candidates[index].score < candidate.score do
    index = index - 1
  end
  table.insert(candidates, index + 1, candidate)
  if #candidates > limit then
    table.remove(candidates)
  end
end

-- Blocks.txt is sorted, so a binary search is enough for the subtitle.
function M.blockAt(blocks, codepoint)
  local low, high = 1, #blocks
  while low <= high do
    local middle = math.floor((low + high) / 2)
    local block = blocks[middle]
    if codepoint < block.start then
      high = middle - 1
    elseif codepoint > block.stop then
      low = middle + 1
    else
      return block.name
    end
  end
  return nil
end

-- Binary search over the parallel arrays built from unicode.tsv.
function M.findIndex(codepoints, codepoint)
  local low, high = 1, #codepoints
  while low <= high do
    local middle = math.floor((low + high) / 2)
    local value = codepoints[middle]
    if value == codepoint then
      return middle
    elseif value < codepoint then
      low = middle + 1
    else
      high = middle - 1
    end
  end
  return nil
end

-- Algorithmic names for the ranges UnicodeData.txt stores as First/Last
-- pairs; these rows are not in unicode.tsv.
local ALGORITHMIC = {
  { 0x3400, 0x4DBF, "CJK UNIFIED IDEOGRAPH-%s", "Lo" },
  { 0x4E00, 0x9FFF, "CJK UNIFIED IDEOGRAPH-%s", "Lo" },
  { 0x17000, 0x187FF, "TANGUT IDEOGRAPH-%s", "Lo" },
  { 0x18D00, 0x18D20, "TANGUT IDEOGRAPH-%s", "Lo" },
  { 0x18E00, 0x19191, "JURCHEN CHARACTER-%s", "Lo" },
  { 0x20000, 0x2A6DF, "CJK UNIFIED IDEOGRAPH-%s", "Lo" },
  { 0x2A700, 0x2B73F, "CJK UNIFIED IDEOGRAPH-%s", "Lo" },
  { 0x2B740, 0x2B81E, "CJK UNIFIED IDEOGRAPH-%s", "Lo" },
  { 0x2B820, 0x2CEAD, "CJK UNIFIED IDEOGRAPH-%s", "Lo" },
  { 0x2CEB0, 0x2EBE0, "CJK UNIFIED IDEOGRAPH-%s", "Lo" },
  { 0x2EBF0, 0x2EE5D, "CJK UNIFIED IDEOGRAPH-%s", "Lo" },
  { 0x30000, 0x3134A, "CJK UNIFIED IDEOGRAPH-%s", "Lo" },
  { 0x31350, 0x323AF, "CJK UNIFIED IDEOGRAPH-%s", "Lo" },
  { 0x323B0, 0x33479, "CJK UNIFIED IDEOGRAPH-%s", "Lo" },
  { 0x3D000, 0x3FC3F, "SEAL CHARACTER-%s", "Lo" },
  { 0xE000, 0xF8FF, "PRIVATE USE CHARACTER-%s", "Co" },
  { 0xF0000, 0xFFFFD, "PRIVATE USE CHARACTER-%s", "Co" },
  { 0x100000, 0x10FFFD, "PRIVATE USE CHARACTER-%s", "Co" },
}

-- Hangul syllables are named from their initial/medial/final jamo.
local HANGUL_INITIAL = {
  "G", "GG", "N", "D", "DD", "R", "M", "B", "BB", "S",
  "SS", "", "J", "JJ", "C", "K", "T", "P", "H",
}
local HANGUL_MEDIAL = {
  "A", "AE", "YA", "YAE", "EO", "E", "YEO", "YE", "O", "WA",
  "WAE", "OE", "YO", "U", "WEO", "WE", "WI", "YU", "EU", "YI", "I",
}
local HANGUL_FINAL = {
  "", "G", "GG", "GS", "N", "NJ", "NH", "D", "L", "LG",
  "LM", "LB", "LS", "LT", "LP", "LH", "M", "B", "BS", "S",
  "SS", "NG", "J", "C", "K", "T", "P", "H",
}

function M.generatedFor(codepoint)
  if codepoint >= 0xAC00 and codepoint <= 0xD7A3 then
    local offset = codepoint - 0xAC00
    local initial = math.floor(offset / 588) + 1
    local medial = math.floor(offset % 588 / 28) + 1
    local final = offset % 28 + 1
    return "HANGUL SYLLABLE "
      .. HANGUL_INITIAL[initial]
      .. HANGUL_MEDIAL[medial]
      .. HANGUL_FINAL[final], "Lo"
  end
  for i = 1, #ALGORITHMIC do
    local range = ALGORITHMIC[i]
    if codepoint >= range[1] and codepoint <= range[2] then
      return string.format(range[3], M.hex(codepoint)), range[4]
    end
  end
  return nil
end

return M
