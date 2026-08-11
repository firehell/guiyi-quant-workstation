"""归一量化统一命令行入口包（``guiyi``）。

默认只读优先：data 命令无 ``--apply`` 时为 dry-run/plan；runtime status 仅查询健康。
JSON 输出经 output 模块脱敏，不向终端泄露凭据或内部路径。
"""
