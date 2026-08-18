# WeChat-Courier dependency contract

`develop` pins `bladydora/WeChat-Courier-macOS` at commit
`981bd14e238302b2a0e206cb5f28e8e2505bb874`. The dependency lives outside the
repository under an explicitly configured expansion-volume root:

```text
<root>/source/.git
<root>/source/wechat_courier.py
<root>/venv/bin/python
<root>/runtime
<root>/tmp
<root>/cache/clang
```

Read-only structural check:

```bash
GUIYI_WECHAT_COURIER_ROOT=/Volumes/<volume>/<private-root> \
  scripts/ops/macos/install-wechat-courier.sh --check
```

`--confirm-install` is a separately controlled external operation. It may only
run after a new, explicit user instruction for the exact root. It clones the
pinned source and installs only `Pillow==11.3.0`; it never runs upstream
`main`, a watcher, queue or MCP process, opens WeChat, changes TCC permissions,
or sends a message.

The Alert group title is held only in a private JSON file whose parent is mode
`0700` and file is mode `0600`. Code, status output and logs use only the fixed
alias `primary_alert_group`.
