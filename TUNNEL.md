# 本地公网穿透方案（Cloudflare Tunnel）

由于 Hugging Face / Render 在国内网络下访问受限，本项目使用 **Cloudflare Tunnel** 把本地服务暴露到公网，获得一个面试官可以直接点击的 HTTPS 链接。

## 前置条件

1. 本地 FastAPI 服务已在 `http://localhost:8000` 运行（见 README 快速开始）。
2. `cf.exe`（cloudflared 2026.7.3 完整版，约 52MB）已就绪于：
   `D:\WorkBuddyProjects\2026-07-31-14-43-16\.workbuddy\cf.exe`
   （由助手自动下载；`.workbuddy` 目录不进 git，不影响仓库。）

## 启动穿透

在 Git Bash 中执行（**无需 Cloudflare 账号，quick tunnel 免登录**）：

```bash
D:/WorkBuddyProjects/2026-07-31-14-43-16/.workbuddy/cf.exe tunnel --url http://localhost:8000
```

启动后会直接输出公网地址（无需登录）：

```
Your quick Tunnel has been created! Visit it at (it may take some time to be reachable):
https://xxxx-xxx-xxx.trycloudflare.com
```

这个 `https://xxxx-xxx-xxx.trycloudflare.com` 就是你的公网演示链接。

## 验证可用性

打开链接后应看到聊天界面；访问 `/dashboard` 可查看意图分布看板；`/api/health` 可查看服务状态。

## 重要说明

- **临时域名**：每次重启 cloudflared，URL 都会变化。面试前请重新启动并更新简历/发送给面试官的链接。
- **电脑需保持开机**：链接走的是你本机服务，关机后无法访问。
- **无需付费/信用卡**：Cloudflare Tunnel 临时 URL 完全免费。
- **数据安全**：通信走 HTTPS，但面试结束后建议关闭 cloudflared 以停止公网暴露。

## 固定域名（进阶）

若想要固定链接，需要：
1. 注册 Cloudflare 账号并添加一个域名；
2. 创建 Named Tunnel 并绑定到该域名下的子域；
3. 具体步骤参考 [Cloudflare 官方文档](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)。

对简历项目而言，临时 `trycloudflare.com` 链接已足够。
