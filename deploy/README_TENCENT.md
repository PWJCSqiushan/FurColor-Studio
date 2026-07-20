# 腾讯云轻量应用服务器：隔离部署手册

## 安全结论

- 已知宿主机的 `8888` 端口存在响应，因此它是**禁止占用、禁止重启、禁止修改**的已有服务边界。
- FurColor demo 使用独立目录 `/opt/furcolor-demo`、独立 Compose 项目 `furcolor-demo`、独立容器 `furcolor-demo-web`。
- 容器只绑定 `127.0.0.1:8899`；脚本不会修改腾讯云防火墙、系统防火墙、Nginx、宝塔或现有项目。
- 服务器只部署 demo。真实照片、本地路径、水印、人脸反馈、训练数据和 SSH 凭据都不能复制到服务器。

## 第一阶段：只读审计

先在腾讯云控制台创建实例快照。然后通过 SSH 把 `deploy/audit_server.sh` 单独复制到临时目录并执行：

```bash
sh audit_server.sh | tee furcolor-audit.txt
```

检查 `furcolor-audit.txt`：端口、Docker、反向代理、磁盘和 `/opt/furcolor-demo` 状态。审计脚本不会改动服务器。若 8899 已被占用，应选择另一个新端口并同步修改 Compose；不得迁移或停止占用者。

## 第二阶段：上传脱敏代码

必须先在本地运行 `scripts/security_audit.py` 并得到 `PASS`。推荐从干净 GitHub 仓库拉取发布标签，或只上传 `git archive` 生成的源码包。不要上传工作目录、`.env`、`runtime`、照片、模型、人脸记忆或私钥。

将源码放到 `/opt/furcolor-demo` 后，先检查：

```bash
cd /opt/furcolor-demo
docker compose -f docker-compose.demo.yml config
```

## 第三阶段：明确确认后部署

```bash
cd /opt/furcolor-demo
CONFIRM_ISOLATED_DEPLOY=yes sh deploy/deploy_demo.sh
curl -fsS http://127.0.0.1:8899/api/health
```

此时只能从服务器本机访问。公网发布应在另一次变更中完成：先备份现有反向代理配置，再添加独立域名或路径并验证；不要覆盖默认站点，也不要复用 8888。

## 回滚

只停止 FurColor Compose 项目：

```bash
cd /opt/furcolor-demo
docker compose -p furcolor-demo -f docker-compose.demo.yml down
```

不要执行 `docker system prune`，不要停止不属于 `furcolor-demo` 的容器。
