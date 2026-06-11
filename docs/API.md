# 声笺 API v1.2

所有接口仅监听本机地址。除健康检查和认证初始化外，接口需要有效登录会话。

## 通用约定

- 成功响应使用 JSON，下载接口除外。
- 异步任务创建返回 `202 Accepted`。
- 错误统一为 `{"error":{"code":"...","message":"..."}}`。
- 每个响应包含 `X-Request-ID`，可用于关联本地日志。
- 普通用户只能访问自己的任务和历史，管理员可访问全局任务。

## 页面路由

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/` | 极简快速开始首页 |
| GET | `/studio` | 完整创作工作台 |
| GET | `/admin` | 管理后台 |

## 认证

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/auth/status` | 查询初始化及登录状态 |
| POST | `/auth/setup` | 首次创建管理员 |
| POST | `/auth/login` | 登录 |
| POST | `/auth/logout` | 退出 |
| GET | `/auth/me` | 当前用户 |

用户名为 3-32 位字母、数字、点、短横线或下划线。密码长度为 8-128 位。

## 用户管理

仅管理员可用。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/admin/users` | 用户列表 |
| POST | `/admin/users` | 创建用户 |
| PATCH | `/admin/users/<id>` | 修改角色、启用状态或重置密码 |

系统禁止禁用或降级最后一个启用的管理员。

## 转换

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/tasks` | 当前用户任务列表；管理员返回全局任务 |
| DELETE | `/tasks/<kind>/<id>` | 删除已结束的文本或批量任务 |
| POST | `/preview` | 生成前 300 字试听 |
| POST | `/convert` | 创建文本任务 |
| GET | `/jobs/<id>` | 查询文本任务 |
| POST | `/jobs/<id>/cancel` | 取消任务 |
| POST | `/jobs/<id>/items/<item_id>/retry` | 重试失败片段 |
| GET | `/jobs/<id>/download` | 下载合并后的 MP3 |
| POST | `/jobs/<id>/save` | 保存 MP3 到管理员配置的默认目录 |
| GET | `/jobs/<id>/items/<item_id>/audio` | 播放单个片段 |

`/convert` 使用表单参数：`text`、`provider`、`voice`、`speech_rate`、`volume`、`pitch`。
`provider` 可取 `edge`、`cosyvoice` 或 `kokoro`，省略时使用系统默认引擎。

任务响应包含 `created_at`、`started_at`、`elapsed_seconds`、
`estimated_remaining_seconds`、`finished_at`、`queue_position` 和分项时间字段。

## 用户偏好

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/preferences` | 音色偏好、配置收藏和自动下载偏好 |
| PATCH | `/preferences/workspace` | 更新用户级自动下载策略 |
| GET | `/config-favorites` | 获取完整参数配置收藏 |
| POST | `/config-favorites` | 收藏音色、语速、音量和音高组合 |
| DELETE | `/config-favorites/<id>` | 删除配置收藏 |

## 批量任务

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/batch/convert` | 上传最多 20 个 TXT 文件 |
| GET | `/batch/status/<id>` | 查询任务 |
| POST | `/batch/job/<id>/cancel` | 取消任务 |
| POST | `/batch/job/<id>/items/<item_id>/retry` | 重试失败文件 |
| GET | `/batch/download/<id>` | 下载成功结果 ZIP |
| POST | `/batch/job/<id>/save` | 保存 ZIP 到默认目录 |
| GET | `/batch/download/<id>/<item_id>` | 下载单个 MP3 |
| DELETE | `/batch/job/<id>` | 删除已结束任务及文件 |

## 配置与诊断

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/providers` | 登录用户 | Provider 能力、启用状态与健康状态 |
| GET | `/voices?provider=<id>` | 登录用户 | 获取指定 Provider 的动态音色目录 |
| GET | `/settings` | 登录用户 | 普通用户收到脱敏配置 |
| POST | `/settings` | 管理员 | 更新系统设置 |
| POST | `/voices/refresh` | 管理员 | 刷新并缓存在线中文音色 |
| GET | `/health` | 公开 | 本机健康检查 |
| GET | `/diagnostics` | 登录用户 | 网络与运行状态 |
| GET | `/diagnostics/download` | 登录用户 | 导出脱敏诊断 ZIP |
| GET | `/admin/logs` | 管理员 | 查询运行日志或审计日志 |
| GET | `/admin/logs/download` | 管理员 | 下载当前 JSONL 日志 |

诊断包不包含输入文本、密码哈希或音频文件。
本地 Provider 的服务端契约见 [LOCAL_TTS.md](LOCAL_TTS.md)。

`/admin/logs` 支持 `kind=application|audit`、`level`、`query`、`page` 和 `page_size`
参数，按最新日志优先返回分页结果。响应包含 `total`、`pages`、`has_prev` 和
`has_next`；旧版 `limit` 参数仍可作为 `page_size` 使用。
日志记录请求元数据、任务 ID、用户 ID、Provider 和操作结果，不记录用户正文。
