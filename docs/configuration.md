# 环境变量（进阶）

> 大多数用户不需要改环境变量，页面里的「参数配置」已经覆盖了日常要调的东西。这一页适合按机器性能、网络情况或部署方式微调。

## 先搞清楚一件事：`.env` 不等于容器环境变量

仓库 `compose.yml` 只往容器里传了 `TZ`，其余都靠 compose 的 `${...}` 插值使用 `./.env`（端口、目录、容器名）。
所以：**把下面这些变量写进 `.env` 不会自动进入容器**，必须在 `compose.yml` 的 `environment:` 里显式加，

```yaml
    environment:
      - TZ=Asia/Shanghai
      - CROSS_COPY_MAX_CONCURRENT=2      # 例：想加哪个就加哪个
```

或改用 `env_file: [.env]`（注意这样 `.env` 里的 `MH_*` 也会一并进容器，无副作用但看着杂）。

## 常用变量

- `TZ`：容器时区，建议 `Asia/Shanghai`
- `UVICORN_ACCESS_LOG`：是否启用 HTTP 访问日志，默认 `0`；排查接口访问时可设为 `1`
- `UI_PUSH_DEBOUNCE_SECONDS`：状态流推送合并等待秒数，默认 `0.35`；NAS 这类低功耗机器可适当调大
- `UI_STATUS_LOG_TAIL_LIMIT`：状态流里下发的日志尾部条数，默认 `160`；日志很多时可适当调小
- `UI_STATUS_STREAM_LOG_TAIL_LIMIT`：轮询/推送流单次下发的日志条数，默认 `40`
- `UI_STATUS_LOG_MEMORY_LIMIT`：内存里保留的状态日志条数，默认 `220`；只想保留更少历史时可调小
- `STRM_PROXY_MODE`：STRM 播放模式默认值，默认 `redirect_direct`
- `SESSION_HTTPS_ONLY`：只在反代 HTTPS 场景用，设为 `1` 时会话 Cookie 带 `Secure`（HTTP 直连请勿开启，开了一登录就掉）
- `API_115_RATE_LIMIT_SECONDS`：115 API 最小间隔，默认 `0.35`；账号风控明显时可调大
- `API_115_LIST_CACHE_TTL_SECONDS`：115 目录列表缓存秒数，默认 `60`
- `API_115_LIST_CACHE_MAX_ROWS`：115 目录列表缓存最大行数，默认 `2000`
- `API_115_DOWNLOAD_URL_CACHE_TTL_SECONDS`：115 下载链接缓存秒数，默认 `20`
- `API_115_DOWNLOAD_URL_CACHE_MAX_ENTRIES`：115 下载链接缓存最大条数，默认 `1000`
- `TG_CHANNEL_THREADS_DEFAULT`：TG 同步默认线程数，默认 `6`；代理不稳时建议调低
- `TG_CHANNEL_SYNC_LIMIT_DEFAULT`：TG 同步时每个频道默认抓取资源数，默认 `10`，页面配置可覆盖
- `PANSOU_SEARCH_TIMEOUT_SECONDS`：PanSou 搜索请求超时秒数，默认 `15`
- `PANSOU_SEARCH_TOTAL_LIMIT`：PanSou 搜索结果截断上限，默认 `80`
- `TMDB_API_BASE_URL` / `TMDB_IMAGE_BASE_URL`：需要自定义 TMDB 访问地址时再配置
- `RESOURCE_JOB_COMPLETED_KEEP` / `RESOURCE_JOB_FAILED_KEEP`：任务中心完成/失败记录保留上限，默认 `1000` / `500`
- `RESOURCE_JOB_PRUNE_INTERVAL_SECONDS`：任务历史后台清理间隔秒数，默认 `600`（范围 60–86400）
- `CROSS_COPY_MAX_CONCURRENT`：同时运行的跨盘复制任务数，默认 `2`（范围 1–8；排队中的任务不占名额）
- `CROSS_COPY_DOWNLOAD_SEGMENT_MB`：下载分段大小（MB），默认 `16`（范围 1–128）；夸克对整文件流式限速、对分段请求不限速，调小分段能更细地断点续传
- `CROSS_COPY_DOWNLOAD_PARALLEL`：同任务内并行下载的段数，默认 `3`（范围 1–8）；`1` 即串行，带宽充足时可调大
- `CORS_ALLOW_ORIGINS` / `CORS_ALLOW_CREDENTIALS`：调用 Webhook 的跨域收窄，见 [webhook.md](webhook.md)

CLI 专属环境变量（见 [cli.md](cli.md)）：`MH_USERNAME` / `MH_PASSWORD` / `MH_API_BASE` / `MH_COOKIE_FILE` / `MH_CONTAINER`。
