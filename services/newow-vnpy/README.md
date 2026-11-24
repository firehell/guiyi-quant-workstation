# VeighNa P1-B macOS 离线验证

本目录锁定 Apple Silicon 上的 CPython 3.13.3、VeighNa 4.4.0 和 PortfolioStrategy 1.3.0。CTP 使用官方为 Mac 推荐的 6.7.7.2 GitHub 发布源码，锁定提交 `fa199f70dac9e242c20e925c17e2241b877e694f` 及归档 SHA256 `de298bfd8c917d99fb84bf4177909cf98b791d701c056683d239546fc8f9eb6b`。[官方发布](https://github.com/vnpy/vnpy_ctp/releases/tag/6.7.7.2) · [上游问题 #91](https://github.com/vnpy/vnpy_ctp/issues/91)

同版本的 PyPI 源包缺少框架符号链接，签名资源及 `Info.plist` 与 Git 归档存在字节差异。在目标 Mac 上，两份 Git 归档框架均可原样加载，返回 `v6.7.7_MacOS_20240716 15:00:00`。对同版本 PyPI 框架做相同加载时，dyld 返回签名无效。Git 归档中的原始签名与系统安全设置均保留。系统的独立 `codesign --verify --strict` 信任链检查返回 `CSSMERR_TP_NOT_TRUSTED`，本次实际加载由目标 Mac 上的 dyld 验证。

按 [gateway_smoke.py](gateway_smoke.py) 开头的命令，从锁定归档用 Apple Clang／Meson 构建，然后在新的私有目录和系统禁网沙箱中执行 smoke 或 pytest。验收包含两个 ARM64 扩展导入、未连接的 CTP 网关初始化，以及六类事件经具体 Python 回调进入 VeighNa EventEngine 后的顺序、字段和身份。回调输入是固定测试数据。MD 权限与订阅、TD 连接与对账、原生回报传输及 P5 恢复需独立验收。
