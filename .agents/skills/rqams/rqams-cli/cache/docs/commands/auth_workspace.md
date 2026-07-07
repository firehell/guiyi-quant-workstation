# 认证与 Workspace API

认证命令保存 RQAMS 登录态；workspace 命令用于选择后续业务请求使用的 workspace。

## `setup`

交互式配置 RQAMS 登录态和默认 workspace。首次安装后推荐直接运行：

```powershell
rqamsc setup
```

CLI 会依次提示输入 AMS 服务地址、用户名、密码，并在登录成功后列出可用 workspace 供选择。配置会保存到本地，后续业务命令会自动复用。

如果需要非交互式配置，也可以使用 payload：

```powershell
rqamsc setup --payload '{"base_url":"https://www.ricequant.com","username":"...","password":"...","workspace_name_or_id":"default"}'
```

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `base_url` | string | 是 | RQAMS 服务地址，例如 `https://www.ricequant.com` |
| `username` | string | 是 | 用户名；如果输入 11 位中国大陆手机号，CLI 会自动补 `+86` 后登录并保存 |
| `password` | string | 是 | 密码 |
| `workspace_name_or_id` | string | 否 | Workspace 名称或 ID；不传时非交互式 setup 会使用第一个 workspace |
| `profile` | string | 否 | 本地配置 profile，用于隔离不同账号或 workspace |

返回字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `authenticated` | boolean | 是否登录成功 |
| `user_id` | string | 用户 ID |
| `workspace_id` | string | 保存后的 workspace ID |
| `workspace_name` | string | Workspace 名称 |
| `display` | string | 便于展示的 workspace 名称 |
| `config_saved` | boolean | 是否已保存到本地配置 |
| `plaintext` | boolean | 是否以本地明文配置保存密码和登录态 |

## `auth`

登录 RQAMS，并默认把密码和返回的 session 保存到本地配置。后续命令会复用该登录态；session 过期时，CLI 会用本地保存的密码自动重新登录并刷新 session。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `base_url` | string | 是 | RQAMS 服务地址，例如 `https://www.ricequant.com` |
| `username` | string | 是 | 用户名；如果输入 11 位中国大陆手机号，CLI 会自动补 `+86` 后登录并保存 |
| `password` | string | 是 | 密码 |
| `profile` | string | 否 | 本地配置 profile，用于隔离不同账号或 workspace |

返回字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `authenticated` | boolean | 是否登录成功 |
| `user_id` | string | 用户 ID |
| `profile` | string | 写入的本地配置 profile |
| `config_saved` | boolean | 是否已保存到本地配置 |
| `plaintext` | boolean | 是否以本地明文配置保存密码和登录态 |

示例：

```powershell
rqamsc auth --payload '{"base_url":"https://www.ricequant.com","username":"...","password":"..."}'
rqamsc auth --payload '{"profile":"acct-a-w1","base_url":"https://www.ricequant.com","username":"...","password":"..."}'
```

## `get workspace-list`

查询当前账号可用 workspace。

Payload: `{}`。

返回：`data` 为 `/api/user/v1/workspaces` 原始响应，workspace 列表位于 `data.data[]`。

Workspace 字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | Workspace ID |
| `name` | string | Workspace 名称 |
| `admin` | string/int | Workspace 管理员用户 ID |
| `capacity` | number | Workspace 人数上限 |
| `ctime` | string/datetime | Workspace 创建时间 |
| `description` | string | Workspace 描述 |
| `users[]` | array | Workspace 成员列表 |

## `use workspace`

选择并保存当前 workspace。可以传 workspace ID，也可以传 workspace 名称；传名称时 CLI 会查询 workspace 列表并解析为 ID。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `workspace_name_or_id` | string | 是 | Workspace 名称或 ID |
| `profile` | string | 否 | 要更新的本地配置 profile |

返回字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `workspace_id` | string | 保存后的 workspace ID |
| `workspace_name` | string | Workspace 名称 |
| `profile` | string | 写入的本地配置 profile |
| `config_saved` | boolean | 是否已保存 |

示例：

```powershell
rqamsc use workspace --payload '{"workspace_name_or_id":"default"}'
rqamsc use workspace --payload '{"profile":"acct-a-w1","workspace_name_or_id":"default"}'
```

业务命令也可以在 payload 顶层传 `profile`，用于选择对应的本地登录态和 workspace：

```powershell
rqamsc get product-list --payload '{"profile":"acct-a-w1"}'
```

## `get current-workspace`

查看当前本地配置中的 workspace。未配置 workspace 时，CLI 会读取 workspace 列表并使用第一项作为默认值返回。

Payload: `{}`。

返回字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `workspace_id` | string | 当前 workspace ID |
| `workspace_name` | string | 当前 workspace 名称 |
| `display` | string | 便于展示的名称 |
| `defaulted` | boolean | 是否由 CLI 选择默认 workspace |
