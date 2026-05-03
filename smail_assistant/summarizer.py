"""邮件摘要生成 + AI 分类总结"""

import logging
from datetime import date, datetime, timedelta
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


def generate_summary(mails: List[Dict], target_date: date = None) -> str:
    """生成一段话总结邮件内容"""
    if target_date is None:
        date_str = ""
    else:
        date_str = target_date.strftime('%Y年%m月%d日')
    if not mails:
        if date_str:
            return f"{date_str}没有收到邮件。"
        return "未找到匹配的邮件。"

    total_mails = len(mails)
    unread_mails = [mail for mail in mails if not mail.get('read', True)]
    unread_count = len(unread_mails)

    # 收集发件人信息
    senders = {}
    for mail in mails:
        sender = mail.get('sender', mail.get('from', '未知发件人'))
        senders[sender] = senders.get(sender, 0) + 1

    # 收集所有可用文本
    all_texts = []
    for mail in mails:
        subject = mail.get('subject', '')
        body = mail.get('body', mail.get('content', ''))
        all_texts.append(f"{subject} {body}")

    combined_text = ' '.join(all_texts).lower()

    # 常见主题关键词分类
    keywords = {
        '会议': ['会议', 'meeting', 'conference', '讨论'],
        '通知': ['通知', 'announcement', '通告', '公告'],
        '报告': ['报告', 'report', '总结', '分析'],
        '任务': ['任务', 'task', '工作', '待办'],
        '提醒': ['提醒', 'reminder', '提示', '注意'],
        '问题': ['问题', 'issue', 'bug', '错误', '故障'],
        '更新': ['更新', 'update', '升级', '版本'],
        '请求': ['请求', 'request', '申请', '要求'],
        '确认': ['确认', 'confirm', 'approve', '批准'],
    }
    topic_counts = {}
    for category, words in keywords.items():
        for word in words:
            if word in combined_text:
                topic_counts[category] = topic_counts.get(category, 0) + 1
                break

    # 生成总结
    summary_parts = []

    if total_mails == 1:
        summary_parts.append(f"{date_str}收到了1封邮件")
    else:
        summary_parts.append(f"{date_str}共收到了{total_mails}封邮件")

    if len(senders) == 1:
        summary_parts.append(f"全部来自{list(senders.keys())[0]}")
    elif len(senders) <= 3:
        summary_parts.append(f"来自{'、'.join(senders.keys())}等{len(senders)}位发件人")
    else:
        top_names = "、".join([n for n, _ in sorted(senders.items(), key=lambda x: x[1], reverse=True)[:3]])
        summary_parts.append(f"主要来自{top_names}等{len(senders)}位发件人")

    if topic_counts:
        topic_text = "、".join([t for t in sorted(topic_counts, key=topic_counts.get, reverse=True)[:3]])
        summary_parts.append(f"内容涉及{topic_text}相关事项")

    body_keywords = ['截止', '截稿', '会议室', '附件', '请回复', '尽快', '紧急', '重要']
    found = [w for w in body_keywords if w in combined_text]
    if found:
        summary_parts.append(f"邮件中提到{'、'.join(found[:3])}等关键词")

    if unread_count == 1:
        summary_parts.append(f"有1封未读邮件待处理")
    elif unread_count > 1:
        summary_parts.append(f"有{unread_count}封未读邮件待查看")

    summary = "，".join(summary_parts) + "。"
    if len(summary) > 500:
        summary = summary[:500] + "..."
    return summary


def ai_classify_and_summarize(mails: List[Dict], api_key: str, api_base: str,
                               model: str) -> Optional[Dict]:
    """
    通过 AI（Anthropic 兼容 API）对邮件进行分类和总结。

    Returns:
        {'summary': '总结段落', 'categories': {'类别': [邮件索引列表]}} 或 None
    """
    if not api_key:
        logger.warning("未提供 AI API Key，跳过 AI 分类总结")
        return None

    # 构建邮件信息文本
    mail_texts = []
    for i, m in enumerate(mails):
        subject = m.get('subject', '无标题')
        sender = m.get('from', m.get('sender', '未知'))
        body = m.get('body', '')
        if body:
            body = ' '.join(body.split())[:500]
        mail_texts.append(f"[{i+1}] 主题: {subject}\n    发件人: {sender}\n    正文: {body or '(无正文)'}")

    mails_content = "\n\n".join(mail_texts)

    prompt = f"""请对以下邮件进行分类和总结。

邮件列表：
{mails_content}

请按以下格式返回（严格遵守格式，不要添加多余内容）：

【分类】
每封邮件一行，格式为：序号. 类别
类别只能是以下之一：工作、学术、广告推广、通知、账务、社交、其他

【总结】
用2-3段话（150-300字）总结这些邮件的要点：每封邮件谁发的、核心内容是什么、有没有需要你采取行动或回复的、有无重要时间节点或截止日期。对广告推广类邮件一句话带过即可，重点展开有价值的邮件。"""

    try:
        import requests as req

        headers = {
            'x-api-key': api_key,
            'content-type': 'application/json',
            'anthropic-version': '2023-06-01'
        }
        payload = {
            'model': model,
            'max_tokens': 2048,
            'messages': [{'role': 'user', 'content': prompt}]
        }

        url = f"{api_base.rstrip('/')}/v1/messages"

        # 重试一次（MiMo 偶尔超时）
        resp = None
        for attempt in range(2):
            try:
                resp = req.post(url, json=payload, headers=headers, timeout=60, verify=False)
                resp.raise_for_status()
                break
            except req.exceptions.Timeout:
                if attempt == 0:
                    logger.warning("AI API 超时，正在重试...")
                else:
                    raise

        data = resp.json()

        # 提取回复文本（优先 text 类型，其次 thinking）
        content = ''
        if 'content' in data:
            for block in data['content']:
                if block.get('type') == 'text':
                    content += block.get('text', '')
            if not content:
                for block in data['content']:
                    if block.get('type') == 'thinking':
                        content += block.get('thinking', '')

        if not content:
            logger.warning("AI 返回内容为空")
            return None

        # 解析分类结果
        categories = {}
        summary = ''
        in_category = False
        in_summary = False

        for line in content.split('\n'):
            line = line.strip()
            if '分类' in line and '【' in line:
                in_category = True
                in_summary = False
                continue
            elif '总结' in line and '【' in line:
                in_category = False
                in_summary = True
                continue

            if in_category and line:
                parts = line.split('.', 1)
                if len(parts) == 2:
                    cat = parts[1].strip()
                    if cat:
                        categories.setdefault(cat, []).append(int(parts[0].strip()) - 1)
            elif in_summary and line:
                summary += line

        logger.info(f"AI 分类完成: {len(categories)} 个类别")
        return {'summary': summary, 'categories': categories}

    except Exception as e:
        logger.error(f"AI 分类总结失败: {e}")
        return None
