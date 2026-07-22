# Security

请不要在公开 Issue 中粘贴原片、绝对路径、服务器 IP、实例 ID、登录日志、密钥或客户信息。安全问题应通过仓库所有者公布的私密渠道报告。

本地完整版只应监听 `127.0.0.1`。不要将其直接映射到公网，也不要在服务器演示容器中注入本地项目目录。
Fursee 权重、`subject_embeddings.npz`、兽头裁剪、主体分析 JSON 和人脸记忆都属于本地敏感资产，不应附在 Issue、Release、Docker 镜像或公开部署中。云端 demo 不得配置 `FURCOLOR_FURSEE_MODEL_DIR`，也不得挂载项目运行目录。