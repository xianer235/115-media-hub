# 光鸭云盘链接识别设计

**日期**: 2026-08-01
**范围**: 仅识别光鸭云盘分享链接；不注册为可操作的网盘 Provider。

## 目标

将 `guangyapan.com` 的分享链接统一归类为 `guangya`，使资源导入、频道解析和订阅候选筛选能保留该来源类型，为后续 Provider 接入建立稳定的链接类型。

## 方案

在 `app/resource_linking.py` 的 `RESOURCE_LINK_TYPE_PATTERNS` 中新增 `guangya` 规则。规则匹配 `https://www.guangyapan.com` 或 `https://guangyapan.com` 的分享路径：`/share/<id>`、`/s/<id>`、`/link/<id>`、`/download/<id>`。普通主页、目录页和未知路径不归类为分享链接。

沿用已有 `extract_resource_links()` 的 HTTP URL 提取和 `detect_resource_link_type()` 的类型判定，不新增平行的解析入口，也不改变既有链接的优先级。

## 边界

- 不新增 `GuangyaProvider`、设置卡、认证字段或分享转存按钮。
- 不执行手机号、短信验证码或人机验证登录。
- 不将光鸭离线下载或直链能力声明为可用。
- 后续完整接入应使用 `refresh_token` 认证，并在真实账号下验证目录、分享令牌、分享分页和转存响应。

## 测试

新增链接分类回归测试，覆盖四种分享路径和带查询参数的链接；同时覆盖非分享主页，确保其仍仅是普通 `link`。
