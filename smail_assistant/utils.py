"""日期工具、邮件日期过滤、文件保存"""

import os
import re
import json
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List

logger = logging.getLogger(__name__)


def parse_date_input(date_str: str) -> date:
    """解析日期输入字符串，支持多种格式（YYYY-M-D / YYYY/M/D / YYYY年M月D日）"""
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%Y年%m月%d日'):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            pass
    logger.warning(f"无法解析日期: {date_str}，使用当天日期")
    return date.today()


def is_date_mail(mail_info: Dict, target_date: date) -> bool:
    """检查邮件是否是指定日期的"""
    try:
        time_str = None
        for field in ['time', 'date', 'receivedDate', 'sentDate', 'received', 'sent']:
            if field in mail_info and mail_info[field]:
                time_str = str(mail_info[field])
                break

        if not time_str:
            return False

        # 简单字符串包含
        target_date_str = target_date.strftime('%Y-%m-%d')
        if target_date_str in time_str:
            return True

        alt_formats = [
            target_date.strftime('%Y/%m/%d'),
            target_date.strftime('%Y.%m.%d'),
            target_date.strftime('%Y年%m月%d日'),
        ]
        for fmt in alt_formats:
            if fmt in time_str:
                return True

        # 正则匹配
        patterns = [
            r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})',
            r'(\d{1,2})[-/](\d{1,2})[-/](\d{4})',
            r'(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})',
            r'([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})',
        ]

        for pattern_idx, pattern in enumerate(patterns):
            match = re.search(pattern, time_str)
            if match:
                groups = match.groups()
                if len(groups) == 3:
                    try:
                        if pattern_idx == 0:
                            year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
                        elif pattern_idx == 1:
                            day, month, year = int(groups[0]), int(groups[1]), int(groups[2])
                        elif pattern_idx == 2:
                            day, month_str, year = int(groups[0]), groups[1], int(groups[2])
                            month = datetime.strptime(month_str, '%B').month if month_str.isalpha() else int(month_str)
                        elif pattern_idx == 3:
                            month_str, day, year = groups[0], int(groups[1]), int(groups[2])
                            month = datetime.strptime(month_str, '%B').month if month_str.isalpha() else int(month_str)
                        else:
                            continue
                        mail_date = date(year, month, day)
                        return mail_date == target_date
                    except (ValueError, TypeError):
                        continue

        # 关键词匹配
        date_keywords = {
            '今天': date.today(),
            'today': date.today(),
            'yesterday': date.today() - timedelta(days=1),
            '昨天': date.today() - timedelta(days=1)
        }
        for keyword, keyword_date in date_keywords.items():
            if keyword.lower() in time_str.lower():
                return keyword_date == target_date

        return False
    except Exception as e:
        logger.debug(f"检查邮件日期时出错: {e}")
        return False


def is_today_mail(mail_info: Dict) -> bool:
    """检查邮件是否是今天的"""
    return is_date_mail(mail_info, date.today())


def is_date_range_mail(mail_info: Dict, start_date: date, end_date: date) -> bool:
    """检查邮件是否在指定日期范围内"""
    try:
        time_str = None
        for field in ['time', 'date', 'receivedDate', 'sentDate', 'received', 'sent']:
            if field in mail_info and mail_info[field]:
                time_str = str(mail_info[field])
                break

        if not time_str:
            return False

        patterns = [
            r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})',
        ]
        for pattern in patterns:
            match = re.search(pattern, time_str)
            if match:
                year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
                mail_date = date(year, month, day)
                return start_date <= mail_date <= end_date

        return False
    except Exception:
        return False


def save_mails(mails: List[Dict], output_dir: str = 'mails') -> None:
    """保存邮件数据为 JSON 文件"""
    if not mails:
        logger.warning("没有邮件数据可保存")
        return

    os.makedirs(output_dir, exist_ok=True)

    for i, mail in enumerate(mails):
        try:
            subject = mail.get('subject', f'mail_{i+1}')
            safe_subject = ''.join(c for c in subject if c.isalnum() or c in ' _-')
            safe_subject = safe_subject[:100]
            filename = f"{output_dir}/mail_{i+1:03d}_{safe_subject}.json"
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(mail, f, ensure_ascii=False, indent=2)
            logger.info(f"已保存邮件: {filename}")
        except Exception as e:
            logger.error(f"保存第 {i+1} 个邮件时出错: {e}")
