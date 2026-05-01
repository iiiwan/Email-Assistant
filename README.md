# 邮件爬取与发送工具

适用于 NUDT 邮箱（mail.nudt.edu.cn，Coremail XT 系统）的邮件爬取和发送程序。

## 功能特点

- **邮件爬取**：通过 Coremail JSON API 获取收件箱、已发送等文件夹的邮件列表和正文
- **SMTP 发信**：通过 SMTP 直接发送邮件，无需打开浏览器
- **附件支持**：发送邮件时可添加多个附件
- **关键词搜索**：按主题/发件人关键词搜索邮件
- **日期筛选**：按指定日期过滤邮件，支持多种日期格式
- **中文总结**：自动生成邮件摘要，按发件人分组输出
- **会话缓存**：登录后缓存 SID，复用会话避免频繁登录
- **交互式输入**：支持命令行和交互式两种方式输入认证信息

## 安装依赖

```bash
# 激活虚拟环境
source cc_test/Scripts/activate

# 安装依赖
pip install requests beautifulsoup4 lxml
```

## 使用方法

### 发送邮件（SMTP）

```bash
# 基本发送
python email_crawler.py --send \
    --username your_email@nudt.edu.cn --password your_password \
    --to recipient@example.com \
    --subject "邮件主题" \
    --body "邮件正文" \
    --text

# 带抄送和附件
python email_crawler.py --send \
    --username your_email@nudt.edu.cn --password your_password \
    --to recipient@qq.com \
    --subject "日报" \
    --body "请查收附件" \
    --cc boss@example.com \
    --attachments report.pdf photo.png

# 使用自定义 SMTP 服务器
python email_crawler.py --send \
    --username your_email@nudt.edu.cn --password your_password \
    --smtp-host mail.nudt.edu.cn --smtp-port 25 \
    --to recipient@qq.com --subject "test" --body "hello" --text
```

### 爬取邮件

```bash
# 交互式登录，获取今日邮件
python email_crawler.py --today --interactive

# 获取指定日期邮件
python email_crawler.py --username your_email@nudt.edu.cn --password your_password --date 2026-4-1

# 只获取元数据，不获取正文（更快）
python email_crawler.py --interactive --no-content

# 按关键词搜索
python email_crawler.py --interactive --keyword "会议纪要"

# 获取已发送邮件
python email_crawler.py --interactive --mailbox sent
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
| `--today`, `-t` | 只获取今日邮件 | — |
| `--keyword`, `-k` | 按关键词搜索（不限日期，最多20页） | — |
| `--max-content` | 最大获取邮件内容数量 | 10 |
| `--no-content` | 不获取邮件正文，只获取元数据 | — |
| `--interactive`, `-i` | 交互式输入用户名和密码 | — |
| `--output`, `-o` | 输出目录 | mails |
| `--verbose`, `-v` | 显示详细日志 | — |

## 程序结构

```
CC_test/
├── email_crawler.py        # 主程序
├── send_mail_smtp.py       # 独立 SMTP 发送脚本（最小示例）
├── requirements.txt        # 依赖包列表
└── README.md               # 说明文档
```

### 主要类和方法

- `MailCrawler`: 主类
  - `login()` — 登录邮箱，获取会话 SID
  - `load_session()` / `save_session()` — 会话缓存，避免重复登录
  - `get_mail_list()` — 通过 Coremail JSON API 获取邮件列表
  - `get_mail_content()` — 获取邮件正文和附件
  - `send_mail()` — 通过 SMTP 发送邮件（支持附件、抄送、密送）
  - `logout()` — 退出登录
  - `is_date_mail()` / `is_today_mail()` — 日期筛选（静态方法）
  - `generate_summary()` — 中文邮件摘要生成（静态方法）

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
2. **会话缓存**：登录后 SID 缓存 8 小时，期间无需重复登录
3. **频率控制**：请求间自动添加随机延迟，避免被封
4. **SMTP 发信**：不需要网页登录，直接通过 SMTP 协议发送
5. **SSL 证书**：默认禁用 SSL 证书验证，因服务器使用自签名证书

## 许可证

仅供学习和研究使用，请遵守相关法律法规和网站使用条款。
