# 邮箱渠道与 OAuth2 配置指南

本文档面向 **MailHub** 用户，汇总各主流邮箱渠道的协议预设、授权码 / 应用专用密码获取方式、Gmail / Outlook 的 OAuth2 PKCE 配置流程以及常见报错排查方法。

> 回到 [项目主页](https://github.com/A-510/MailHub) · 查看 [README 常见问题](https://github.com/A-510/MailHub#常见问题) · 前往 [Issues](https://github.com/A-510/MailHub/issues)

---

## 一、支持渠道与协议预设一览

在 MailHub 右侧栏点击 **`+`**（或打开 **设置中心 → 邮箱渠道**），输入邮箱地址后失焦，系统会自动识别域名并填充对应服务器参数（含 `yeah.net` 独立主机 `imap.yeah.net` / `smtp.yeah.net`）：

| 邮箱渠道 | 自动匹配后缀 | IMAP 服务器 | SMTP 服务器 | 推荐认证方式 | 协议兼容特性 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **QQ / Foxmail** | `qq.com`, `foxmail.com` | `imap.qq.com:993` (SSL) | `smtp.qq.com:465` (SSL) | 16 位客户端授权码 | 自动识别授权码并校验连接 |
| **网易 163 / yeah.net** | `163.com`, `yeah.net` | `imap.163.com:993` (`imap.yeah.net`) | `smtp.163.com:465` (`smtp.yeah.net`) | 客户端授权密码 | 自动发送 **RFC 2971 IMAP ID**；SMTP 支持 465 → 994 / 587 回退 |
| **网易 126** | `126.com` | `imap.126.com:993` (SSL) | `smtp.126.com:465` (SSL) | 客户端授权密码 | 自动发送 **RFC 2971 IMAP ID**；SMTP 支持 465 → 994 / 587 回退 |
| **Gmail** | `gmail.com`, `googlemail.com` | `imap.gmail.com:993` (SSL) | `smtp.gmail.com:587` (STARTTLS) | **OAuth2 PKCE** 或 16 位应用专用密码 | 自动剔除 16 位应用专用密码中的空格 |
| **Outlook / M365** | `outlook.com`, `hotmail.com`, `live.com`, `msn.com` | `outlook.office365.com:993` (SSL) | `smtp.office365.com:587` (STARTTLS) | **浏览器 OAuth2 PKCE** | 微软已停用基础密码登录，必须使用 OAuth2 |
| **iCloud 邮箱** | `icloud.com`, `me.com`, `mac.com` | `imap.mail.me.com:993` (SSL) | `smtp.mail.me.com:587` (STARTTLS) | Apple ID App 专用密码 | — |
| **学校 / 教育邮箱** | `.edu.cn`, `.edu` | 手动填写（默认 `993` SSL） | 手动填写（默认 `465` SSL） | 校园邮局密码 / 客户端密码 | 需填写学校邮件中心提供的服务器地址 |
| **企业 / 自定义邮局** | 任意自建或企业域名 | 手动填写（默认 `993` SSL） | 手动填写（默认 `465` SSL） | 密码 / 授权码 | 展开「自定义 IMAP / SMTP 服务器参数」填写 |

---

## 二、客户端授权码 / 应用专用密码获取方式

国内与国际主流邮箱通常**不允许直接使用网页登录密码**通过 IMAP/SMTP 收发邮件，请按对应服务商要求生成专用凭据：

1. **QQ 邮箱 / Foxmail**
   - 登录 [QQ 邮箱网页版](https://mail.qq.com/) → **设置 → 账户**；
   - 在 **POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV 服务** 中开启 **IMAP/SMTP 服务**，按提示短信验证后生成 **16 位授权码**；
   - 在 MailHub 填写该 16 位授权码（非 QQ 登录密码）。
2. **网易 163 / 126 / yeah.net 邮箱**
   - 登录网页版邮箱 → **设置 → POP3/SMTP/IMAP**；
   - 开启 **IMAP/SMTP 服务** 并新增**客户端授权密码**；
   - MailHub 在连接网易邮箱时会自动向服务器发送符合 **RFC 2971** 的客户端识别信息（IMAP ID），避免触发 `Unsafe Login` 拦截。
3. **Gmail（应用专用密码模式）**
   - 需先为 Google 账号开启**两步验证（2-Step Verification）**；
   - 前往 [Google 应用专用密码页面](https://myaccount.google.com/apppasswords) 创建名为 `MailHub` 的应用专用密码；
   - 填入生成的 16 位密码（直接带空格粘贴即可，后端会自动清理中间空格）。
4. **iCloud 邮箱**
   - 前往 [Apple ID 账户管理](https://appleid.apple.com/account/manage) → **登录与安全 → App 专用密码** 生成后填入。

---

## 三、Gmail & Outlook 浏览器 OAuth2 PKCE 配置步骤

MailHub 采用 **OAuth2 Authorization Code + PKCE (S256)** 与本地回环回调机制，源码中**不硬编码**任何开发者密钥，所有令牌由你自己的 Client ID 签发并经过 **Fernet** 加密保存在本机 `data/mailhub.db`。

### 回调地址（Redirect URI）

无论配置 Google 还是 Microsoft 应用，均请将回调地址严格设置为：

```text
http://127.0.0.1:8765/api/v1/oauth/callback
```

> 若通过环境变量修改了 `MAILHUB_HOST` 或 `MAILHUB_PORT`，OAuth 应用中的回调地址需保持与实际监听地址一致。

### 1. 配置 Google (Gmail) OAuth2

1. 打开 [Google Cloud Console](https://console.cloud.google.com/)，新建或选择一个项目；
2. 启用 **Gmail API**，并在 **OAuth 同意屏幕（OAuth consent screen）** 中将你的 Gmail 地址加入**测试用户（Test users）**（未发布测试阶段必须添加，否则登录会报 403）；
3. 进入 **凭据 → 创建凭据 → OAuth 客户端 ID**：
   - 应用类型可选择 **桌面应用（Desktop app）** 或 **Web 应用（Web application）**（若为 Web 应用或提示需要密钥，请同时记录 `Client Secret`）；
   - 将 `http://127.0.0.1:8765/api/v1/oauth/callback` 添加到已授权的重定向 URI；
4. 回到 MailHub：**设置中心 → 邮箱渠道 → 跳转浏览器登录 → 展开「OAuth2 Client ID 开发者配置」**，填入 `Google Client ID`（按需填写 `Google Client Secret`）并保存；
5. 点击**「打开浏览器登录 Google (Gmail)」**完成授权即可。

### 2. 配置 Microsoft (Outlook / Hotmail / Live) OAuth2

1. 登录 [Microsoft Entra 管理中心](https://entra.microsoft.com/) → **应用注册（App registrations） → 新注册**；
2. **受支持的账户类型**建议选择：**任何组织目录中的账户和个人 Microsoft 账户**；
3. **重定向 URI（Redirect URI）** 平台选择 **Web** 或 **公共客户端/本机（Public client/native）**，填入 `http://127.0.0.1:8765/api/v1/oauth/callback`；
4. 在 **API 权限** 中确认允许 `openid`、`email`、`profile`、`offline_access` 以及 Outlook IMAP/SMTP 权限（`IMAP.AccessAsUser.All`、`SMTP.Send`）；
5. 复制应用概览页的 **应用程序(客户端) ID（Application (client) ID）**，填入 MailHub 设置中心的 `Microsoft Entra Client ID` 并保存；
6. 点击**「打开浏览器登录 Microsoft (Outlook)」**完成授权。

---

## 四、常见连接错误对照与排查

| 提示现象 | 常见原因 | 建议处理方式 |
| :--- | :--- | :--- |
| `Gmail 拒绝了普通账户密码登录 (185833)` | 填写了 Google 账户常规密码 | 开启两步验证并生成 16 位应用专用密码，或改用 OAuth2 浏览器登录 |
| `微软 Outlook 已停用基础密码登录` | Outlook 在密码表单提交 | 微软已禁用基础密码认证，请切换为「跳转浏览器登录」使用 OAuth2 |
| `网易邮箱安全拦截 / Unsafe Login` | 未在网页端开启 IMAP 或未使用客户端授权码 | 前往网页端开启 IMAP 服务并重新生成授权密码 |
| `TLS/SSL 握手被中断 (465 端口)` | 本地代理软件或网络策略拦截 SMTPS 465 | MailHub 会自动回退尝试 `587 (STARTTLS)`（网易补充 `994`），也可展开服务器参数手动切换端口 |
| `连接邮件服务器超时` | 代理拦截、防火墙阻断或主机/端口填写错误 | 核对 IMAP/SMTP 主机与端口；使用企业/校园内网邮箱时确认网络可达 |
| 已有邮箱报错后如何更新授权码 | 授权码过期或修改过密码 | 在 **设置中心 → 邮箱渠道 → 已绑定列表** 点击对应邮箱的 **「改密码」/「更新授权码」**，验证通过会自动重新同步 |

---

## 五、导出脱敏诊断信息提交 Issue

如果按以上步骤仍无法解决，可在 MailHub 客户端内直接生成不含敏感内容的排查信息：

1. 点击右上角齿轮进入 **设置中心 → 关于与诊断**；
2. 点击 **「复制脱敏诊断报告 (Markdown)」** 或 **「导出脱敏诊断包 (.zip)」**；
3. 展开预览框确认其中已自动遮罩邮箱前缀、本地用户路径、主机名与凭据（绝不包含邮件正文、数据库与密钥文件）；
4. 前往 [MailHub Issues](https://github.com/A-510/MailHub/issues/new/choose) 选择 **Bug 反馈** 或 **使用问题咨询** 模板提交。
