# SR 周线第一批：精确数据写入待授权

- 代码身份：`develop@55454558629734aff0856d02692c1d4242500980`；统一完整周截止：`2026-09-18T07:00:00.000001+00:00`。
- 准备文件：`sr-prepare.json`，SHA-256 `054eaa727285ae9c3ecdbf486fb1ba592a90e8786ba8df5525a42748d601d7b6`；SR 范围 Catalog revision：`ab1953f8b183e89c681ca5de7568f0e8ed3a667363d941318387ad402a9587b2`。
- 精确目标：本地工作站 Canonical `contract/sr/SR2303/1w/2022-03` 一个月分区；仅 `2022-03-18` 一根 W1 改动，月内另 1 行不变。旧 open/low=0，新 open=6053、low=5954；high=6053、close=6011、volume=25、turnover=1503200、OI=21 不变。
- D1 来源：`SR2303` 2022-03-15 至 18 四个权威端点完整；03-15/16 为严格全零无交易日。provider 请求 0、D1 写入 0、其他品种写入 0。
- 旧 W1 分区哈希 `73f9d1a81dd1d8eaedfbb82668702892055fe4299986d11332fb1979f7fdedda`；候选哈希 `bfea4244281706b53333d6e170997a5eedf581090e0ce2f4f657961c3c073ac8`。旧文件保留，使用现有维护锁和 Catalog 指针原子提交。独立 `inspect` 已读回 `old`。
- 内存候选数据下趋势、震荡、主升浪的 W1 chart/auxiliary/reference 均 READY；震荡 comparator 因样本不足为 UNAVAILABLE，另两项 NOT_APPLICABLE；explanation 未开放。此结果不等于生产数据或真实浏览器验收。
- 执行前重新核对计划 SHA、代码/聚合版本、D1 与 W1 文件前像、Catalog revision 和指针状态；只允许一次 apply。失败或结果不明时停止，仅用独立只读 `inspect` 判定 old/candidate/mixed，不盲目重试。若需恢复旧指针，另以保留的旧文件和精确身份做受控恢复。
- apply 后独立回读新指针、两行 W1、四根 D1 不变及全品种三策略。再做候选 API 与真实浏览器首载；正式 Scope 开放、main/tag/Release、Runtime promotion 均为各自 Gate。
