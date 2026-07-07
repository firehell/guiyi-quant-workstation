# 权限分享 API

权限分享用于查看、添加、修改和删除产品或产品组的成员访问权限。CLI 统一使用 `permission` 资源名，贴近 AMS 服务端接口的 `resource_type` + `resource_id` 模型，底层对应 `products/{id}/permissions` 和 `product_groups/{id}/permissions`。

推荐显式传 `resource_type` 和 `resource_id`。`product_id_or_name`、`product_group_id_or_name` 仅作为便捷别名保留。

## `get permission-list`

获取某个产品或产品组的权限列表。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `resource_type` | string | 是 | 资源类型，见[资源类型](#资源类型) |
| `resource_id` | string | 是 | 资源 ID |
| `product_id_or_name` | string | 否 | 产品 ID/名称便捷别名；传该字段时可省略 `resource_type` 和 `resource_id` |
| `product_group_id_or_name` | string | 否 | 产品组 ID/名称便捷别名；传该字段时可省略 `resource_type` 和 `resource_id` |
| `fields` | string[]/string | 否 | CLI 返回字段列表，例如 `id`、`user_id`、`permission` |
| `limit` | integer | 否 | CLI 返回条数上限 |
| `format` | string | 否 | `json` 或 `ndjson` |

返回：`data.permissions[]` 为权限记录，支持 `format:"ndjson"`。

示例：

```powershell
rqamsc get permission-list --payload '{"resource_type":"products","resource_id":"..."}'
rqamsc get permission-list --payload '{"resource_type":"product_groups","resource_id":"...","fields":["id","user_id","permission","shared_by"],"format":"ndjson"}'
```

## `update permission`

给单个产品或产品组添加或修改权限。该命令是 upsert 语义：同一用户已有权限时会更新，没有权限时会新增。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `resource_type` | string | 是 | 资源类型，见[资源类型](#资源类型) |
| `resource_id` | string | 是 | 资源 ID |
| `permissions` | object[]/object | 是 | 权限记录列表，字段见[权限写入字段](#权限写入字段) |
| `product_id_or_name` | string | 否 | 产品 ID/名称便捷别名；传该字段时可省略 `resource_type` 和 `resource_id` |
| `product_group_id_or_name` | string | 否 | 产品组 ID/名称便捷别名；传该字段时可省略 `resource_type` 和 `resource_id` |

也可以用 `permission` 传单条权限对象，或把 `user_id`、`permission` 放在 payload 顶层。

返回：`data.effect_count` 为实际新增或修改数量；`data.error_messages[]` 为服务端逐条校验失败信息。

示例：

```powershell
rqamsc update permission --payload '{"resource_type":"products","resource_id":"...","permissions":[{"user_id":123456,"permission":"read_import_data"}]}'
rqamsc update permission --payload '{"resource_type":"product_groups","resource_id":"...","permission":{"permission_id":"...","user_id":123456,"permission":"write"}}'
```

## `delete permission`

按权限记录 ID 删除单个产品或产品组上的权限。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `resource_type` | string | 是 | 资源类型，见[资源类型](#资源类型) |
| `resource_id` | string | 是 | 资源 ID |
| `permission_ids` | string[]/string | 是 | 要删除的权限记录 ID；也可传 `permission_id` 或 `ids` |
| `product_id_or_name` | string | 否 | 产品 ID/名称便捷别名；传该字段时可省略 `resource_type` 和 `resource_id` |
| `product_group_id_or_name` | string | 否 | 产品组 ID/名称便捷别名；传该字段时可省略 `resource_type` 和 `resource_id` |

返回：`data.effect_count` 为删除数量。

示例：

```powershell
rqamsc delete permission --payload '{"resource_type":"products","resource_id":"...","permission_ids":["..."]}'
```

## `update permission-batch`

给多个同类资源批量添加或修改权限。每条 `permissions[]` 会应用到所有 `resource_ids`。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `resource_type` | string | 是 | 资源类型，见[资源类型](#资源类型) |
| `resource_ids` | string[]/string | 是 | 产品或产品组 ID 列表 |
| `permissions` | object[]/object | 是 | 权限记录列表，字段见[权限写入字段](#权限写入字段)；批量接口不使用 `permission_id` |
| `product_ids_or_names` | string[]/string | 否 | 产品 ID/名称列表；传该字段时可省略 `resource_type` 和 `resource_ids` |
| `product_group_ids_or_names` | string[]/string | 否 | 产品组 ID/名称列表；传该字段时可省略 `resource_type` 和 `resource_ids` |

返回：`data.effect_count` 为实际新增或修改数量；`data.error_messages[]` 为服务端逐条校验失败信息。

示例：

```powershell
rqamsc update permission-batch --payload '{"resource_type":"products","resource_ids":["...","..."],"permissions":[{"user_id":123456,"permission":"read_net_value"}]}'
rqamsc update permission-batch --payload '{"product_ids_or_names":["demo-a","demo-b"],"permissions":[{"user_id":123456,"permission":"read_position"}]}'
```

## 权限记录字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 权限记录 ID，删除或精确修改时使用 |
| `resource_id` | string | 产品或产品组 ID |
| `resource_type` | string | 资源类型，通常为 `product` 或 `product_groups` |
| `user_id` | integer | 被授权用户 ID |
| `workspace_id` | string | Workspace ID |
| `permission` | string | 权限值，见[权限值](#权限值) |
| `shared_by` | integer | 分享者用户 ID |

## 权限写入字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `user_id` | integer | 是 | 被授权用户 ID；该用户必须已经在当前 workspace 中 |
| `permission` | string | 是 | 权限值，见[权限值](#权限值) |
| `permission_id` | string | 否 | 已有权限记录 ID；单资源更新时可用于精确修改，也可用 `id` 代替 |

## 资源类型

| 取值 | 说明 |
| --- | --- |
| `products` | 产品权限；也接受 `product` |
| `product_groups` | 产品组权限；也接受 `product_group`、`group` |

## 权限值

权限从低到高如下：

| 取值 | 说明 |
| --- | --- |
| `forbidden` | 无权限 |
| `read_net_value` | 可查看一级，通常用于查看净值级数据 |
| `read_position` | 可查看二级，通常用于查看持仓级数据 |
| `read_import_data` | 可查看三级，通常用于查看导入数据、交易流水、估值表等更明细数据 |
| `write` | 可编辑 |
| `admin` | 管理员；不能通过权限分享接口授予，只能通过 workspace 管理员身份或资源创建者身份获得 |

服务端约束：

1. 被授权用户必须已在当前 workspace 中。
2. 分享给他人的权限不能高于操作者自己对该资源的权限。
3. 产品组权限会受子产品权限约束；对产品组管理员或创建者设置的权限不能高于其对子产品的最小权限。
4. 产品权限变化后，服务端会级联更新相关产品组权限和已分享出去的权限。
