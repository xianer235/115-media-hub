# 资源中心同步完成后刷新设计

## 背景

资源中心点击“同步频道”后，后台同步任务会通过 SSE 和资源状态轮询推送 `channel_sync` 状态。同步进行中使用 `compact=1` 的轻量 `/resource/state` 请求，以降低轮询开销。

当前问题是：轻量轮询可能先收到“同步完成”状态。`applyResourceState` 会更新本地 `channel_sync`，但明确关闭完成后的完整刷新；之后 SSE 再收到相同的完成状态时，前端已经不再观察到“进行中 -> 完成”的状态迁移，因此频道资源卡片不会更新。

## 目标与边界

- 搜索框为空时，同步从进行中变为完成后，自动请求一次完整资源状态并刷新频道资源卡片。
- 搜索框有搜索词时，不触发频道概览刷新，保留当前搜索结果和搜索状态。
- 同步状态栏、SSE、无 SSE 时的轮询都继续可用。
- 不修改后端同步任务、资源存储、搜索接口或资源卡片渲染结构。

## 方案

复用 `static/js/index.js` 中已有的 `handleResourceChannelSyncStateChange` 完成迁移处理：

1. `applyResourceState` 只在处理 `compact` 响应时允许完成迁移触发后续刷新；完整响应已经包含频道资源数据，不需要再请求一次。
2. 完成迁移处理在发起完整刷新前读取搜索框，并同时参考 `resourceState.search`：只要存在搜索词就跳过刷新；为空时调用现有 `refreshResourceState({ allowSearch: false })`。
3. 使用现有的 `lastResourceChannelSyncFinishNotifiedAt` 去重，避免轮询和 SSE 对同一完成时间重复触发请求。

这样保留了 5 月引入的轻量轮询优化，同时补回同步完成后的资源数据刷新行为。

## 测试

- 新增前端状态策略回归测试，验证：
  - 进行中 -> 完成且搜索为空：需要刷新。
  - 进行中 -> 完成且存在搜索词：不刷新。
  - 完成 -> 完成或非 `compact` 更新：不重复刷新。
- 运行资源相关定向测试、完整 unittest、JS 语法检查、Python 编译检查和 `git diff --check`。
- 若 Docker daemon 可用，再按 `AGENTS.md` 重建容器并手动验证空搜索同步与带搜索词同步两条路径。

