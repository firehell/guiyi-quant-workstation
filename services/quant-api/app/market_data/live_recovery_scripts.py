"""Atomic transient Live writes. All checks precede the first mutation."""

PUT_BAR = r"""-- live-put-v1
local existing = redis.call('ZRANGEBYSCORE', KEYS[1], ARGV[1], ARGV[1])
if #existing > 0 then
  if #existing ~= 1 or existing[1] ~= ARGV[2] then return -1 end
  return 0
end
redis.call('ZADD', KEYS[1], ARGV[1], ARGV[2])
redis.call('EXPIRE', KEYS[1], ARGV[3])
return 1
"""

COMMIT_RECOVERY = r"""-- live-recovery-v1
local frozen = ARGV[7] and cjson.decode(ARGV[7]) or nil
local plan = cjson.decode(ARGV[3])
local ttl = tonumber(ARGV[6])
if #plan ~= 5 or not ttl or ttl < 1 or ttl > 259200 or ttl ~= math.floor(ttl) then return -4 end
if frozen then
  if #frozen.types ~= #KEYS or #frozen.values ~= #KEYS then return -4 end
  for i, key in ipairs(KEYS) do
    local kind = redis.call('TYPE', key).ok
    local remaining = redis.call('TTL', key)
    if kind ~= frozen.types[i] then return -4 end
    if kind == 'none' then
      if remaining ~= -2 then return -4 end
    elseif remaining <= 0 or remaining > 259200 then return -4 end
    if i >= 3 and i <= 7 then
      if kind ~= 'zset' or redis.call('ZCARD', key) > 225 then return -4 end
    else
      if kind ~= 'none' and kind ~= 'string' then return -4 end
      local raw = redis.call('GET', key)
      local expected = frozen.values[i]
      if expected == cjson.null then
        if raw then return -4 end
      elseif raw ~= expected then return -4 end
    end
  end
  if redis.call('GET', KEYS[#KEYS]) then return -4 end
end
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return -1 end
local expected_state = redis.call('GET', KEYS[2]) or ''
if expected_state ~= ARGV[2] then return -2 end
for i, series in ipairs(plan) do
  local current = redis.call('ZRANGEBYSCORE', KEYS[i+2], '-inf', ARGV[4])
  if #current ~= #series.before then return -3 end
  for j, value in ipairs(current) do
    if value ~= series.before[j] then return -3 end
  end
  if frozen then
    if #series.add ~= 1 then return -4 end
    local scored = redis.call('ZRANGE', KEYS[i+2], 0, -1, 'WITHSCORES')
    if #scored ~= #series.before * 2 then return -3 end
    for j, value in ipairs(series.before) do
      if scored[2*j-1] ~= value or tonumber(scored[2*j]) ~= series.before_scores[j] then return -3 end
    end
  end
  for _, bar in ipairs(series.add) do
    if type(bar.score) ~= 'number' or bar.score ~= bar.score or bar.score <= 0
       or bar.score == math.huge or bar.score ~= math.floor(bar.score)
       or type(bar.payload) ~= 'string' or #bar.payload == 0 then return -4 end
    if frozen and #redis.call('ZRANGEBYSCORE', KEYS[i+2], bar.score, bar.score) ~= 0 then return -3 end
  end
end
for i, series in ipairs(plan) do
  for _, bar in ipairs(series.add) do
    redis.call('ZADD', KEYS[i+2], bar.score, bar.payload)
  end
  redis.call('EXPIRE', KEYS[i+2], ARGV[6])
end
redis.call('SET', KEYS[2], ARGV[5], 'EX', ARGV[6])
return 1
"""

CLAIM_ATTEMPT = r"""-- live-recovery-attempt-v1
if redis.call('GET', KEYS[2]) then return 0 end
local raw = redis.call('GET', KEYS[1])
local state = raw and cjson.decode(raw) or {count=0,last_at=0}
if state.count >= 3 or tonumber(ARGV[1]) - state.last_at < 60000 then return 0 end
state.count = state.count + 1
state.last_at = tonumber(ARGV[1])
redis.call('SET', KEYS[1], cjson.encode(state), 'EX', ARGV[2])
return 1
"""
