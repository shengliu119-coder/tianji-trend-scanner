# 天机伏击趋势扫描器

这个仓库用于 GitHub Actions 每小时自动扫描币圈、美股和 A股趋势机会。它只在出现 A/B 类机会或已推送信号发生关键状态变化时推送飞书；无机会时静默。

## 你需要做的操作

1. 在 GitHub 创建仓库，建议私有仓库。
2. 上传本目录全部文件。
3. 在仓库 `Settings -> Secrets and variables -> Actions` 新增：

```text
Name: FEISHU_WEBHOOK
Value: 你的飞书机器人 Webhook
```

4. 进入 `Actions -> scan -> Run workflow` 手动运行一次。

## 本地测试

```bash
pip install -r requirements.txt
DRY_RUN=1 python scanner.py
```

`DRY_RUN=1` 时不会发飞书，只会在日志中打印消息。

## 设计原则

- 不连接账户。
- 不读取持仓。
- 不自动交易。
- 数据不可用就跳过，不编造行情。
- 已拉离、低盈亏比、财报/公告扰动、涨停附近、弱指数非龙头，一律不推。

## 重要限制

公开行情源可能偶发失败，第一版以低成本和稳定静默为优先。后续如果你需要更高可靠性，可以把行情源升级为付费 API 或迁移到低价 VPS。
