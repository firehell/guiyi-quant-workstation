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
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return -1 end
local expected_state = redis.call('GET', KEYS[2]) or ''
if expected_state ~= ARGV[2] then return -2 end
local plan = cjson.decode(ARGV[3])
for i, series in ipairs(plan) do
  local current = redis.call('ZRANGEBYSCORE', KEYS[i+2], '-inf', ARGV[4])
  if #current ~= #series.before then return -3 end
  for j, value in ipairs(current) do
    if value ~= series.before[j] then return -3 end
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
