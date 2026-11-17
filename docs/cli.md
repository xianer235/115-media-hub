# 命令行工具（CLI）

`cli.py` 是运行在宿主机上的命令行客户端（不进入容器镜像），通过面板自身的 HTTP API 完成搜索、订阅、转存、监控、刮削等操作，方便 AI 代理或脚本直接管理媒体中心，无需打开网页。

## 安装

依赖只装在宿主机，与容器镜像无关：

```bash
python3 -m venv .cli-venv
.cli-venv/bin/pip install -r requirements-cli.txt
```

## 登录

账号密码与网页登录一致，需先设置环境变量；非交互环境未提供凭据时会直接报错（不会静默用默认口令）：

```bash
export MH_USERNAME=admin
export MH_PASSWORD=你的面板密码
export MH_API_BASE=http://127.0.0.1:18080   # 可选，默认即本机
.cli-venv/bin/python cli.py status
.cli-venv/bin/python cli.py search "黑客帝国 4K"
.cli-venv/bin/python cli.py subscribe list
```

## 常用命令

`status` / `version` / `search <关键词>|--cancel` / `channels sync` /
`subscribe list|add|remove|start` / `jobs list|retry|cancel` /
`scrape jobs-create|batch-preferences` /
`cross-copy list|create|cancel|retry|delete|clear|capabilities`（跨盘复制任务）/
`monitor list|start|stop` / `tree list|create|update|delete|defaults|run|full|jobs` /
`offline list [--page N]` / `sources search` / `daemon status|logs|restart`。

- 完整命令列表见仓库根目录 `CLI-API-AUDIT.md`；每个子命令都支持 `--help` 查看参数
- 会话 Cookie 默认保存到 `/tmp/.115_cookies.txt`（权限 0600），可用 `MH_COOKIE_FILE` 覆盖
- `sources` / `daemon` 等容器运维命令需要宿主机安装 Docker，容器名自动识别 `115-media-hub` / `115-media-hub-test`，也可用环境变量 `MH_CONTAINER` 覆盖

## 批量整理与监控任务

```bash
# 读取 / 设置 / 清除某网盘的批量整理偏好（文件命名方式、文件夹开关、删除广告等）
.cli-venv/bin/python cli.py scrape batch-preferences get --provider 115
.cli-venv/bin/python cli.py scrape batch-preferences set --provider 115 --options-json '{"file_name_mode":"keep"}'
.cli-venv/bin/python cli.py scrape batch-preferences clear --provider 115

# 生成重命名预览时传入命名选项（keep 保持原名 / clean 仅清理广告 / standard 标准重命名）
.cli-venv/bin/python cli.py scrape rename-plan "/影视/剧集" --file-name-mode clean --no-season-subfolder --delete-ad-files

# 创建普通监控任务（只扫描生成 STRM；整理选项已归接收夹，不再挂在监控任务上）
.cli-venv/bin/python cli.py monitor add 自存影视 --scan-path /115/自存影视 --target-path /strm/自存影视 --cron-minutes 30
```

`scrape rename-plan` 支持 `--file-name-mode keep|clean|standard`、`--no-rename-folders`、`--no-season-subfolder`、`--include-tmdb-id`、`--delete-ad-files`、`--title-language auto|zh|en`、`--season`、`--episode-mode auto|seasonal|absolute`、`--preserve-file-info`，或直接用 `--options-json` 传完整选项对象。监控任务只负责扫描生成 STRM，整理选项（文件命名方式、Season 子目录、删除广告文件等）现在配置在**接收夹任务**上，在面板「文件夹监控 → 接收夹」弹窗里设置。

## 目录树任务

```bash
# 查看自动填充参数 / 创建任务（--folder 指定 115 文件夹路径，--name 可选）
.cli-venv/bin/python cli.py tree defaults --folder "影视库/电视剧"
.cli-venv/bin/python cli.py tree create --folder "影视库/电视剧" --name "目录树-电视剧"

# 列表 / 增量同步（run 不带 --id 时对所有任务仅做 sha1 对比更新）/ 全量重写
.cli-venv/bin/python cli.py tree list
.cli-venv/bin/python cli.py tree run --id <任务ID>
.cli-venv/bin/python cli.py tree full --id <任务ID>
```

## 跨盘复制

见 [cross-copy.md](cross-copy.md) 的「命令行也能复制」一节。
