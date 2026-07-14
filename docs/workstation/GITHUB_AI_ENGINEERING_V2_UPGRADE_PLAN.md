---

# 归一量化工作站 V2

# GitHub-Centric AI Engineering System Upgrade Plan

## 目标

将当前：

```
GPT
 ↓
人工复制文档
 ↓
WorkBuddy
 ↓
CodeBuddy
 ↓
Codex
 ↓
GitHub
```

升级为：

```
                 GitHub Private Repository

        Code
        Docs
        Issues
        PR
        Actions
        History


              ↑        ↑        ↑


            GPT    WorkBuddy   Codex


                    |
                CodeBuddy


                    |
               企业微信入口

```

目标：

让 GitHub 成为：

* 项目事实源
* AI共享记忆
* 任务管理中心
* 开发交付中心

---

# 第一阶段：GitHub 作为项目大脑

## 目标

建立 AI 可以共同读取的项目知识结构。

---

## Step 1.1 创建 AI 项目规则

新增：

```
AGENTS.md
```

位置：

```
/
├── AGENTS.md
```

内容：

```markdown
# Guiyi Quant AI Development Rules


## Project

This repository is the Guiyi Quant personal quantitative research workstation.


## Core Principle

Codex is the only code execution agent.


GPT:
Architecture and review.

Work:
Long-term planning.

WorkBuddy:
Task coordination.

CodeBuddy:
Execution trigger.


## Development Rules

Before any coding:

1. Read AGENTS.md
2. Read STATUS.md
3. Read related Issue
4. Read related docs


## Forbidden

- Modify production directly
- Delete historical data
- Change data schema without migration
- Modify secrets
- Push automatically


## Completion Requirement

Every task must provide:

- Summary
- Changed files
- Tests
- Risks
- Next step

```

---

### 执行 AI

使用 Codex：

Prompt：

```
@Codex

任务：

为归一量化仓库增加根目录 AGENTS.md。

要求：

1. 根据当前 README、ARCHITECTURE、STATUS 理解项目定位。
2. 生成适合 Codex/GPT/WorkBuddy 协作的仓库规则。
3. 不修改任何业务代码。
4. 创建：

AGENTS.md

5. 输出修改说明。
```

---

# Step 2：建立项目状态中心

新增：

```
STATUS.md
```

作用：

替代人工记忆。

结构：

```markdown
# Guiyi Quant Current Status


## Current Phase

V1


## Completed

- Historical data download
- Data layer design
- Web chart
- API deployment


## In Progress

DATA FINAL CLOSURE


## Next

- JM realtime
- Alert system


## Current Risks

- Runtime stability
- Data validation

```

---

### AI Prompt

```
@GPT

请读取当前 GitHub 仓库。

生成 STATUS.md。

要求：

包含：

1. 当前项目定位
2. 已完成模块
3. 当前开发任务
4. 未完成任务
5. 风险
6. 下一阶段入口条件

不要修改代码。
只创建文档。
```

---

# 第二阶段：Issue 驱动开发

## 目标

废弃：

```
聊天任务
本地task文件
人工复制
```

改成：

```
Issue
 ↓
Codex
 ↓
PR
 ↓
Review
```

---

# Step 3：建立 Issue 模板

新增：

```
.github/ISSUE_TEMPLATE/task.md
```

内容：

```markdown
# Task


## Background


## Goal


## Non Goal


## Scope


## Technical Design


## Acceptance Criteria


## Test Requirement


## Risk

```

---

### AI Prompt

```
@GPT

请修改 GitHub 仓库。

创建：

.github/ISSUE_TEMPLATE/task.md


目标：

让所有 AI 开发任务标准化。

不要修改业务代码。
```

---

# Step 4：建立任务状态标签

GitHub Labels：

创建：

```
status:draft

status:design

status:approved

status:coding

status:testing

status:review

status:done

priority:p0

priority:p1

priority:p2
```

---

作用：

以后 WorkBuddy 不维护状态。

GitHub 就是状态机。

---

# 第三阶段：PR 驱动交付

## Step 5：建立 PR 模板

新增：

```
.github/PULL_REQUEST_TEMPLATE.md
```

内容：

```markdown
# Change Summary


## Related Issue


## Changed Files


## Tests


## Risk


## Reviewer Notes

```

---

# Step 6：Codex 开发流程改变

以后：

不是：

```
给Codex Prompt
```

而是：

```
执行 Issue
```

例如：

Issue:

```
#300 修复日线重复K
```

Codex：

读取：

```
Issue #300

+
AGENTS.md

+
STATUS.md

+
docs
```

执行。

---

# 第四阶段：重新定义 AI 角色

## GPT Chat

角色：

CTO

负责：

* 架构判断
* 技术选择
* 风险分析

---

## GPT Work

角色：

架构部门

负责：

大型设计：

例如：

* 数据治理
* 实时系统
* 指标内核

输出：

直接写 GitHub：

```
docs/design/
```

创建 Issue。

---

## WorkBuddy

角色：

项目经理。

负责：

企业微信：

```
查看任务

启动任务

收集结果

提醒状态
```

不负责：

* 写代码
* 修改架构

---

## CodeBuddy

角色：

执行调度。

负责：

```
收到命令

调用Codex

返回结果
```

---

## Codex

角色：

高级工程师。

负责：

```
代码

测试

Debug

PR
```

---

# 第五阶段：自动化

## Step 7：增加 GitHub Actions

新增：

```
.github/workflows/
```

实现：

提交 PR 自动：

```
pytest

lint

frontend test

playwright
```

---

# Step 8：增加 Codex Skill

目录：

```
.codex/

skills/

├── task-bootstrap

├── delivery-check

├── data-audit

├── indicator-change

├── runtime-gate

└── release-check

```

---

## 第一个 Skill

task-bootstrap

功能：

检查：

```
当前branch

Issue

状态

权限

测试环境
```

不满足：

禁止开发。

---

# 第六阶段：新的日常流程

## 场景1：新需求

你：

ChatGPT：

```
增加实时预警
```

GPT：

读取 GitHub。

生成：

```
docs/design/live-alert.md

Issue #xxx
```

---

## 场景2：开发

企业微信：

```
执行 Issue #xxx
```

流程：

```
WorkBuddy

↓

CodeBuddy

↓

Codex

↓

PR
```

---

## 场景3：审核

GPT：

读取 PR。

检查：

* 架构
* 风险
* 是否符合设计

---

## 场景4：合并

你：

人工确认。

Merge。

---

# 最终架构

```
                         你

                  技术负责人


                         |


                 ChatGPT Chat

                    决策


                         |


                 ChatGPT Work

                    设计


                         |


================================================

                 GitHub Repository

================================================


       Docs       Issues       PR

       Code       Actions      History


================================================


        WorkBuddy          Codex

        项目管理          工程执行


             |

          CodeBuddy

          调度入口


             |

          企业微信


```

---

# 实施顺序总结

## Phase 0

确认 GitHub AI 能力

状态：

✅ 已完成

---

## Phase 1

GitHub AI 基础

顺序：

1. AGENTS.md
2. STATUS.md
3. docs结构整理

---

## Phase 2

任务系统

顺序：

1. Issue Template
2. Label
3. PR Template

---

## Phase 3

Codex 接入

顺序：

1. Issue读取
2. Codex执行
3. PR生成
4. Review

---

## Phase 4

自动化

顺序：

1. Actions
2. Skills
3. 状态同步

---

# 最终效果

以前：

```
AI工具之间传信息
```

升级：

```
AI共同操作一个项目世界
```

你的角色：

从：

```
AI操作员
```

变成：

```
归一量化技术负责人
```

---

我建议下一步实际执行时，不要一次让 Codex 大改整个工作站。

按照：

**Phase 1 → Phase 2 → Phase 3 → Phase 4**

四个阶段推进。

其中 Phase 1 完成后，GPT、WorkBuddy、Codex 三者的信息断层问题基本就解决了。你后续所有归一量化开发都会基于这个新体系。
