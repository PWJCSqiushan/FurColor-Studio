# FurColor Studio

面向兽装活动摄影的、本地优先批量后期工作站。它把图片源选择、选片、隐私复核、参考样片驱动的白平衡与色彩映射、主体曝光保护、逐图眼睛蒙版、水印和可审计交付串成一条流程。

## 安全边界

- **本地工作站**处理真实照片，只监听 `127.0.0.1`；照片、路径、标注、记忆模型、水印和数据库不进入 Git。
- **服务器演示版**只展示 UI，不提供上传、路径读取、模型处理或交付 API。
- 系统是摄影师辅助工具。商业交付必须完成人脸、蒙版、曝光和水印四项人工质检。

## Windows 快速开始

需要 Python 3.11 或 3.12。在 PowerShell 进入项目目录：

```powershell
& '.\install_local.ps1'
```

编辑本地 `.env`，把 `FURCOLOR_ALLOWED_ROOTS` 改成允许软件访问的照片根目录；多个根目录使用英文分号分隔。`.env` 已被 Git 忽略。

准备兼容的 YuNet ONNX 人脸模型，并在确认模型许可证后执行：

```powershell
& '.\install_local.ps1' -FaceModelPath '你本机的模型文件.onnx'
& '.\run_local.ps1'
```

浏览器将打开 `http://127.0.0.1:8899`。完整流程：

`新建项目 → 选择原片/参考/水印 → 正选或反选 → 隐私分析 → 人脸复核与自动记忆 → 逐图眼睛蒙版 → V3.3 渲染 → 四项质检 → 交付`

详细说明见 [操作手册](docs/USER_GUIDE.md)、[人脸记忆模型说明](docs/MODEL_CARD.md) 与 [隐私政策](PRIVACY.md)。

## 云端安全演示

```bash
docker compose -f docker-compose.demo.yml up -d --build
```

容器只绑定宿主机 `127.0.0.1:8899`。公网发布必须先审计服务器，再通过已有反向代理添加独立域名或路径；脚本不会修改 Nginx、宝塔、腾讯云防火墙或已有项目。服务器步骤见 [隔离部署手册](deploy/README_TENCENT.md)。

## 发布前检查

```powershell
& '.\.venv\Scripts\python.exe' '.\scripts\security_audit.py'
& '.\.venv\Scripts\python.exe' -m pytest -q
git status --short
```

脱敏审计必须返回 `PASS`。禁止用 `git add -f` 强制加入照片、模型、`.env`、数据库或记忆文件。

## 许可证与资产边界

FurColor Studio 源代码采用 [Apache License 2.0](LICENSE)。可以使用、修改、分发和商业化代码，但必须遵守许可证中的版权、许可证副本、修改声明和专利条款。

许可证不覆盖用户照片、活动素材、水印、私有标注、人脸记忆、训练数据及未随仓库分发的模型权重；这些资产可能有独立权利和使用条件。FurColor 名称、图标和未来示例图的商标、肖像权及著作权仍需分别管理。

## 技术栈

FastAPI、SQLite、Pillow、OpenCV、rawpy，以及 FurColor V3.3 本地图像引擎。
