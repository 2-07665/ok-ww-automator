# 消息通知

`src/ok_ww_automator/notices.py` 模块在任务执行器（Runner）完成所有重试尝试后，分发格式化的执行报告。

## 通知触发条件

默认情况下，通知会在所有最终任务状态（例如，`success` 成功, `failure` 失败, `needs review` 需要复查, `skipped` 跳过）下触发。中间的 `running`（运行中）状态不会触发通知。

## 支持的渠道

您可以使用以下环境变量启用通知：

```powershell
NOTICE_ENABLED=true
NOTICE_CHANNEL=mailgun,wxpusher
```

### Mailgun

通过 Mailgun API 发送 HTML 格式的电子邮件。

需要配置：
- `MAILGUN_API_KEY`
- `MAILGUN_DOMAIN`
- `MAILGUN_RECIPIENT`

### WxPusher

通过 WxPusher 的 simple-push API 发送富文本通知到微信。

需要配置：
- `WXPUSHER_SPT`

## 模板引擎

通知模块在 `src/ok_ww_automator/notice_templates/` 中使用了轻量级、无依赖的 HTML 模板。这些模板使用内联 CSS 并提供了针对移动设备优化的响应式布局。