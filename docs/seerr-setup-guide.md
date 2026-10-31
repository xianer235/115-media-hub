# Seerr 点播对接配置教程（本电脑测试用）

> 对应功能：115 Media Hub 的 Radarr/Sonarr v3 兼容层（2026-10-24 提交 `900da5e`）。
> 本教程面向「在本机部署 Seerr 并亲自测试」的场景，全程约 20 分钟。

---

## 0. 先分清：这三个东西分别是什么

家庭影院的点播链路由三个角色组成：

| 角色 | 是什么 | 谁在用 |
| --- | --- | --- |
| **115 Media Hub**（你的面板） | 后台干活的：管网盘、订阅追更、找资源、转存、生成 STRM | 你 |
| **Seerr** | 前台选片下单的网页：搜电影/剧集、提交请求、看进度 | 家人 |
| **Radarr / Sonarr** | 业界通用的「点播标准接口」——Radarr 管电影，Sonarr 管剧集 | 没人直接用，软件之间靠它对话 |

Seerr 只会说 Radarr/Sonarr 这套"标准语言"。本次改造让你的面板**伪装成一台 Radarr + 一台 Sonarr**，所以：

- 在 Seerr 里要加**两条服务器**：一条 Radarr（电影点播走它）、一条 Sonarr（剧集点播走它）
- 两条的地址、端口、API Key **填的内容完全一样**，都指向你的面板
- 家人点播后，请求会变成面板「影视订阅」页里的一个任务，之后全自动

```
家人在 Seerr 点播 ──▶ Seerr 按 Radarr/Sonarr 标准协议 ──▶ 115 Media Hub（/api/v3）
                                                              │
                                                自动建订阅任务 → 找资源 → 转存 → 入库 → STRM
```

---

## 1. 面板侧准备（2 分钟）

1. 打开面板 → **参数配置 → 后台安全管理**
2. 找到「**点播接口 API Key**」→ 点「**随机生成密钥**」→ 出现一串 32 位字符
3. 找到「**电影点播保存目录**」→ 填一个 115 网盘里的目录，例如 `媒体库/网盘电影`
   - 电影点播会在此目录下自动建「片名 (年份)」子目录，例如 `媒体库/网盘电影/黑客帝国 (1999)/`
4. 找到「**电视剧点播保存目录**」→ 填另一个目录，例如 `媒体库/网盘电视剧`
   - 剧集点播会在此目录下自动建「剧名 (年份)/Season NN」两层，例如 `媒体库/网盘电视剧/绝命毒师 (2008)/Season 01/`
   - 电影与剧集分开建目录，避免混在一起
   - 两项都留空时回退旧版「点播默认保存目录」（`servarr_default_savepath`）
5. 拉到页面底部点「**保存全部配置**」
6. 顺手确认「参数配置」里 **TMDB 增强已开启**（有 API Key）——点播链路依赖它做影片识别

> 密钥只显示这一次，建议先复制到备忘录；忘了可以重新生成，记得两个地方（面板和 Seerr）要一致。

---

## 2. 在本电脑部署 Seerr（Docker，一条命令）

前提：已安装 Docker Desktop 并正在运行。在终端执行：

```bash
mkdir -p ~/seerr-test/config

docker run -d --name seerr \
  -e TZ=Asia/Shanghai \
  -e PORT=5055 \
  -p 5055:5055 \
  -v ~/seerr-test/config:/app/config \
  --restart unless-stopped \
  ghcr.io/seerr-team/seerr:latest
```

启动后浏览器打开 **http://localhost:5055**。

---

## 3. Seerr 初始化向导（含一个本机测试用媒体服务器）

Seerr 首次启动要求先绑定一个媒体服务器（Jellyfin / Plex / Emby）——这是它的设计，用来判断"哪些片库里已经有"。

**如果你本机没有**，跑一个测试专用 Jellyfin（同样一条命令，空的库正好适合测点播）：

```bash
mkdir -p ~/jellyfin-test/config ~/jellyfin-test/media

docker run -d --name test-jellyfin \
  -e TZ=Asia/Shanghai \
  -p 8096:8096 \
  -v ~/jellyfin-test/config:/config \
  -v ~/jellyfin-test/media:/media \
  --restart unless-stopped \
  jellyfin/jellyfin:latest
```

打开 **http://localhost:8096** 完成 Jellyfin 向导：随便建一个管理员账号（用户名/密码，仅测试用），媒体库步骤可以跳过或指向 `/media`（空目录即可）。

然后回到 Seerr 向导（http://localhost:5055）：

1. 选择 **Jellyfin**
2. Hostname 填 `test-jellyfin`，Port 填 `8096`（两个容器用 Docker 互认容器名）
3. 邮箱随便填，用户名/密码填刚才建的 Jellyfin 管理员
4. 登录后选择要同步的媒体库（空库就直接下一步）
5. 用户导入步骤直接跳过

到这里 Seerr 初始化完成，进入主界面。

---

## 4. 添加 Radarr 服务器（管电影点播）

Seerr 左侧 **Settings（设置）→ Services（服务）→ Radarr 标签 → Add Radarr Server**，按下表填：

| 字段 | 填什么 | 说明 |
| --- | --- | --- |
| Default Server | ✅ 勾选 | 电影点播默认发给它 |
| Server Name | `115-media-hub` | 随便起的显示名 |
| Hostname or IP Address | `host.docker.internal` | **不能填 localhost**——容器里的 localhost 指的是它自己。Docker Desktop（Mac/Windows）认这个特殊域名 |
| Port | `18080` | 面板端口 |
| Use SSL | 不勾 | 面板是 http |
| API Key | 第 1 步生成的 32 位密钥 | 复制粘贴，别多空格 |
| URL Base | 留空 | 面板没有反向代理前缀 |

先点 **Test**：

- **显示连接成功** → 下面的下拉框才会出现选项，继续填：
  - Quality Profile：**默认**
  - Root Folder：**`/`**（面板固定只回这一个选项，见下方说明）
  - Minimum Availability：**Released**
  - Enable Scan：建议勾选（Seerr 能识别重复点播）
- **连接失败** → 跳到本文第 7 节排错

> **Root Folder 为什么只有一个 `/`**：Seerr 这个下拉框是从我们的 `/api/v3/rootfolder` 取的。我们固定返回 `/`，是因为保存目录已经在面板的「电影点播保存目录 / 电视剧点播保存目录」里配好了，后端收单时按电影/电视剧自己决定落点，不读 Seerr 传来的这个值。这样 Seerr 里不会再出现「选错目录」的问题，选 `/` 即可。

最后点 **Save**。

---

## 5. 添加 Sonarr 服务器（管剧集点播）

同样在 **Settings → Services**，切到 **Sonarr 标签 → Add Sonarr Server**：

字段与第 4 节大体相同（勾 Default Server、Hostname 填 `host.docker.internal`、Port `18080`、同一把 API Key），Test 通过后多三个字段：

| 字段 | 填什么 |
| --- | --- |
| Language Profile | **默认** |
| Series Type | **Standard** |
| Season Folder | ✅ 勾选（剧集按「Season NN」分目录） |
| Root Folder | **`/`**（同上，面板固定返回这一个） |

Save。

> 到这一步，Seerr 已经把你的面板当成"电影 + 剧集"两台自动化服务器了。

---

## 6. 开始测试

### 测试一：电影点播

1. Seerr 首页搜索一部电影（比如《黑客帝国》）→ **Request**
2. 如果弹服务器选择，选刚才加的 `115-media-hub`
3. 提交后**立刻打开面板的「影视订阅」页**：应出现名为 `黑客帝国 (1999)` 的新任务，并自动开始搜索资源
4. 面板任务卡片会显示搜索进度；找到资源后的转存、入库、STRM 与手动订阅完全同链路

### 测试二：剧集点播

1. Seerr 搜索一部剧（比如《绝命毒师》）→ **Request** → 选择要订的季
2. 面板「影视订阅」页出现对应任务：
   - 只订 1 季：任务名 `绝命毒师 (2008)`
   - 多季一起订：自动拆成 `绝命毒师 (2008) S01`、`S02`…… 每季一个任务
3. 同样立即开始搜索

### 测试三：删除点播（连带删任务）

1. Seerr 右上角头像 → **Manage Requests（请求管理）**（或 Request Queue）
2. 找到刚才的请求 → 删除 / 标记为未请求
3. 面板「影视订阅」页里对应的订阅任务**同时消失**，不再追更

### 测试四：接口是否关闭（可选）

1. 回面板把「点播接口 API Key」清空 → 保存
2. Seerr 的 Test 会立刻失败，点播也会被拒绝（接口整体关闭）
3. 测完把密钥填回去即可

---

## 7. 排错清单

| 现象 | 原因 | 解法 |
| --- | --- | --- |
| Seerr Test 连接失败 | Hostname 填了 localhost | 改成 `host.docker.internal`；不行就换成你电脑的局域网 IP（终端 `ifconfig` 看 en0 的 inet） |
| Seerr Test 连接失败 | 面板没在跑 / 端口不对 | 浏览器先直接打开 `http://localhost:18080` 确认面板能开 |
| 点播返回「点播接口未启用」503 | API Key 没保存 | 面板设置页填密钥 → 务必点「保存全部配置」 |
| 点播返回「API Key 无效」401 | 两边密钥不一致 | 重新生成或复制，两边填同一串 |
| 点播返回「未配置电影点播保存目录」或「未配置电视剧点播保存目录」 | 对应保存目录为空 | 面板设置页分别填电影、电视剧两个保存目录（如 `媒体库/网盘电影`、`媒体库/网盘电视剧`）并保存 |
| 点播返回「TMDB 增强未启用」 | 面板没配 TMDB | 参数配置里开启 TMDB 增强并填 API Key |
| Test 通过但下拉框是空的 | Quality/Root Folder 拉不到 | 确认 Test 真的通过了；刷新页面重新 Save 一次 |
| 点播成功但订阅页看不到任务 | 页面没刷新 / 没设默认服务器 | 刷新「影视订阅」页；回 Seerr 确认该服务器勾了 Default Server |
| 剧集点播报「未找到 TVDB 对应的 TMDB 条目」 | 该剧在 TMDB 查不到对应关系 | 换一部热门剧测试；个别冷门条目确实会缺映射 |
| 点播报「读取 TMDB 信息失败」 | TMDB 超时或被墙 | 检查参数配置里的 TMDB 代理/Key；这是**有意报错**，不报错会建出一条永远搜不到的任务 |

### 两个已知边界

- **Seerr 里点「重新搜索」会真的跑一轮**（`POST /command` 已接通），但**剧集详情页的「剧集清单」是空的**：我们按「季」管订阅、不维护逐集清单，Seerr 只显示「尚未获取剧集」，不影响下发点播。
- **点播建的订阅默认开「跨盘补源」**：115 本盘搜不到时才会去夸克找，补到就转存下载再上传。不需要的话在「影视订阅」页把该任务的补源开关关掉即可。

---

## 8. 测试完后（清理）

```bash
docker stop seerr test-jellyfin        # 停掉两个测试容器
docker rm seerr test-jellyfin          # 删除容器（配置数据在 ~/seerr-test、~/jellyfin-test，不需要可整个删掉）
```

数据目录说明：Seerr 的配置和请求记录在 `~/seerr-test/config`，删容器不删数据，重装可复用。

---

## 附：以后给家人用（可选）

- Seerr 的地址固定后（如 `http://192.168.x.x:5055`），家人手机浏览器直接打开就能点播
- 在 Settings → Users 里给家人开账号、设权限（是否免审批、每周点播上限）
- 面板侧无需任何额外操作——点播进来就是普通订阅任务
