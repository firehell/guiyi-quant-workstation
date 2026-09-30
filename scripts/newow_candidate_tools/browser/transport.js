async page=>{
  const NONCE = __NONCE__;
  const LIMIT = 1048576;
  const state = page.__p7ChunkedCapture;
  if (!state || state.nonce !== NONCE || state.done) throw Error('CHUNK_STATE_MISSING');
  if (!state.iterator) {
    const ancestors = new WeakSet();
    function* encode(value, inArray = false) {
      if (value && typeof value.toJSON === 'function') value = value.toJSON();
      if (value === undefined || typeof value === 'function' || typeof value === 'symbol') {
        if (inArray) yield 'null';
        return;
      }
      if (value === null || typeof value !== 'object') {
        const scalar = JSON.stringify(value);
        if (scalar === undefined) throw Error('CHUNK_UNSUPPORTED_VALUE');
        yield scalar;
        return;
      }
      if (ancestors.has(value)) throw Error('CHUNK_CYCLE');
      ancestors.add(value);
      if (Array.isArray(value)) {
        yield '[';
        for (let i = 0; i < value.length; i++) {
          if (i) yield ',';
          yield* encode(value[i], true);
        }
        yield ']';
      } else {
        yield '{';
        let first = true;
        for (const [key, item] of Object.entries(value)) {
          if (item === undefined || typeof item === 'function' || typeof item === 'symbol') continue;
          if (!first) yield ',';
          first = false;
          yield JSON.stringify(key);
          yield ':';
          yield* encode(item);
        }
        yield '}';
      }
      ancestors.delete(value);
    }
    state.iterator = encode(state.result);
    state.pending = '';
    state.seq = 0;
  }
  let chunk = '';
  while (chunk.length < LIMIT) {
    if (!state.pending) {
      const next = state.iterator.next();
      if (next.done) { state.done = true; break; }
      state.pending = next.value;
    }
    const room = LIMIT - chunk.length;
    let take = Math.min(room, state.pending.length);
    const lastCode = state.pending.charCodeAt(take - 1);
    if (take < state.pending.length && lastCode >= 0xD800 && lastCode <= 0xDBFF) take--;
    if (take <= 0) {
      if (chunk.length) break;
      throw Error('CHUNK_BOUNDARY_INVALID');
    }
    chunk += state.pending.slice(0, take);
    state.pending = state.pending.slice(take);
  }
  if (!state.done && chunk.length === LIMIT && !state.pending) {
    const next = state.iterator.next();
    if (next.done) state.done = true;
    else state.pending = next.value;
  }
  if (!chunk && !state.done) throw Error('CHUNK_NO_PROGRESS');
  const bytes = Buffer.from(chunk, 'utf8');
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  const sha256 = [...new Uint8Array(digest)].map(x => x.toString(16).padStart(2, '0')).join('');
  if (state.done) { state.result = null; state.iterator = null; state.pending = ''; }
  return {kind: 'chunked_json_v1', nonce: NONCE, seq: ++state.seq,
          done: state.done === true, bytes: bytes.length, sha256, base64: bytes.toString('base64')};
}
