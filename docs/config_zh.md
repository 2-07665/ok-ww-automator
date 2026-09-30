# 账号配置

[English](config.md) · [运行说明](operations_zh.md)

从 `env/.env.example` 复制一个账号文件。调度器发现 `env/*.env`，排除示例；`.env` 的账号名为 `default`，其他文件去掉 `.env` 后即为账号名。进程环境变量优先于文件，因此避免在多账号任务的全局环境中设置账号专属凭据。

单独使用配置或 Sheets CLI 时，默认文件为 `env/.env`；`ENV_FILE=cn.env` 会解析为 `env/cn.env`。调度器通过 `--account cn` 选择配置。值保留中文，不展开 shell 变量。双引号内会解析 `\n`、`\r`、`\t` 等转义。Windows 路径请用单引号、不加引号或使用正斜杠，例如 `GAME_EXE_PATH='D:\new\tools\Game.exe'`。

日常/体力需要 Sheets 凭据，游戏尝试需要 `GAME_EXE_PATH`。周常需要 `GAME_SERVER`、游戏及可选 WxPusher 配置。Waves API、通知和 Healthchecks 启用时才需要其对应凭据；Healthchecks 需要日常和体力两个 UUID。

## 环境变量

自动任务和启动器的“启动游戏”使用 `Client -krqlv=<quality> -SkipSplash`。请使用与已安装资源一致的档位；未安装的档位可能自动下载数 GB 资源，不会自动回退到高清。未填写此项时默认使用高清。两种启动方式均允许进程环境变量覆盖此设置。

| 变量 | 默认值 | 描述 |
| --- | --- | --- |
| `ENV_FILE` | `env/.env` | dotenv 文件的路径。 |
| `GAME_SERVER` | *未设置* | 周常必填：`CN`、`US`、`EU`、`ASIA`、`SEA`、`HMT`，不区分大小写。每个账号单独配置，不根据文件名推断。 |
| `GAME_EXE_PATH` | *未设置* | `Wuthering Waves.exe` 的绝对路径。 |
| `GAME_RESOURCE_QUALITY` | `hd` | 游戏资源档位：`sd`（流畅）、`hd`（高清）、`uhd`（极致）。忽略大小写及首尾空格；空值和无效值会报错。 |
| `DAILY_HOUR` | `5` | 预期的日常任务运行小时 (0-23, UTC+8)。用于体力计算。 |
| `DAILY_MINUTE` | `0` | 预期的日常任务运行分钟 (0-59)。 |
| `WEEKLY_RUN_DAYS` | `1,2,3,4,5,6,7` | 每账号允许执行周常的服务器时间自然日，1=周一至7=周日，例如 `1,3,5`；未设置或留空表示每天。手动周常忽略此限制。 |
| `WEEKLY_NOTICE_DAY` | `7` | 周常未成功的通知日（服务器时间），1=周一至7=周日。当日或之后触发时，本周未完成就通知，非执行日也检查。 |
| `GOOGLE_SHEET_ID` | *未设置* | 目标 Google Spreadsheet ID。 |
| `GOOGLE_SERVICE_ACCOUNT_JSON_BASE64` | *未设置* | Base64 编码的 Service Account JSON 凭据。 |
| `SHEET_NAME_CONFIG` | `Config` | 配置工作表的名称。 |
| `SHEET_NAME_DAILY` | `DailyRuns` | 日常结果日志工作表的名称。 |
| `SHEET_NAME_STAMINA` | `StaminaRuns` | 体力结果日志工作表的名称。 |
| `SHEET_NAME_FASTFARM` | `5to1` | 旧版刷取结果写入接口的工作表；当前速刷/五合一不会自动写入。 |
| `WAVES_API_ENABLED` | `false` | 启用库洛/Waves API 进行快速体力检查。 |
| `WAVES_ROLE_ID` | *未设置* | Waves API 角色 ID。 |
| `WAVES_TOKEN` | *未设置* | Waves API Token。 |
| `WAVES_DID` | *未设置* | Waves API 设备 ID。 |
| `RETRY_MAX_ATTEMPTS` | `2` | 运行器最多尝试次数（至少 1）；周常另有最多 2 次及总时限。 |
| `RETRY_DELAY_SECONDS` | `30` | 游戏启动重试之间的等待时间。 |
| `NOTICE_ENABLED` | `false` | 启用运行后通知。 |
| `NOTICE_CHANNEL` | *未设置* | 逗号分隔的通知渠道列表 (`mailgun`, `wxpusher`)。 |
| `NOTICE_ACCOUNT_ID` | *未设置* | 通知主题前缀的显示标签。 |
| `NOTICE_SKIP_SUCCESS` | `false` | 当最终任务结果为 `success` 或 `skipped` 时跳过通知。 |
| `MAILGUN_API_KEY` | *未设置* | Mailgun API 密钥。 |
| `MAILGUN_DOMAIN` | *未设置* | Mailgun 发送域名。 |
| `MAILGUN_RECIPIENT` | *未设置* | 接收通知的目标邮箱地址。 |
| `WXPUSHER_SPT` | *未设置* | WxPusher simple-push token。 |
| `HEALTHCHECKS_ENABLED` | `false` | 启用 Healthchecks.io 运行监控 ping。 |
| `HEALTHCHECKS_DAILY_UUID` | *未设置* | 日常任务的 Healthchecks.io check UUID。 |
| `HEALTHCHECKS_STAMINA_UUID` | *未设置* | 体力任务的 Healthchecks.io check UUID。 |


布尔值接受 `true/false`、`1/0`、`yes/no`、`on/off`、`是/否`，忽略英文大小写。

`DAILY_HOUR`/`DAILY_MINUTE` 仅供北京时间体力预测；Windows 触发器使用系统本地时间。周常以所配置服务器时间周一 04:00 重置，执行日和通知日详见[运行说明](operations_zh.md#周常乐园)。
