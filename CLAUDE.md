# CC_test 项目指南

## 行为规则（最高优先级）

1. **实现功能前必须先读代码**：在修改任何文件之前，先用 `Read` 工具阅读本文件和相关源代码文件，理解现有逻辑后再动手。
2. **虚拟环境必须激活**：见下方。

## 虚拟环境

运行任何 Python 命令前，必须先 `source activate`：

```bash
source f:/Worker_development/CC_test/cc_test/Scripts/activate && cd f:/Worker_development/CC_test && python <脚本名> <参数>
```

禁止使用 `f:/Worker_development/CC_test/cc_test/Scripts/python.exe` 直接路径。

## 项目概述

邮件爬取与发送工具，适用于 NUDT 邮箱（mail.nudt.edu.cn，Coremail XT 系统）。

## 主要文件

- `email_crawler.py` — 主程序：SMTP 发信 + Coremail JSON API 爬取邮件 + AI 分类总结
- `requirements.txt` — 依赖：requests, beautifulsoup4, lxml
- `config.example.json` — 配置文件示例（含 AI API 配置）

## 关键技术点

- **SMTP 发信**：mail.nudt.edu.cn:25，AUTH PLAIN，无需 SSL/TLS
- **爬取邮件**：通过 Coremail JSON API（`/coremail/s/json`），需先网页登录获取 SID
- **会话缓存**：SID 缓存到 `.session_cache.json`，有效期 8 小时
- **SSL 证书**：服务器使用自签名证书，需禁用 SSL 验证
- **发信模式无需登录**：`--send` 模式直接用 SMTP，跳过网页登录
- **AI 分类总结**：通过小米 MiMo API（Anthropic 兼容格式）对邮件智能分类和精炼总结
  - 端点：`POST {api_base}/v1/messages`，Header `x-api-key`，`anthropic-version: 2023-06-01`
  - 默认模型：`mimo-v2-pro`，默认 API Base：`https://token-plan-cn.xiaomimimo.com/anthropic`
  - 支持从 `config.json` 读取 `ai_api_key`、`ai_api_base`、`ai_model`
  - MiMo 模型会输出 `thinking` 类型内容块，需作为回退提取
