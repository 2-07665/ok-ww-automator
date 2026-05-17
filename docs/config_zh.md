# 运行时配置

`ok-ww-automator` 从进程环境加载运行时配置，并由可选的 `.env` 文件作为补充。如果两个地方都存在相同的变量，则以进程环境变量为准。

## 环境文件解析

默认情况下，应用程序会相对于项目根目录查找 `env/.env`。
您可以通过设置 `ENV_FILE` 环境变量来覆盖此行为。如果仅提供文件名（例如，`ENV_FILE=cn.env`），它将解析为 `env/cn.env`。这使得 Windows 任务计划程序中的命令保持简洁。

您可以将 `env/.env.example` 用作新账号的模板。

## 集成开关与密钥

配置模块被设计为延迟失败（fail lazily）。只有在实际执行可选功能时，才会验证相关的密钥和凭据。

- **游戏执行**: 启动游戏适配器之前需要 `GAME_EXE_PATH`。
- **Google Sheets**: 读取或追加数据到表格需要 `GOOGLE_SHEET_ID` 和 `GOOGLE_SERVICE_ACCOUNT_JSON_BASE64`。需要安装 `[sheets]` 额外依赖。
- **Waves API**: 如果 `WAVES_API_ENABLED=true`，则需要 `WAVES_ROLE_ID`, `WAVES_TOKEN` 和 `WAVES_DID`。需要安装 `[waves]` 额外依赖。
- **消息通知**: 如果 `NOTICE_ENABLED=true`，则需要特定于 `NOTICE_CHANNEL` 的密钥（如 `MAILGUN_API_KEY` 或 `WXPUSHER_SPT`）。需要安装 `[notice]` 额外依赖。

## 环境变量

| 变量 | 默认值 | 描述 |
| --- | --- | --- |
| `ENV_FILE` | `env/.env` | dotenv 文件的路径。 |
| `GAME_EXE_PATH` | *未设置* | `Wuthering Waves.exe` 的绝对路径。 |
| `DAILY_HOUR` | `5` | 预期的日常任务运行小时 (0-23, UTC+8)。用于体力计算。 |
| `DAILY_MINUTE` | `0` | 预期的日常任务运行分钟 (0-59)。 |
| `GOOGLE_SHEET_ID` | *未设置* | 目标 Google Spreadsheet ID。 |
| `GOOGLE_SERVICE_ACCOUNT_JSON_BASE64` | *未设置* | Base64 编码的 Service Account JSON 凭据。 |
| `SHEET_NAME_CONFIG` | `Config` | 配置工作表的名称。 |
| `SHEET_NAME_DAILY` | `DailyRuns` | 日常结果日志工作表的名称。 |
| `SHEET_NAME_STAMINA` | `StaminaRuns` | 体力结果日志工作表的名称。 |
| `SHEET_NAME_FASTFARM` | `5to1` | 快速刷取结果日志工作表的名称。 |
| `WAVES_API_ENABLED` | `false` | 启用库洛/Waves API 进行快速体力检查。 |
| `WAVES_ROLE_ID` | *未设置* | Waves API 角色 ID。 |
| `WAVES_TOKEN` | *未设置* | Waves API Token。 |
| `WAVES_DID` | *未设置* | Waves API 设备 ID。 |
| `RETRY_MAX_ATTEMPTS` | `2` | 失败前的最大游戏启动尝试次数。 |
| `RETRY_DELAY_SECONDS` | `30` | 游戏启动重试之间的等待时间。 |
| `NOTICE_ENABLED` | `false` | 启用运行后通知。 |
| `NOTICE_CHANNEL` | *未设置* | 逗号分隔的通知渠道列表 (`mailgun`, `wxpusher`)。 |
| `NOTICE_ACCOUNT_ID` | *未设置* | 通知主题前缀的显示标签。 |
| `MAILGUN_API_KEY` | *未设置* | Mailgun API 密钥。 |
| `MAILGUN_DOMAIN` | *未设置* | Mailgun 发送域名。 |
| `MAILGUN_RECIPIENT` | *未设置* | 接收通知的目标邮箱地址。 |
| `WXPUSHER_SPT` | *未设置* | WxPusher simple-push token。 |

*(注意：布尔变量接受 `true`, `1`, `yes`, `on`, `是` 及其对应的否定值。)*