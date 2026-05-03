"""命令行入口：参数解析 + main()"""

import argparse
import getpass
import json
import logging
import os
import time
from datetime import datetime, date, timedelta

from .crawler import MailCrawler
from .utils import parse_date_input, is_date_mail, is_date_range_mail
from .fetcher import get_mail_content_playwright
from .summarizer import generate_summary, ai_classify_and_summarize

logger = logging.getLogger(__name__)


def parse_args():
    """定义命令行参数"""
    parser = argparse.ArgumentParser(description='邮件内容爬取程序')
    parser.add_argument('--username', '-u', help='邮箱用户名')
    parser.add_argument('--password', '-p', help='邮箱密码')
    parser.add_argument('--mailbox', '-m', default='inbox', help='邮箱类型（inbox/sent/draft等）')
    parser.add_argument('--pages', type=int, default=1, help='爬取页数')
    parser.add_argument('--output', '-o', default='mails', help='输出目录')
    parser.add_argument('--config', '-c', help='配置文件路径（JSON格式）')
    parser.add_argument('--today', '-t', action='store_true', help='只获取今日邮件并直接输出到控制台')
    parser.add_argument('--date', '-d', help='指定日期（格式：YYYY-M-D，例如：2026-4-1），默认当天')
    parser.add_argument('--start-date', help='起始日期（配合 --end-date 使用，格式同 --date）')
    parser.add_argument('--end-date', help='结束日期（配合 --start-date 使用，格式同 --date）')
    parser.add_argument('--interactive', '-i', action='store_true', help='交互式输入用户名和密码')
    parser.add_argument('--max-content', type=int, default=10, help='最大获取邮件内容数量（默认为10）')
    parser.add_argument('--no-content', action='store_true', help='不获取邮件内容，只获取元数据')
    parser.add_argument('--keyword', '-k', help='按主题关键词搜索邮件（不限日期，最多搜索20页）')
    parser.add_argument('--verbose', '-v', action='store_true', help='显示详细日志（调试用）')
    parser.add_argument('--send', '-s', action='store_true', help='发送邮件模式')
    parser.add_argument('--to', help='收件人邮箱（发送模式）')
    parser.add_argument('--subject', help='邮件主题（发送模式）')
    parser.add_argument('--body', help='邮件正文（发送模式）')
    parser.add_argument('--cc', help='抄送（发送模式，可选）')
    parser.add_argument('--bcc', help='密送（发送模式，可选）')
    parser.add_argument('--html', action='store_true', default=True, help='正文使用HTML格式（默认）')
    parser.add_argument('--text', action='store_true', help='正文使用纯文本格式')
    parser.add_argument('--attachments', nargs='+', help='附件文件路径（发送模式，可多个）')
    parser.add_argument('--smtp-host', default='mail.nudt.edu.cn', help='SMTP 服务器地址')
    parser.add_argument('--smtp-port', type=int, default=25, help='SMTP 服务器端口')
    parser.add_argument('--ai', action='store_true', help='启用 AI 分类和总结（需要 API Key）')
    parser.add_argument('--api-key', help='AI API Key')
    parser.add_argument('--api-base', default='https://token-plan-cn.xiaomimimo.com/anthropic', help='AI API Base URL')
    parser.add_argument('--ai-model', default='mimo-v2-pro', help='AI 模型名称')
    parser.add_argument('--daily-digest', action='store_true', help='每日日报模式：拉取今日邮件、AI 总结、发送到指定邮箱')
    parser.add_argument('--digest-to', help='日报发送目标邮箱（默认从 config.json 读取）')
    return parser.parse_args()


def main():
    """主函数"""
    args = parse_args()

    # 根据--verbose参数调整日志级别
    if args.verbose:
        logging.getLogger().setLevel(logging.INFO)
        logger.setLevel(logging.INFO)

    # 自动加载 config.json（如果存在），--config 可指定其他路径
    config = {}
    config_path = args.config or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

    username = args.username or config.get('username')
    password = args.password or config.get('password')

    # AI 配置（命令行优先，其次从 config.json 读取）
    api_key = args.api_key or config.get('ai_api_key')
    api_base = args.api_base or config.get('ai_api_base', 'https://token-plan-cn.xiaomimimo.com/anthropic')
    ai_model = args.ai_model or config.get('ai_model', 'mimo-v2-flash')
    digest_to = args.digest_to or config.get('digest_to', '')

    # 提示用户输入认证信息
    if args.interactive or not username or not password:
        print("\n=== 邮箱登录信息 ===")
        if not username:
            username = input("请输入邮箱用户名: ").strip()
        if not password:
            password = getpass.getpass("请输入邮箱密码: ").strip()
        if not username or not password:
            logger.error("用户名和密码不能为空")
            return
        print()
    elif args.send:
        logger.info("使用命令行提供的凭据发送邮件")
    else:
        logger.info("使用命令行提供的凭据登录邮箱")

    # 日期选择（关键词搜索模式下跳过）
    selected_date = None
    date_start = None
    date_end = None
    if args.send:
        selected_date = date.today()
    elif args.daily_digest:
        if args.start_date or args.end_date:
            date_start = parse_date_input(args.start_date) if args.start_date else date.today()
            date_end = parse_date_input(args.end_date) if args.end_date else date.today()
            selected_date = date_start
        else:
            selected_date = date.today()
    elif args.keyword:
        selected_date = None
    elif args.start_date or args.end_date:
        date_start = parse_date_input(args.start_date) if args.start_date else date.today() - timedelta(days=30)
        date_end = parse_date_input(args.end_date) if args.end_date else date.today()
        logger.info(f"使用日期范围: {date_start} ~ {date_end}")
    elif args.date:
        selected_date = parse_date_input(args.date)
        logger.info(f"使用命令行指定日期: {selected_date}")
    elif args.today or args.send:
        selected_date = date.today()
        logger.info(f"使用今日日期: {selected_date}")
    else:
        print("\n=== 日期选择 ===")
        print("请输入日期（格式：2026-4-1），直接回车使用今天日期")
        print("或输入日期范围（格式：2026-4-1~2026-4-30）")
        date_input = input("日期: ").strip()
        if '~' in date_input:
            parts = date_input.split('~', 1)
            date_start = parse_date_input(parts[0].strip())
            date_end = parse_date_input(parts[1].strip())
            print(f"选择的日期范围: {date_start} ~ {date_end}")
        elif date_input:
            selected_date = parse_date_input(date_input)
            print(f"选择的日期: {selected_date}")
        else:
            selected_date = date.today()
            print(f"使用今日日期: {selected_date}")
        print()

    if not username or not password:
        logger.error("用户名和密码不能为空")
        return

    # 创建爬取器
    crawler = MailCrawler(smtp_host=args.smtp_host, smtp_port=args.smtp_port)

    # ===== 发送邮件模式（SMTP，无需网页登录）=====
    if args.send:
        if not args.to or not args.subject or not args.body:
            logger.error("发送邮件需要提供 --to, --subject, --body 参数")
            print("用法: python -m email_crawler.cli --send --username user@domain.com --password pwd "
                  "--to recipient@example.com --subject '主题' --body '正文'")
            return

        print(f"\n正在发送邮件...")
        print(f"  发件人: {username}")
        print(f"  收件人: {args.to}")
        print(f"  主题: {args.subject}")
        if args.cc:
            print(f"  抄送: {args.cc}")
        if args.bcc:
            print(f"  密送: {args.bcc}")
        if args.attachments:
            print(f"  附件: {', '.join(args.attachments)}")

        success = crawler.send_mail(
            to=args.to, subject=args.subject, body=args.body,
            cc=args.cc or '', bcc=args.bcc or '', is_html=not args.text,
            attachments=args.attachments or [],
            username=username, password=password,
        )
        if success:
            print(f"\n邮件发送成功！")
        else:
            print(f"\n邮件发送失败，请检查日志。")
        return

    # ===== 每日日报模式 =====
    if args.daily_digest:
        print("=== 邮件日报推送 ===\n")
        session_file = '.session_cache.json'
        session_loaded = crawler.load_session(username, session_file)
        if not session_loaded:
            print("正在登录邮箱...")
            if not crawler.login(username, password):
                logger.error("登录失败，程序退出")
                return
            crawler.save_session(username, session_file)
        else:
            print("复用缓存会话。\n")

        today = date.today()
        digest_start = date_start or today
        digest_end = date_end or today

        if digest_start == digest_end:
            print(f"正在拉取 {digest_start} 的邮件...")
        else:
            print(f"正在拉取 {digest_start} ~ {digest_end} 的邮件...")

        max_pages = 20 if digest_start != digest_end else 3
        all_mails = []
        for page in range(1, max_pages + 1):
            mails = crawler.get_mail_list(args.mailbox, page, target_date=digest_start if digest_start == digest_end else None)
            if not mails:
                break
            all_mails.extend(mails)
            if digest_start != digest_end:
                last_time = mails[-1].get('time', mails[-1].get('date', ''))
                try:
                    last_date = datetime.strptime(last_time[:10], '%Y-%m-%d').date()
                    if last_date < digest_start:
                        break
                except:
                    pass
            if page < max_pages:
                time.sleep(1)

        # 去重
        seen = set()
        deduped = []
        for m in all_mails:
            mid = m.get('id', '')
            if mid and mid not in seen:
                seen.add(mid)
                deduped.append(m)
        all_mails = deduped

        # 筛选日期范围邮件 + 过滤自己发的
        if digest_start == digest_end:
            date_mails = [m for m in all_mails if is_date_mail(m, digest_start)]
        else:
            date_mails = [m for m in all_mails if is_date_range_mail(m, digest_start, digest_end)]
        date_mails = [m for m in date_mails if m.get('sender', m.get('from', '')).lower() != username.lower()]
        all_mails = date_mails

        date_label = str(digest_start) if digest_start == digest_end else f"{digest_start} ~ {digest_end}"
        if not all_mails:
            print(f"\n{date_label} 没有收到邮件，跳过日报。")
            crawler.logout()
            return

        print(f"共 {len(all_mails)} 封邮件，正在生成 AI 总结...\n")

        max_content = min(10, len(all_mails))
        target_mails = all_mails[:max_content]
        pw_bodies = get_mail_content_playwright(username, password, target_mails)
        for mail in target_mails:
            body = pw_bodies.get(mail.get('id', ''), '')
            mail['body'] = body

        ai_result = ai_classify_and_summarize(all_mails, api_key, api_base, ai_model)

        if not ai_result:
            print("AI 服务不可用，将使用关键词摘要生成日报。\n")

        # 构建日报邮件
        digest_lines = []
        digest_lines.append(f"<h2>  {date_label} 邮件日报（{len(all_mails)} 封）</h2>")

        if ai_result and ai_result.get('summary'):
            digest_lines.append(f"<p><b>AI 总结：</b><br>{ai_result['summary']}</p>")
        else:
            fallback_summary = generate_summary(all_mails, digest_start if digest_start == digest_end else None)
            digest_lines.append(f"<p><b>摘要：</b><br>{fallback_summary}</p>")

        if ai_result and ai_result.get('categories'):
            digest_lines.append("<p><b>分类统计：</b></p><ul>")
            for cat, indices in ai_result['categories'].items():
                subjects = [all_mails[i].get('subject', '无标题') for i in indices if i < len(all_mails)]
                digest_lines.append(f"<li><b>{cat}</b>（{len(indices)} 封）：{'、'.join(subjects[:5])}</li>")
            digest_lines.append("</ul>")

        digest_lines.append("<hr><p><b>邮件详情：</b></p>")
        for i, mail in enumerate(all_mails, 1):
            sender = mail.get('sender', mail.get('from', '未知'))
            subject = mail.get('subject', '无标题')
            time_str = mail.get('time', mail.get('date', ''))
            body_preview = mail.get('body', '')
            if body_preview:
                body_preview = ' '.join(body_preview.split())[:200]
                if len(mail.get('body', '')) > 200:
                    body_preview += '...'
            digest_lines.append(
                f"<p><b>{i}. {subject}</b><br>"
                f"发件人：{sender} | 时间：{time_str}<br>"
                f"{body_preview}</p>"
            )

        digest_body = '\n'.join(digest_lines)

        print(f"正在发送日报到 {digest_to}...")
        success = crawler.send_mail(
            to=digest_to,
            subject=f"邮件日报 - {date_label}",
            body=digest_body,
            is_html=True,
            username=username, password=password,
        )
        if success:
            print(f"\n日报已发送到 {digest_to}！")
        else:
            print(f"\n日报发送失败。")

        crawler.logout()
        return

    # ===== 邮件爬取/搜索模式（需要网页登录）=====
    session_file = '.session_cache.json'

    session_loaded = crawler.load_session(username, session_file)
    if session_loaded:
        print("复用缓存会话，无需重新登录。\n")
    else:
        print("正在登录邮箱...")
        if not crawler.login(username, password):
            logger.error("登录失败，程序退出")
            return
        print("登录成功！\n")
        crawler.save_session(username, session_file)

    try:
        all_mails = []
        search_keyword = args.keyword

        if search_keyword:
            print(f"正在搜索包含 '{search_keyword}' 的邮件（最多20页）...")
            max_search_pages = 20
            for page in range(1, max_search_pages + 1):
                logger.info(f"搜索第 {page} 页")
                mails = crawler.get_mail_list(args.mailbox, page, target_date=None)
                if not mails:
                    break
                for mail in mails:
                    if 'id' in mail and crawler.current_sid:
                        mail['link'] = f"{crawler.base_url}/coremail/s?func=mbox:readMessage&mid={mail['id']}&sid={crawler.current_sid}"
                all_mails.extend(mails)
                logger.info(f"第 {page} 页爬取完成，共 {len(mails)} 封")
                if len(mails) < 50:
                    break
                if page < max_search_pages:
                    time.sleep(1)

            seen = set()
            deduped = []
            for m in all_mails:
                key = m.get('id') or f"{m.get('subject','')}|{m.get('time','')}"
                if key not in seen:
                    seen.add(key)
                    deduped.append(m)
            all_mails = deduped

            kw_lower = search_keyword.lower()
            all_mails = [
                m for m in all_mails
                if kw_lower in m.get('subject', '').lower()
                or kw_lower in m.get('sender', '').lower()
                or kw_lower in m.get('from', '').lower()
            ]
            print(f"共找到 {len(all_mails)} 封匹配邮件\n")
        else:
            print("正在获取邮件列表...")
            fetch_pages = args.pages
            if date_start and date_end:
                days_span = (date_end - date_start).days + 1
                fetch_pages = max(args.pages, min(40, days_span))
            target_date = selected_date
            for page in range(1, fetch_pages + 1):
                logger.info(f"开始爬取第 {page} 页")
                mails = crawler.get_mail_list(args.mailbox, page, target_date=target_date)
                if not mails:
                    logger.warning(f"第 {page} 页没有邮件或解析失败")
                    break
                for mail in mails:
                    if 'id' in mail and crawler.current_sid:
                        mail['link'] = f"{crawler.base_url}/coremail/s?func=mbox:readMessage&mid={mail['id']}&sid={crawler.current_sid}"
                all_mails.extend(mails)
                logger.info(f"第 {page} 页爬取完成，共 {len(mails)} 个邮件")
                if page < fetch_pages:
                    time.sleep(1)

            seen_ids = set()
            deduped = []
            for mail in all_mails:
                mid = mail.get('id', '')
                if mid and mid not in seen_ids:
                    seen_ids.add(mid)
                    deduped.append(mail)
            all_mails = deduped

            if date_start and date_end:
                print(f"正在筛选 {date_start} ~ {date_end} 的邮件...")
                date_mails = [mail for mail in all_mails if is_date_range_mail(mail, date_start, date_end)]
                logger.info(f"{date_start} ~ {date_end} 的邮件数量: {len(date_mails)} / {len(all_mails)}")
                all_mails = date_mails
            else:
                print(f"正在筛选 {selected_date} 的邮件...")
                date_mails = [mail for mail in all_mails if is_date_mail(mail, selected_date)]
                logger.info(f"{selected_date} 的邮件数量: {len(date_mails)} / {len(all_mails)}")
                all_mails = date_mails

        # 获取邮件内容
        if all_mails and not args.no_content:
            print(f"\n正在获取邮件内容（最多 {args.max_content} 封）...")
            max_content = min(args.max_content, len(all_mails))
            target_mails = all_mails[:max_content]

            pw_bodies = get_mail_content_playwright(username, password, target_mails)

            content_mails = []
            for i, mail in enumerate(target_mails):
                mail_id = mail.get('id', '')
                body = pw_bodies.get(mail_id, '')
                mail['content'] = body
                mail['body'] = body
                content_mails.append(mail)
                if body:
                    print(f"  获取邮件 {i+1}/{max_content}: {mail.get('subject', '无标题')} ({len(body)}字)")

            if content_mails:
                all_mails = content_mails + all_mails[max_content:]
                logger.info(f"成功获取 {len(content_mails)} 封邮件的内容")
            else:
                logger.warning("未能获取任何邮件的内容")

        # 过滤自己发给自己的邮件
        if not search_keyword and not args.mailbox == 'sent':
            all_mails = [
                m for m in all_mails
                if m.get('sender', m.get('from', '')).lower() != username.lower()
            ]

        # 输出结果
        if all_mails:
            print("\n" + "="*60)
            if search_keyword:
                print(f"关键词 '{search_keyword}' 搜索结果 ({len(all_mails)} 封)")
            elif date_start and date_end:
                print(f"{date_start} ~ {date_end} 邮件整理总结 ({len(all_mails)} 封)")
            else:
                print(f"{selected_date} 邮件整理总结 ({len(all_mails)} 封)")
            print("="*60)

            # 按发件人分组统计
            sender_groups = {}
            for mail in all_mails:
                sender = mail.get('sender', mail.get('from', '未知发件人'))
                if sender not in sender_groups:
                    sender_groups[sender] = []
                sender_groups[sender].append(mail)

            # 一段话总结
            ai_result = None
            if args.ai:
                print(f"\n正在调用 AI 分类总结...")
                ai_result = ai_classify_and_summarize(all_mails, api_key, api_base, ai_model)
                if not ai_result:
                    print("AI 服务不可用，将使用关键词摘要代替。")

            if ai_result and ai_result.get('summary'):
                print(f"\n【邮件总结】")
                print(f"{ai_result['summary']}")
            else:
                summary_date = selected_date if not search_keyword else None
                summary = generate_summary(all_mails, summary_date)
                print(f"\n【邮件总结】")
                print(f"{summary}")

            # 统计摘要
            print(f"\n【摘要统计】")
            print(f"  * 总邮件数：{len(all_mails)} 封")
            print(f"  * 发件人数量：{len(sender_groups)} 个")
            if search_keyword:
                print(f"  * 搜索关键词：{search_keyword}")
            elif date_start and date_end:
                print(f"  * 日期范围：{date_start} ~ {date_end}")
            else:
                print(f"  * 日期范围：{selected_date}")

            # 按发件人输出邮件
            print(f"\n【邮件详情】")
            for idx, (sender, mails) in enumerate(sender_groups.items(), 1):
                print(f"\n[发件人 {idx}] {sender} ({len(mails)} 封)")
                for i, mail in enumerate(mails, 1):
                    print(f"  {i}. {mail.get('subject', '无标题')}")
                    time_str = mail.get('time', mail.get('date', '未知时间'))
                    read_status = '已读' if mail.get('read', True) else '未读'
                    print(f"     时间：{time_str}")
                    print(f"     状态：{read_status}")
                    body = mail.get('body', '')
                    if body:
                        preview = ' '.join(body.split())
                        if preview:
                            print(f"     内容：{preview}")
                    attachments = mail.get('attachments', [])
                    if attachments:
                        attach_names = [attach.get('name', '未命名') for attach in attachments]
                        print(f"     附件：{', '.join(attach_names)}")

            # 分类总结
            print(f"\n【分类总结】")
            if ai_result and ai_result.get('categories'):
                for category, indices in ai_result['categories'].items():
                    print(f"  * {category}：{len(indices)} 封")
                    for idx in indices:
                        if 0 <= idx < len(all_mails):
                            mail = all_mails[idx]
                            print(f"    - {mail.get('subject', '无标题')}")
            else:
                subject_keywords = {
                    '会议': ['会议', 'meeting', '通知'],
                    '通知': ['通知', 'announcement', '通告'],
                    '报告': ['报告', 'report', '汇报'],
                    '提醒': ['提醒', 'reminder', '提示'],
                    '任务': ['任务', 'task', '工作'],
                    '其他': []
                }
                category_counts = {}
                for category, keywords in subject_keywords.items():
                    count = 0
                    for mail in all_mails:
                        subject = mail.get('subject', '').lower()
                        if category == '其他':
                            continue
                        for keyword in keywords:
                            if keyword in subject:
                                count += 1
                                break
                    if count > 0:
                        category_counts[category] = count
                other_count = len(all_mails) - sum(category_counts.values())
                if other_count > 0:
                    category_counts['其他'] = other_count
                for category, count in category_counts.items():
                    print(f"  * {category}：{count} 封")

            # 建议和提醒
            print(f"\n【建议和提醒】")
            unread_mails = [mail for mail in all_mails if not mail.get('read', True)]
            if unread_mails:
                print(f"  [注意] 有 {len(unread_mails)} 封未读邮件需要处理")

            urgent_keywords = ['紧急', 'urgent', '重要', 'important', '尽快', 'ASAP']
            urgent_mails = []
            for mail in all_mails:
                subject = mail.get('subject', '')
                body = mail.get('body', '')
                content = f"{subject} {body}".lower()
                for keyword in urgent_keywords:
                    if keyword in content:
                        urgent_mails.append(mail)
                        break
            if urgent_mails:
                print(f"  [注意] 有 {len(urgent_mails)} 封重要邮件需要优先处理")
                for mail in urgent_mails:
                    print(f"    * {mail.get('subject', '无标题')} - {mail.get('sender', '未知发件人')}")

            total_attachments = sum(len(mail.get('attachments', [])) for mail in all_mails)
            if total_attachments > 0:
                print(f"  [附件] 共有 {total_attachments} 个附件需要处理")

            print(f"\n" + "="*60)
            print(f"整理完成！建议优先处理未读邮件和重要邮件。")
            print("="*60)

        else:
            if search_keyword:
                print(f"\n[空] 未找到包含 '{search_keyword}' 的邮件")
            elif date_start and date_end:
                print(f"\n[空] {date_start} ~ {date_end} 没有邮件")
                print(f"提示：可以尝试检查其他日期范围或邮箱文件夹。")
            else:
                print(f"\n[空] {selected_date} 没有邮件")
                print(f"提示：可以尝试检查其他日期或邮箱文件夹。")

    finally:
        crawler.logout(keep_session=True)


if __name__ == "__main__":
    main()
