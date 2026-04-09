# Preview Runtime

用于持久化和复用 UI 预览/截图/可读性巡检脚本，统一放在 `preview-runtime`。

## 快速开始

1. 安装依赖（首次）：

```bash
npm --prefix preview-runtime install
```

2. 执行常用网盘链接预览（夜间/日间 + 管理弹窗 + 样式采样）：

```bash
npm --prefix preview-runtime run preview:quick-link
```

产物默认输出到：

- `preview-runtime/shots/quick-link-preview/resource-panel-night.png`
- `preview-runtime/shots/quick-link-preview/resource-panel-day.png`
- `preview-runtime/shots/quick-link-preview/resource-quick-link-modal-night.png`
- `preview-runtime/shots/quick-link-preview/resource-quick-link-modal-day.png`
- `preview-runtime/shots/quick-link-preview/report.json`

## 其他脚本

- `npm --prefix preview-runtime run preview:theme`：主题截图与调色板采样
- `npm --prefix preview-runtime run preview:modals`：常见页面/弹窗截图
- `npm --prefix preview-runtime run preview:contrast`：对比度巡检
- `npm --prefix preview-runtime run preview:readability`：可读性巡检
- `npm --prefix preview-runtime run preview:mermaid -- <input.mmd> <output.png>`：Mermaid 渲染截图

## 可选环境变量

- `PREVIEW_BASE_URL`（默认 `http://127.0.0.1:18080`）
- `PREVIEW_USERNAME`（默认 `admin`）
- `PREVIEW_PASSWORD`（默认 `admin123`）
- `PREVIEW_BROWSER_CHANNEL`（默认 `bundled`；可选 `bundled` / `chrome`。脚本会自动回退到另一种内核）
- `PREVIEW_LOCALE`（默认 `zh-CN`）
- `PREVIEW_WIDTH`（默认 `1512`）
- `PREVIEW_HEIGHT`（默认 `920`）
- `PREVIEW_HEADLESS`（默认 `true`，设为 `false` 可看浏览器过程）

示例：

```bash
PREVIEW_BASE_URL=http://127.0.0.1:18080 \
PREVIEW_USERNAME=admin \
PREVIEW_PASSWORD=admin123 \
npm --prefix preview-runtime run preview:quick-link
```
