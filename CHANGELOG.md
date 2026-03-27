# Changelog

All notable changes to this project will be documented in this file. The format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [2.2.2] - 2026-03-27
- 监控页状态同步改为 `SSE` 优先、低频轮询兜底，减少前后端高频轮询请求。
- 优化文件夹监控任务按钮交互，降低列表刷新导致首次点击不稳定的问题。
- 调整监控日志分隔层级与汇总展示，任务边界更清晰，汇总数字支持语义着色。
- 版本信息更新至 `2.2.2`，构建时间调整为 `2026-03-27 19:42`（UTC+8）。

## [2.2.1] - 2026-03-26
- 关于页展示版本与更新信息。
- 优化日间模式下关于页按钮和文字对比度，提升可读性与视觉层次。
- 版本信息更新至 `2.2.1`，构建时间调整为 `2026-03-26 23:18`（UTC+8）。

## [2.2.0] - 2026-03-26
- 目录树任务在每次联网同步前自动调用 AList 刷新接口，避免 tree.txt 读取到旧缓存。
- 新增 `version.json` 与本文档，用于规范化版本号和更新日志。
- Docker 镜像支持通过 `APP_VERSION` 构建参数写入 OCI 元数据。
- Web UI 会在检测到远端最新版本时显示提示横幅，可引导到 GitHub 查看更新内容。

## [2.1.0] - 2026-02-?? *(历史版本)*
- 初始前端顶部展示静态版本号。
- webhook 支持根据 savepath/sharetitle 进行局部目录刷新。

> 早期版本只有零散 commit 说明，如需追溯可查看仓库历史。
