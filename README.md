# 智能邮箱助手

适用于 NUDT 邮箱（mail.nudt.edu.cn，Coremail XT 系统）的邮件爬取和发送程序。

## 功能特点

- **邮件爬取**：通过 Coremail JSON API 获取收件箱、已发送等文件夹的邮件列表
- **邮件正文**：通过 Playwright 浏览器自动化读取邮件完整正文内容
- **SMTP 发信**：通过 SMTP 直接发送邮件，无需打开浏览器
- **附件支持**：发送邮件时可添加多个附件
- **关键词搜索**：按主题/发件人关键词搜索邮件
- **日期筛选**：按指定日期过滤邮件，支持多种日期格式
- **中文总结**：自动生成邮件摘要，按发件人分组输出
- **AI 智能分类**：调用 AI（Anthropic 兼容 API）对邮件自动分类（工作/学术/广告推广/通知/账务/社交/其他）并生成精炼摘要
- **会话缓存**：登录后缓存 SID，复用会话避免频繁登录
- **每日日报**：一键拉取当日/日期范围邮件，AI 总结后自动推送到指定邮箱
- **交互式输入**：支持命令行和交互式两种方式输入认证信息

## 安装依赖

```bash
# 激活虚拟环境
source cc_test/Scripts/activate

# 安装依赖
pip install -r requirements.txt

# 安装 Playwright 浏览器（读取邮件正文需要）
playwright install chromium
```

## 使用方法

### 发送邮件（SMTP）

```bash
# 基本发送
python -m smail_assistant.cli --send \
    --username your_email@nudt.edu.cn --password your_password \
    --to recipient@example.com \
    --subject "邮件主题" \
    --body "邮件正文" \
    --text

# 带抄送和附件
python -m smail_assistant.cli --send \
    --username your_email@nudt.edu.cn --password your_password \
    --to recipient@qq.com \
    --subject "日报" \
    --body "请查收附件" \
    --cc boss@example.com \
    --attachments report.pdf photo.png

# 使用自定义 SMTP 服务器
python -m smail_assistant.cli --send \
    --username your_email@nudt.edu.cn --password your_password \
    --smtp-host mail.nudt.edu.cn --smtp-port 25 \
    --to recipient@qq.com --subject "test" --body "hello" --text
```

### 爬取邮件

```bash
# 交互式登录，获取今日邮件
python -m smail_assistant.cli --today --interactive

# 获取指定日期邮件
python -m smail_assistant.cli --username your_email@nudt.edu.cn --password your_password --date 2026-4-1

# 只获取元数据，不获取正文（更快）
python -m smail_assistant.cli --interactive --no-content

# 按关键词搜索
python -m smail_assistant.cli --interactive --keyword "会议纪要"

# 获取已发送邮件
python -m smail_assistant.cli --interactive --mailbox sent

# 使用 AI 智能分类和总结
python -m smail_assistant.cli --username your_email@nudt.edu.cn --password your_password \
    --today --ai --api-key YOUR_API_KEY

# 使用 AI + 指定模型和 API 地址
python -m smail_assistant.cli --username your_email@nudt.edu.cn --password your_password \
    --date 2026-4-30 --max-content 5 --ai \
    --api-key YOUR_API_KEY \
    --api-base https://token-plan-cn.xiaomimimo.com/anthropic \
    --ai-model mimo-v2-pro

# 按日期范围获取邮件（最近一周）
python -m smail_assistant.cli --username your_email@nudt.edu.cn --password your_password \
    --start-date 2026-4-25 --end-date 2026-5-1 --ai --api-key YOUR_API_KEY

# 只指定起始日期（到今天为止）
python -m smail_assistant.cli --interactive --start-date 2026-4-1 --ai --api-key YOUR_API_KEY
```

### 每日日报推送

```bash
# 推送今日邮件日报到 config.json 中配置的邮箱
python -m smail_assistant.cli --daily-digest

# 推送指定日期范围的邮件日报
python -m smail_assistant.cli --daily-digest --start-date 2026-5-1 --end-date 2026-5-3

# 指定推送目标邮箱
python -m smail_assistant.cli --daily-digest --digest-to your_qq@qq.com
```

## 命令行参数

| 参数 | 说明 | 默认值 |
|---|---|---|
| `--username`, `-u` | 邮箱用户名 | — |
| `--password`, `-p` | 邮箱密码 | — |
| `--send`, `-s` | 发送邮件模式（SMTP） | — |
| `--to` | 收件人（发送模式） | — |
| `--subject` | 邮件主题（发送模式） | — |
| `--body` | 邮件正文（发送模式） | — |
| `--cc` | 抄送（发送模式，可选） | — |
| `--bcc` | 密送（发送模式，可选） | — |
| `--attachments` | 附件路径，可多个（发送模式） | — |
| `--text` | 纯文本正文 | HTML |
| `--smtp-host` | SMTP 服务器地址 | mail.nudt.edu.cn |
| `--smtp-port` | SMTP 服务器端口 | 25 |
| `--mailbox`, `-m` | 邮箱类型（inbox/sent/draft/trash/spam） | inbox |
| `--pages` | 爬取页数 | 1 |
| `--date`, `-d` | 指定日期（YYYY-M-D） | 当天 |
| `--start-date` | 起始日期（配合 --end-date 使用） | — |
| `--end-date` | 结束日期（配合 --start-date 使用） | — |
| `--today`, `-t` | 只获取今日邮件 | — |
| `--keyword`, `-k` | 按关键词搜索（不限日期，最多20页） | — |
| `--max-content` | 最大获取邮件内容数量 | 10 |
| `--no-content` | 不获取邮件正文，只获取元数据 | — |
| `--interactive`, `-i` | 交互式输入用户名和密码 | — |
| `--output`, `-o` | 输出目录 | mails |
| `--verbose`, `-v` | 显示详细日志 | — |
| `--ai` | 启用 AI 分类和总结 | — |
| `--api-key` | AI API Key | — |
| `--api-base` | AI API Base URL | https://token-plan-cn.xiaomimimo.com/anthropic |
| `--ai-model` | AI 模型名称 | mimo-v2-pro |
| `--daily-digest` | 每日日报模式（AI 总结 + 推送到邮箱） | — |
| `--digest-to` | 日报发送目标邮箱 | 从 config.json 读取 |

## 程序结构

```
CC_test/
├── smail_assistant/                  # 主包
│   ├── __init__.py                 # 包入口，导出 MailCrawler、main
│   ├── crawler.py                  # MailCrawler 核心类（登录、邮件列表、会话管理）
│   ├── sender.py                   # SMTP 发信（SOCKS5 代理 + SSL 回退）
│   ├── fetcher.py                  # Playwright 浏览器获取邮件正文
│   ├── summarizer.py               # 邮件摘要生成 + AI 分类总结
│   ├── utils.py                    # 日期工具、邮件日期过滤、文件保存
│   └── cli.py                      # 命令行入口（参数解析 + main）
├── requirements.txt                # 依赖包列表
├── config.example.json             # 配置文件示例
├── config.json                     # 实际配置文件（不纳入版本控制）
├── README.md                       # 说明文档
└── CLAUDE.md                       # 项目开发指南
```

### 运行方式

```bash
python -m smail_assistant.cli <参数>
```

### 主要模块

- `crawler.py` — `MailCrawler` 核心类
  - `login()` — 登录邮箱，获取会话 SID
  - `load_session()` / `save_session()` — 会话缓存，避免重复登录
  - `get_mail_list()` — 通过 Coremail JSON API 获取邮件列表
  - `get_mail_content()` — 获取邮件元数据
  - `send_mail()` — 通过 SMTP 发送邮件（委托 sender 模块）
  - `logout()` — 退出登录
- `sender.py` — SMTP 发信
  - `send_mail()` — 发送邮件（支持附件、抄送、密送、代理回退）
- `fetcher.py` — Playwright 正文获取
  - `get_mail_content_playwright()` — 批量获取邮件完整正文
- `summarizer.py` — 摘要与 AI
  - `generate_summary()` — 关键词摘要
  - `ai_classify_and_summarize()` — AI 智能分类和精炼摘要
- `utils.py` — 工具函数
  - `parse_date_input()` — 多格式日期解析
  - `is_date_mail()` / `is_today_mail()` / `is_date_range_mail()` — 日期筛选
  - `save_mails()` — 保存邮件到 JSON 文件

## 输出格式

邮件数据以 JSON 保存到 `mails/` 目录：

```json
{
  "subject": "邮件标题",
  "from": "发件人",
  "to": "收件人",
  "time": "2026-04-27 10:30:00",
  "body": "邮件正文",
  "attachments": [
    {"name": "附件名称", "size": 1024}
  ]
}
```

## 注意事项

1. **网络环境**：需能访问 mail.nudt.edu.cn（校内网络或 VPN）
2. **Playwright**：读取邮件正文需要安装 Playwright 及 Chromium 浏览器
3. **会话缓存**：登录后 SID 缓存 8 小时，期间无需重复登录
4. **频率控制**：请求间自动添加随机延迟，避免被封
5. **SMTP 发信**：不需要网页登录，直接通过 SMTP 协议发送
6. **SSL 证书**：默认禁用 SSL 证书验证，因服务器使用自签名证书

## 许可证

仅供学习和研究使用，请遵守相关法律法规和网站使用条款。
