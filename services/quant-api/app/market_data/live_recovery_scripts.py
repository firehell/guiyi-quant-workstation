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

COMMIT_OBSERVATIONS = r"""-- live-observation-commit-v1
-- KEYS: source cursor, source stream, completed stream, completed identities, bar zsets.
local ok,plan=pcall(cjson.decode,ARGV[3])
if not ok or type(plan)~='table' or string.sub(ARGV[3],1,1)~='[' then return -4 end
local ttl=tonumber(ARGV[4]); local limit=tonumber(ARGV[5])
if not ttl or ttl~=259200 or not limit or limit~=120000 then return -4 end
for i,k in ipairs(KEYS) do
 local t=redis.call('TYPE',k).ok
 local expected=i==1 and 'string' or ((i==2 or i==3) and 'stream' or (i==4 and 'hash' or 'zset'))
 if t~='none' and t~=expected then return -4 end
end
if redis.call('GET',KEYS[1])~=ARGV[1] then return -2 end
if ARGV[2]~=ARGV[1] and #redis.call('XRANGE',KEYS[2],ARGV[2],ARGV[2])~=1 then return -2 end
local additions=0
local identities={}
for _,item in ipairs(plan) do
 if type(item)~='table' or type(item.key_index)~='number' or item.key_index~=math.floor(item.key_index)
    or item.key_index<5 or item.key_index>#KEYS or type(item.score)~='number'
    or item.score~=item.score or item.score<=0 or item.score==math.huge
    or item.score~=math.floor(item.score) or item.score>9007199254740991
    or type(item.payload)~='string' or #item.payload==0
    or type(item.envelope)~='string' or #item.envelope==0
    or type(item.identity)~='string' or #item.identity==0 or identities[item.identity]
    or type(item.channel)~='string' or #item.channel==0 then return -4 end
 identities[item.identity]=true
 local parsed,envelope=pcall(cjson.decode,item.envelope)
 if not parsed or type(envelope)~='table' then return -4 end
 local existing=redis.call('ZRANGEBYSCORE',KEYS[item.key_index],item.score,item.score)
 if #existing>0 and (#existing~=1 or existing[1]~=item.payload) then return -1 end
 local old=redis.call('HGET',KEYS[4],item.identity)
 if old then
  if cjson.decode(old).payload~=item.envelope then return -1 end
 else additions=additions+1 end
end
if redis.call('XLEN',KEYS[3])+additions>limit then return -3 end
for _,item in ipairs(plan) do
 redis.call('ZADD',KEYS[item.key_index],item.score,item.payload)
 redis.call('EXPIRE',KEYS[item.key_index],ttl)
 if not redis.call('HGET',KEYS[4],item.identity) then
  local id=redis.call('XADD',KEYS[3],'*','envelope',item.envelope)
  redis.call('HSET',KEYS[4],item.identity,cjson.encode({id=id,payload=item.envelope}))
  redis.call('PUBLISH',item.channel,item.payload)
 end
end
redis.call('EXPIRE',KEYS[3],ttl); redis.call('EXPIRE',KEYS[4],ttl)
redis.call('SET',KEYS[1],ARGV[2],'EX',ttl)
return 1
"""
