# 参与贡献与问题反馈指南（Contributing to MailHub）

感谢你使用并关注 **MailHub**！无论是提交 Bug、咨询配置问题，还是贡献代码与文档改进，都欢迎按照本指南协作，以便维护者快速复现并给出精准修复。

---

## 一、提交 Issue 前的准备

在 [A-510/MailHub/issues](https://github.com/A-510/MailHub/issues) 新建 Issue 前，请先完成以下确认：

1. **查阅已有文档**：
   - 先浏览 [README 常见问题](https://github.com/A-510/MailHub#常见问题) 与 [邮箱渠道与 OAuth2 配置指南](https://github.com/A-510/MailHub/blob/main/docs/guide/email-providers-and-oauth2.md)。
2. **检索历史 Issues**：
   - 在 [Issues 页面](https://github.com/A-510/MailHub/issues) 搜索关键词，确认是否已有相同或已修复的问题。
3. **保护个人隐私与敏感凭据（非常重要）**：
   - 切勿在截图、日志或正文中公开：邮箱客户端授权码、应用专用密码、OAuth2 `Client Secret` / `Token`、`data/.secret.key`、完整的个人私有邮箱地址或邮件正文隐私。
4. **附带脱敏诊断信息（推荐）**：
   - 若应用可正常打开，请进入右上角 **设置中心 → 关于与诊断**：
     - 点击 **「复制 Event ID」** 与 **「复制脱敏诊断报告 (Markdown)」** 粘贴到 Issue 的「诊断信息」区域；
     - 也可点击 **「导出脱敏诊断包 (.zip)」** 作为附件上传。
   - **安全提示**：内置诊断功能会尽力遮罩邮箱前缀、用户目录路径、主机名与敏感参数，且**绝不会打包 `mailhub.db`、`.secret.key` 或邮件正文**；但仍请你在公开分享前展开预览或解压复查一遍。

### Issue 模板分类

点击 [New Issue](https://github.com/A-510/MailHub/issues/new/choose) 后请选择最匹配的模板：

- **Bug 反馈（`[BUG]`）**：启动器异常、前端交互/主题报错、IMAP 同步异常、SMTP 发信失败、FTS5 搜索或加密存储问题。
- **新功能支持（`[功能]`）**：新邮箱协议适配、交互增强、快捷键或新设置项建议。
- **使用问题咨询（`[问题]`）**：授权码获取、Gmail/Outlook OAuth2 配置、自定义邮局参数、自定义立绘或 Live2D 扩展咨询。

---

## 二、本地开发与代码提交规范

### 1. 架构与安全红线

- **后端（Python >= 3.10 + FastAPI）**：
  - 严格遵循 `api → service → repository → schema / model` 分层，禁止在 `api/` 层直接操作数据库。
  - 所有凭据必须经过 `crypto_service`（Fernet）加密落盘，`AccountOut` 等对外响应模型绝不能暴露密文与密钥。
  - 统一使用标准库 `logging`（禁止使用 `print` 作为运行日志，禁止输出敏感凭据）。
- **前端（Vue 3 + TypeScript + Pinia）**：
  - 邮件 HTML 正文渲染必须经过 `useMailSanitizer`（`DOMPurify`）净化，外部链接保持 `rel="noopener noreferrer"`。
  - 无图资源必须保证优雅降级，不得引入未授权的商业插画、立绘或模型文件进仓库。
- **数据隔离**：
  - 运行期生成的 `data/`、`.env`、`*.db`、`*.key`、`*.log` 与个人图片素材已在 `.gitignore` 中排除，提交前请用 `git status` 核查。

### 2. 提交 PR 前必跑验证

```bash
# 1. 后端全量测试
cd backend
.\.venv\Scripts\python.exe -m pytest tests/test_mailhub.py -v

# 2. 启动器单元测试
cd ..
.\backend\.venv\Scripts\python.exe -m pytest launcher_app/tests/test_launcher_core.py -v

# 3. 前端 TypeScript 类型检查与构建校验
cd frontend
npm run build
```

欢迎在 Pull Request 描述中附上改动目的、关联的 Issue 编号（如 `Closes #12`）以及本地测试通过情况。
