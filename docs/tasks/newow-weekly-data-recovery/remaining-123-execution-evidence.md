# 牛哇周线剩余 1–3 项当前证据

日期：2026-09-14。状态：`EC2607 COMPLETED / ORDINARY_AND_RS_EXTERNAL_GATE_PENDING`。本文件记录本任务的
工程、只读事实与 EC2607 已消费的一次执行证据；不代表普通批次、RS、发布或 Runtime 操作已获授权。

## 当前依赖队列

冻结参数：`operational` 60 品种、`frequency=1w`、
`as_of=2026-09-13T06:36:13+00:00`、dependency-only compact readiness。有效结果为
`complete=true`、`budget_exhausted=false`、`provider_requests=0`、`writes=0`。

| 分类 | 2026-09-13 历史快照 | 当前 | 变化 |
| --- | ---: | ---: | ---: |
| DATA_READY | 98 | 100 | +2 |
| DATA_UNAVAILABLE | 2,320 | 2,318 | -2 |
| NOT_APPLICABLE | 20 | 20 | 0 |
| SOURCE_EXCEPTION | 2 | 2 | 0 |
| PROPOSED repair | 1,139 | 1,138 | -1 |
| REVIEW_REQUIRED repair | 11 | 11 | 0 |
| metadata proposal | 0 | 0 | 0 |

当前不可用细分为 `DATASET_OR_PARTITION_MISSING=12`、`REPLAY_ENDPOINTS_MISSING=2`、
`REPLAY_PREFIX_MISSING=2304`。`SI2308` 已从 repair targets 消失，符合其既有原生 replan targets=0；
上述变化不能外推为第 4 项完整矩阵通过。

普通候选按 `symbol/contract/through` 稳定排序并排除 EC2607、RS2309、RS2311 后，首批最多 20 项如下。
这些只是批次候选，不是执行授权；正式 prepare 还须冻结完整 targets、来源日期和执行身份。

| # | symbol | contract | through | bars | targets | plan sha256 |
| ---: | --- | --- | --- | ---: | ---: | --- |
| 1 | a | A2407 | 2024-06-17 | 232 | 20 | `b3681d91707a8751b9248f4d5e27ff12001c772398b99da10e38eb68febd3a1f` |
| 2 | a | A2409 | 2024-08-15 | 227 | 20 | `b27e979309fdf3d32ebfb18f181a15c2f90e62d385b73231254bc2c8a26f2744` |
| 3 | a | A2501 | 2024-12-20 | 184 | 16 | `a66294c66ae087d8be35734e2dcf449f8f21846339512f3050a672524299c3b3` |
| 4 | a | A2505 | 2025-04-21 | 186 | 16 | `4258ec20f5f63f7e6c41a2fc77510c26525da8e8c10d335e976896a0df22589c` |
| 5 | a | A2507 | 2025-06-10 | 235 | 20 | `ecf994e2ae5727ee05f5924dbc08d6650c30a2b410c11ece13991728f5b5dd54` |
| 6 | a | A2509 | 2025-08-08 | 228 | 20 | `58aea617a4c8b928fbfdd78feb5f49a984b2a752af89f02f0a2b2b38eb95dc92` |
| 7 | a | A2511 | 2025-10-14 | 236 | 20 | `0ad480828c89ca762512a03c1f06750e2b87f48d0e99b3f3a790bc13cbfbe52c` |
| 8 | a | A2601 | 2025-12-19 | 232 | 20 | `6670053f9ba9caba4990b5eab8873f4521cf8fc634dd32a8bf4e8bf64f2c2f43` |
| 9 | a | A2605 | 2026-04-14 | 188 | 16 | `0503b17271e4fff56bd989beef7ee6712511fe33ef460901f99c063beba5ffba` |
| 10 | a | A2607 | 2026-06-17 | 234 | 20 | `f416b809fe2d72660876fa6163517c3da492fc4f516e17897c0948297630f81d` |
| 11 | a | A2609 | 2026-08-10 | 228 | 20 | `b9148eb40dc233c2bf863cbd5251308a1d9c851d56d2d3aa70334c5eb768d3a3` |
| 12 | ag | AG2302 | 2023-01-11 | 261 | 22 | `db6e7db8d289e8b11b10fac45d7d6c5063ff1bfdcd648dec3e7f3e54ceeb2867` |
| 13 | ag | AG2306 | 2023-05-23 | 183 | 16 | `426fa927e41404fd76ce7c8f5e45ff44f73839f870a6b0cf9e226b86d6013dfb` |
| 14 | ag | AG2308 | 2023-07-14 | 230 | 20 | `527f42eea1db1fbc39ae5f07e180098c52e07fb4c3bd65d00c794526dd99663f` |
| 15 | ag | AG2310 | 2023-09-05 | 233 | 20 | `e33e3e1cd21978b5401b897b39a47cdd5520c4cafb8084d1f16561ea5ff29369` |
| 16 | ag | AG2312 | 2023-11-06 | 234 | 20 | `4bc70937e25912718b8624b97b56219fe625e4208163624aac72bc198f19e96b` |
| 17 | ag | AG2402 | 2024-01-17 | 234 | 20 | `a2b7ed8de98639c6127bb038494dd7b0dd3bfb0d393e7f348a6ba463af717e3d` |
| 18 | ag | AG2406 | 2024-05-14 | 187 | 16 | `2216d9c75406c96165dbcea33661cc9a1a4515abe79b86e7f24a910f4005fbc9` |
| 19 | ag | AG2408 | 2024-07-26 | 230 | 20 | `300ee3ce45fb05af6e84a1833bc497def245074d0e98543e5e2de851375030f4` |
| 20 | ag | AG2412 | 2024-11-13 | 181 | 16 | `e9be225401501d7633e0186e1fed4a8014f452730c781c5b737d4bf4d1ae3c7b` |

## EC2607

当前原生只读结果仍为 8 个 D1/W1 月目标、84 根、plan
`5c7a1debdae9001497638f747b9ec0eb8cca2c8b3cf66e32ec28351b353dae72`，与旧失败包一致。
旧 attempt 的真实 provider 调用数仍是 unknown；Catalog/物理写入为 0。新实现的 April W1 来源范围由原生
Calendar 展开到 2026-03-30，不再使用旧执行器的 2026-04-01 硬断言。

owner 批准后，exact prepared artifact
`4712d8b6d16ccd0dea71cb1f3e32f07026aabcdc4246e4f43eb626fb6bc1db93` 已以 attempt
`ec2607-20260914-001` 严格执行一次。绑定代码为
`3ea81f34e24fcf7767ad5be51f1d62c5c6129e18`，原 plan hash 未漂移；结果为 `passed`：8/8 targets、
84 bars、8 次原生 target 请求，blocked/failed 均为 0。底层同源调用为 4 started/4 response_saved，
`outcome_unknown=false`、`retries=0`；2026 年 4 月来源从 2026-03-30 开始。

提交后 8 个分区的 Catalog row count、物理 Parquet row count 与 MDS bar count 逐项相等，物理文件均记录
SHA-256；原生 replan 为 0 targets/0 bars/0 provider request，plan
`fe28bda7044f566d67400c6fda40f717320febc345e31e71c6810aa6ab8f6c8d`。独立新进程再次得到同一零目标结果。
本次执行意图已消费，不授权重试或扩大范围；完整 journal、来源 payload、receipt 和逐分区 readback 保存在
`outputs/newow-weekly-recovery-attempts/ec2607-20260914-001/`。

## RS2309 / RS2311 本地专项

本次仅读取当前 Catalog、Calendar、Session 与 Canonical 文件；`provider_requests=0`、`writes=0`。全部列出的
Catalog row count 与物理 Parquet row count 一致，未发现行数型文件损坏。当前分类只能是
`SOURCE_VERIFICATION_PENDING`，不得提前写成 `SOURCE_NONPOSITIVE_MATCH`。

| contract | through | plan targets / bars | plan sha256 | 去重来源日期范围 |
| --- | --- | --- | --- | --- |
| RS2309 | 2023-06-28 | 20 / 226 | `787702047f51edc3f3c8e80616353c8c74f3fd6d2af2ce846b84c514ad5a7fb5` | 2022-09-16..2023-06-16，181 日，日期 hash `9f2dc8c66ce5b70365e1b48f2e6dda487b83929654dd01a7ef3a03ea946ae39e` |
| RS2311 | 2023-11-01 | 6 / 66 | `1a0e9bb2fb854bf3f1267b8af8acbe5c2b49bcec126b90c8c7148eff5df6394e` | 2022-11-15..2023-06-28，150 日，hash `f85a53ea5d97a23e694db4658801b956c787cb8466782b5077c9eb3a46f7b104`；另 2023-11-01，hash `bc1a430d1edabce59ba95dc1d4e413d4b91751ff348daa806ad7cf35937000df` |

三个来源日期组的 Calendar 与有效 Session 均完整。它们是未来“仅来源核验”的最大精确边界，不授权下载，
更不授权 Canonical 写入。

当前非正 bars：

- RS2309 D1：2023-06-15；W1：2023-06-16。
- RS2311 D1：2023-01-06/09/10/11，02-01/07/08/09/17/20/21/22/23，
  03-07/08/13/14/15，04-06，05-17/25/30，06-06/07/08/09/12/13，11-01。
- RS2311 W1：2023-01-06/13，02-03/10/17/24，03-10/17，04-07，05-19/26，06-02/09。

相关分区身份：

| contract/frequency/month | rows | file sha256 |
| --- | ---: | --- |
| RS2309/1d/2023-06 | 8 | `458efffcbeefd761d19d46706ca1397ddd8a9a63dce9ea5c1db92bc0939ef3db` |
| RS2309/1w/2023-06 | 2 | `978a3c45a818404f9ebc36712194ea02350aa23adf5407d3e4ccc1a91c5fdfa3` |
| RS2311/1d/2023-01 | 16 | `a8d99f7fe5c69bff1c98c35f8c0fa29848cf7fcff92adf7911e55c5851d50645` |
| RS2311/1d/2023-02 | 20 | `e2dac1490d2810c9da3ad58fb015dae6bbe96a190ee73f0a3103fe54cf6b2b15` |
| RS2311/1d/2023-03 | 23 | `fc933832aebb57e60b00c0c8a3cd4003c4f1ffd515fb0cd77548cd7c48484009` |
| RS2311/1d/2023-04 | 19 | `6e840d23925c1b24a71922a8ff2620f1ab2aa3f74cab2265aafa1347aed1d8f6` |
| RS2311/1d/2023-05 | 20 | `3d0aa3aaeddd7fa6d26c1f07df59171e5cb21b5c0ae30dda0201ac83ac2139ac` |
| RS2311/1d/2023-06 | 12 | `d8c4e6a3b07d0d078d7b6215c6e9541c8d08f6d11db4d60d42b321d437f9e97c` |
| RS2311/1d/2023-11 | 1 | `e7344ea31f2f14846e6bbe6d4dcc485ad20427d03aa946bf12934673034a6dc6` |
| RS2311/1w/2023-01 | 3 | `fc0be2b1638217e66c5119d1cb6139e9f65a554997b340aaab903efbb86f090d` |
| RS2311/1w/2023-02 | 4 | `0e161199c27909cf876abc5bb9cff62c26f8ddf267fa4d71a6d3b72559a8b276` |
| RS2311/1w/2023-03 | 5 | `e4f702a13f87326a5d8d7d7cc8780da47de10e9830f9151cc2a066ddcc1fd4f6` |
| RS2311/1w/2023-04 | 4 | `0d0d1449e3f5ee7fb466a7086e2aff2cec8dda5a3cf6017c7d0e3d122e3fd962` |
| RS2311/1w/2023-05 | 4 | `546e59e7c1b97c8b49a7c6c7564437b42626b762c1cb0fd14443e6c2824b5a9e` |
| RS2311/1w/2023-06 | 3 | `e855e6f6e0cab9b1eecf82f8cc49969564f4318f116a2f0ecdc4d7f7cfa5c5dd` |

RS2309 缺口覆盖 2022-09 至 2023-06 的 D1/W1；RS2311 缺口为 2022-11/12 与 2023-06 的
D1/W1。非正 bars 与缺口一起形成未来来源核验集合，但来源核验和正式修复是两个独立 Gate。

## Gate

- 工程：504 项扩展定向测试、Ruff、mypy、OpenSpec strict 9/9、secret scan 0 findings 与 diff check 均通过。
  最终独立 Review：Standards 为 P1/P2/P3/smell 全 0；Spec 为 P1/P2/P3 全 0、1 个非阻断的 readback
  seam smell。结论均为允许集成 develop。
- EC2607：一次执行已完成且严格读回通过；该意图已消费，不授权重试。
- 普通首批：EC 成功 Gate 已满足，但仍需独立 prepared hash 和 fresh 一次执行意图；本任务未执行。
- RS2309/RS2311：先对上述精确来源集合取得“仅来源下载”意图；禁止 Canonical 写入。分类后如有本地可修复
  冲突，再形成独立修复 plan、Review 和正式写入意图。
- 第 4 项完整矩阵、main/tag/release、Runtime、Scope、通知和交易均不在本任务。
