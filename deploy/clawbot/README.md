# Clawbot dependency contract

`versions.json` freezes the non-secret OpenClaw, Node and `openclaw-weixin` compatibility facts observed by the
approved G1 read-only discovery. Runtime paths and owner identifiers remain outside Git and are injected explicitly.

Guiyi does not install, update, supervise or log in OpenClaw. The tracked integration is single-shot and must never
use OpenClaw public message delivery, retries, queues, replay, backfill or recipient fallback.
