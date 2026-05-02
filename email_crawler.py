#!/usr/bin/env python3
"""
邮件内容爬取程序 - 针对 https://mail.nudt.edu.cn
注意：此程序为模板，需要根据实际网站结构调整选择器和参数
"""

import requests
from bs4 import BeautifulSoup
import time
import json
import os
import logging
import random
import smtplib
import argparse
import getpass
import re
from datetime import datetime, date, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from typing import List, Dict, Optional
import urllib3
from urllib3.exceptions import InsecureRequestWarning
from bs4 import XMLParsedAsHTMLWarning
import warnings
import sys
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# 强制使用UTF-8编码输出，避免Windows GBK编码导致中文乱码
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

# 配置日志（默认只显示WARNING及以上，--verbose时显示INFO）
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class MailCrawler:
    """邮件爬取器"""

    def __init__(self, base_url: str = "https://mail.nudt.edu.cn", disable_ssl_verify: bool = True,
                 smtp_host: str = "mail.nudt.edu.cn", smtp_port: int = 25):
        """
        初始化爬取器

        Args:
            base_url: 邮箱基础URL
            disable_ssl_verify: 是否禁用SSL证书验证（默认True，避免证书验证错误）
            smtp_host: SMTP 服务器地址（用于发送邮件）
            smtp_port: SMTP 服务器端口（默认25，也可用465/587）
        """
        self.base_url = base_url
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.session = requests.Session()
        # 禁用SSL证书验证（避免自签名证书错误）
        if disable_ssl_verify:
            self.session.verify = False
            urllib3.disable_warnings(InsecureRequestWarning)
            logger.warning("SSL证书验证已禁用，可能存在安全风险")
        # 设置请求头，模拟浏览器
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
        self.is_logged_in = False
        self.current_sid = None  # 当前会话的SID

    def login(self, username: str, password: str, **kwargs) -> bool:
        """
        登录邮箱系统

        Args:
            username: 用户名
            password: 密码
            **kwargs: 其他可能需要的参数（如验证码）

        Returns:
            登录是否成功
        """
        try:
            # 访问主页获取登录表单
            logger.info(f"访问邮箱主页: {self.base_url}")
            response = self._safe_request(self.base_url, method='get')
            if not response:
                logger.error("访问邮箱主页失败")
                return False
            response.raise_for_status()

            # 解析页面，查找登录表单
            soup = BeautifulSoup(response.text, 'lxml')

            # Coremail系统：查找包含sid参数的登录表单
            # 表单通常有类似这样的action: /coremail/index.jsp?cus=1&sid=xxx
            form = None
            for form_candidate in soup.find_all('form'):
                action = form_candidate.get('action', '')
                if 'coremail' in action and 'sid=' in action:
                    form = form_candidate
                    logger.info(f"找到Coremail登录表单: {action}")
                    break

            # 如果没有找到，尝试其他选择器
            if not form:
                logger.info("未找到标准Coremail表单，尝试通用选择器")
                form_selectors = [
                    'form.j-login-form',
                    'form.u-form',
                    'form[action*="coremail"]',
                    'form[action*="index.jsp"]',
                    'form'
                ]
                for selector in form_selectors:
                    form = soup.select_one(selector)
                    if form:
                        logger.info(f"使用选择器 '{selector}' 找到表单")
                        break

            if not form:
                logger.warning("未找到HTML表单，尝试从JavaScript中提取登录信息")

                # 尝试从JavaScript代码中提取sid（会话ID）
                sid = None
                # 查找 X = { ... s: 'sid_value', ... } 模式
                import re
                sid_patterns = [
                    r"s:\s*['\"]([A-Za-z0-9]+)['\"]",  # s: 'sid'
                    r"sid=([A-Za-z0-9]+)",  # sid=sid_value
                    r'"sid"\s*:\s*"([A-Za-z0-9]+)"'  # "sid": "value"
                ]

                for pattern in sid_patterns:
                    match = re.search(pattern, response.text)
                    if match:
                        sid = match.group(1)
                        logger.info(f"找到sid: {sid}")
                        break

                if not sid:
                    # 尝试从X对象中提取
                    x_pattern = r"X\s*=\s*\{[^}]*s:\s*['\"]([A-Za-z0-9]+)['\"]"
                    match = re.search(x_pattern, response.text, re.DOTALL)
                    if match:
                        sid = match.group(1)
                        logger.info(f"从X对象中找到sid: {sid}")

                if sid:
                    logger.info(f"使用提取的sid构建登录请求: {sid}")
                    # 构建登录URL
                    form_action = f"/coremail/index.jsp?cus=1&sid={sid}"
                    form_method = "post"

                    # 构建登录数据
                    login_data = {
                        'uid': username,
                        'password': password,
                        'locale': 'zh_CN',
                        'destURL': '',
                        'action:login': '',
                        'nodetect': 'false',
                        'supportLoginDevice': 'true',
                        'supportDynamicPwd': 'true',
                        'supportBind2FA': 'true'
                    }
                    # 跳过HTML表单处理
                    skip_html_form = True
                else:
                    logger.error("未找到登录表单和sid")
                    # 保存页面用于调试
                    with open('login_debug.html', 'w', encoding='utf-8') as f:
                        f.write(response.text)
                    logger.info("已保存登录页面到 login_debug.html")
                    return False
            else:
                # 使用找到的表单
                form_action = form.get('action', '')
                form_method = form.get('method', 'post').lower()
                skip_html_form = False

            # 如果不是从JavaScript路径，则处理HTML表单
            if not skip_html_form:
                # 构建登录数据
                login_data = {}

                # 查找所有input字段
                for input_tag in form.select('input'):
                    name = input_tag.get('name')
                    value = input_tag.get('value', '')
                    input_type = input_tag.get('type', '')
                    input_id = input_tag.get('id', '')

                    if name:
                        # Coremail特定字段处理
                        if name == 'uid':
                            # 用户名字段
                            login_data[name] = username
                        elif name == 'password':
                            # 密码字段（通常是隐藏字段）
                            login_data[name] = password
                        elif 'user' in name.lower() or 'account' in name.lower() or 'login' in name.lower():
                            # 其他可能的用户名字段
                            login_data[name] = username
                        elif 'pass' in name.lower() or 'pwd' in name.lower():
                            # 其他可能的密码字段
                            login_data[name] = password
                        elif input_type == 'text' and not value:
                            # 空的文本字段可能是用户名输入框
                            # 检查常见的用户名字段ID
                            if input_id in ['uid', 'username', 'user', 'account', 'loginname']:
                                login_data[name] = username
                        elif input_type == 'password':
                            # 密码输入框
                            login_data[name] = password
                        elif value:
                            # 其他有值的字段（如CSRF token、sid等）
                            login_data[name] = value

                # 如果没有找到用户名和密码字段，尝试手动添加常见字段名
                if 'uid' not in login_data:
                    # Coremail系统使用uid作为用户名字段
                    uid_input = form.select_one('input[name="uid"]')
                    if uid_input:
                        login_data['uid'] = username
                    else:
                        # 尝试其他常见字段
                        common_username_fields = ['username', 'user', 'email', 'account', 'loginname']
                        for field in common_username_fields:
                            if form.select_one(f'input[name="{field}"]'):
                                login_data[field] = username
                                break

                if 'password' not in login_data:
                    # 查找密码字段
                    password_input = form.select_one('input[name="password"]')
                    if password_input:
                        login_data['password'] = password
                    else:
                        # 尝试其他常见字段
                        common_password_fields = ['pass', 'pwd', 'passwd']
                        for field in common_password_fields:
                            if form.select_one(f'input[name="{field}"]'):
                                login_data[field] = password
                                break

                # 确保必要的字段存在
                if not any(key in login_data for key in ['uid', 'username', 'user', 'account']):
                    logger.error("未找到用户名字段")
                    return False

                if not any(key in login_data for key in ['password', 'pass', 'pwd']):
                    logger.error("未找到密码字段")
                    return False

                # 添加必要的隐藏字段
                required_fields = ['locale', 'destURL', 'action:login']
                for field in required_fields:
                    if field not in login_data:
                        field_input = form.select_one(f'input[name="{field}"]')
                        if field_input:
                            login_data[field] = field_input.get('value', '')

            logger.info(f"登录数据: { {k: '***' if 'pass' in k.lower() else v for k, v in login_data.items()} }")

            # 提交登录表单
            if form_action.startswith('http'):
                submit_url = form_action
            elif form_action.startswith('/'):
                submit_url = f"{self.base_url}{form_action}"
            else:
                submit_url = f"{self.base_url}/{form_action}"

            logger.info(f"提交登录请求到: {submit_url}")

            # 添加Referer头
            headers = {
                'Referer': self.base_url,
                'Origin': self.base_url,
                'Content-Type': 'application/x-www-form-urlencoded'
            }

            if form_method == 'post':
                response = self._safe_request(submit_url, method='post', data=login_data, headers=headers)
            else:
                response = self._safe_request(submit_url, method='get', params=login_data, headers=headers)

            if not response:
                logger.error("提交登录请求失败")
                return False
            response.raise_for_status()

            # 检查登录是否成功
            # Coremail系统登录成功后会重定向或显示收件箱
            response_text = response.text

            # 检查页面内容中的成功标识
            if '收件箱' in response_text or 'inbox' in response_text.lower() or 'logout' in response_text.lower():
                self.is_logged_in = True
                # 尝试从响应中提取SID
                import re
                sid_match = re.search(r'sid=([A-Za-z0-9]+)', response_text)
                if sid_match:
                    self.current_sid = sid_match.group(1)
                    logger.info(f"提取到SID: {self.current_sid}")
                logger.info("登录成功（页面包含成功标识）")
                return True

            # 检查HTTP重定向
            elif 'location' in response.headers or 'Location' in response.headers:
                # 有重定向，可能是登录成功
                redirect_url = response.headers.get('location') or response.headers.get('Location')
                logger.info(f"登录重定向到: {redirect_url}")
                # 跟随重定向
                redirect_response = self._safe_request(redirect_url, method='get')
                if not redirect_response:
                    logger.warning("重定向请求失败")
                    return False
                if '收件箱' in redirect_response.text or 'inbox' in redirect_response.text.lower():
                    self.is_logged_in = True
                    # 从重定向URL中提取SID
                    import re
                    sid_match = re.search(r'sid=([A-Za-z0-9]+)', redirect_url)
                    if sid_match:
                        self.current_sid = sid_match.group(1)
                        logger.info(f"从重定向URL提取到SID: {self.current_sid}")
                    logger.info("登录成功（通过HTTP重定向验证）")
                    return True
                else:
                    logger.warning("重定向后未找到成功标识")
                    with open('login_redirect_debug.html', 'w', encoding='utf-8') as f:
                        f.write(redirect_response.text)
                    return False

            # 检查JavaScript重定向（Coremail常见模式）
            elif 'var mainUrl' in response_text and 'coremail/XT/index.jsp?sid=' in response_text:
                logger.info("检测到JavaScript重定向，登录可能成功")

                # 尝试从JavaScript中提取新的sid
                import re
                sid_patterns = [
                    r'var sid\s*=\s*["\']([A-Za-z0-9]+)["\']',
                    r'var mainUrl\s*=\s*["\'][^"\']*sid=([A-Za-z0-9]+)["\']',
                    r'sid=([A-Za-z0-9]+)["\']'
                ]

                new_sid = None
                for pattern in sid_patterns:
                    match = re.search(pattern, response_text)
                    if match:
                        new_sid = match.group(1)
                        logger.info(f"从JavaScript中提取到新的sid: {new_sid}")
                        break

                if new_sid:
                    # 尝试访问重定向URL
                    redirect_url = f"{self.base_url}/coremail/XT/index.jsp?sid={new_sid}"
                    logger.info(f"尝试访问重定向URL: {redirect_url}")

                    redirect_response = self._safe_request(redirect_url, method='get')
                    if not redirect_response:
                        logger.warning("重定向请求失败")
                        return False
                    if '收件箱' in redirect_response.text or 'inbox' in redirect_response.text.lower():
                        self.is_logged_in = True
                        self.current_sid = new_sid
                        logger.info(f"设置SID: {self.current_sid}")
                        logger.info("登录成功（通过JavaScript重定向验证）")
                        return True
                    else:
                        # 即使重定向页面没有收件箱标识，也可能登录成功
                        # 检查页面是否包含邮箱相关元素
                        if '邮箱' in redirect_response.text or 'mail' in redirect_response.text.lower():
                            self.is_logged_in = True
                            self.current_sid = new_sid
                            logger.info(f"设置SID: {self.current_sid}")
                            logger.info("登录成功（页面包含邮箱相关元素）")
                            return True
                        else:
                            logger.warning("重定向页面不包含邮箱标识")
                            with open('js_redirect_debug.html', 'w', encoding='utf-8') as f:
                                f.write(redirect_response.text)
                            return False
                else:
                    logger.warning("检测到JavaScript重定向但未提取到sid")
                    # 保存页面用于调试
                    with open('login_response_debug.html', 'w', encoding='utf-8') as f:
                        f.write(response_text)
                    return False

            # 检查其他成功标识
            elif 'tokenUid' in response_text and 'coremail' in response_text:
                logger.info("检测到tokenUid和coremail，登录可能成功")
                # 尝试提取sid并访问主页面
                import re
                sid_match = re.search(r'sid=([A-Za-z0-9]+)', response_text)
                if sid_match:
                    new_sid = sid_match.group(1)
                    redirect_url = f"{self.base_url}/coremail/XT/index.jsp?sid={new_sid}"
                    logger.info(f"尝试访问主页面: {redirect_url}")

                    redirect_response = self._safe_request(redirect_url, method='get')
                    if not redirect_response:
                        logger.warning("访问主页面请求失败")
                        return False
                    if '收件箱' in redirect_response.text or 'inbox' in redirect_response.text.lower() or '邮箱' in redirect_response.text:
                        self.is_logged_in = True
                        self.current_sid = new_sid
                        logger.info(f"设置SID: {self.current_sid}")
                        logger.info("登录成功（通过sid重定向验证）")
                        return True

                # 即使没有明确的成功标识，如果有tokenUid也认为是成功
                if username in response_text:
                    self.is_logged_in = True
                    # 尝试从响应中提取SID
                    import re
                    sid_match = re.search(r'sid=([A-Za-z0-9]+)', response_text)
                    if sid_match:
                        self.current_sid = sid_match.group(1)
                        logger.info(f"提取到SID: {self.current_sid}")
                    logger.info(f"登录成功（页面包含用户名: {username}）")
                    return True

            # 如果没有找到任何成功标识，记录调试信息
            logger.warning("登录可能失败，页面不包含成功标识")
            # 保存页面用于调试
            with open('login_response_debug.html', 'w', encoding='utf-8') as f:
                f.write(response_text)
            logger.info("已保存登录响应页面到 login_response_debug.html")

            # 尝试检查是否有错误信息
            error_patterns = [
                r'错误[:：]?\s*([^<>\n]+)',
                r'失败[:：]?\s*([^<>\n]+)',
                r'error[:：]?\s*([^<>\n]+)',
                r'invalid|incorrect|wrong',
                r'密码错误|用户名错误|登录失败'
            ]

            for pattern in error_patterns:
                match = re.search(pattern, response_text, re.IGNORECASE)
                if match:
                    error_msg = match.group(1) if match.groups() else match.group(0)
                    logger.error(f"检测到错误信息: {error_msg}")
                    break

            return False

        except Exception as e:
            logger.error(f"登录过程中发生错误: {e}")
            import traceback
            logger.error(f"错误详情: {traceback.format_exc()}")
            return False

    def get_mail_list(self, mailbox: str = 'inbox', page: int = 1,
                      target_date: 'date' = None) -> List[Dict]:
        """
        获取邮件列表（使用Coremail JSON API）

        Args:
            mailbox: 邮箱类型（inbox收件箱，sent已发送，draft草稿箱等）
            page: 页码
            target_date: 目标日期，传入时尝试服务端过滤，减少无效请求

        Returns:
            邮件列表，每个邮件包含标题、发件人、时间等信息
        """
        if not self.is_logged_in:
            logger.error("未登录，请先登录")
            return []

        if not self.current_sid:
            logger.error("未获取到会话ID，请重新登录")
            return []

        try:
            # 邮箱类型映射
            mailbox_map = {
                'inbox': '1',
                'sent': '2',
                'draft': '3',
                'trash': '4',
                'spam': '5'
            }

            fid = mailbox_map.get(mailbox, '1')  # 默认为收件箱

            # 使用Coremail JSON API获取邮件列表
            # 注意：page参数可能不被API直接支持，但我们可以使用start和limit参数
            items_per_page = 50  # 每页邮件数量
            start = (page - 1) * items_per_page

            api_url = f"{self.base_url}/coremail/s/json"
            params = {
                'func': 'mbox:listMessages',
                'fid': fid,
                'sid': self.current_sid,
                'start': start,
                'limit': items_per_page
            }

            # 尝试服务端日期过滤（减少拉取量，降低服务器压力）
            if target_date:
                date_str = target_date.strftime('%Y%m%d')
                params['startDate'] = date_str
                params['endDate'] = date_str

            logger.info(f"获取邮件列表: 邮箱类型={mailbox}(fid={fid}), 页码={page}, 起始={start}")

            # 添加必要的请求头
            headers = {
                'Referer': f"{self.base_url}/coremail/XT/index.jsp?sid={self.current_sid}",
                'X-Requested-With': 'XMLHttpRequest',
                'Accept': 'application/json, text/javascript, */*; q=0.01'
            }

            response = self._safe_request(api_url, method='get', params=params, headers=headers)
            if not response:
                logger.error("获取邮件列表请求失败")
                return []
            response.raise_for_status()

            # 解析JSON响应
            try:
                data = json.loads(response.text)
            except json.JSONDecodeError as e:
                logger.error(f"JSON解析失败: {e}")
                logger.debug(f"响应内容: {response.text[:500]}...")
                return []

            if data.get('code') != 'S_OK':
                logger.error(f"API返回错误: {data.get('code')}")
                return []

            if 'var' not in data:
                logger.warning("API响应中未找到邮件数据")
                return []

            mail_items = []
            raw_mails = data['var']

            logger.info(f"API返回 {len(raw_mails)} 封邮件")

            for idx, raw_mail in enumerate(raw_mails):
                try:
                    mail_info = self._parse_mail_json(raw_mail)
                    if mail_info:
                        mail_info['index'] = idx + 1 + start  # 全局索引
                        mail_info['page'] = page
                        mail_items.append(mail_info)
                except Exception as e:
                    logger.error(f"解析第 {idx+1} 个邮件时出错: {e}")

            logger.info(f"成功解析 {len(mail_items)} 个邮件")
            return mail_items

        except Exception as e:
            logger.error(f"获取邮件列表时发生错误: {e}")
            return []

    def _parse_mail_item(self, mail_elem) -> Optional[Dict]:
        """
        解析单个邮件元素

        Args:
            mail_elem: BeautifulSoup元素

        Returns:
            邮件信息字典
        """
        try:
            mail_info = {}

            # 提取邮件链接（需要根据实际网站结构调整）
            # 常见的选择器: 'a.mail-link', '.subject a', 'td.subject a'
            link_elem = mail_elem.select_one('a')
            if link_elem and link_elem.get('href'):
                mail_info['link'] = link_elem['href']
                if not mail_info['link'].startswith('http'):
                    mail_info['link'] = f"{self.base_url}{mail_info['link']}"

            # 提取邮件标题
            # 常见的选择器: '.mail-subject', '.subject', 'td.subject'
            subject_elem = mail_elem.select_one('.subject, .mail-subject, td.subject')
            if subject_elem:
                mail_info['subject'] = subject_elem.get_text(strip=True)

            # 提取发件人
            # 常见的选择器: '.sender', '.from', 'td.from'
            sender_elem = mail_elem.select_one('.sender, .from, td.from')
            if sender_elem:
                mail_info['sender'] = sender_elem.get_text(strip=True)

            # 提取时间
            # 常见的选择器: '.time', '.date', 'td.date'
            time_elem = mail_elem.select_one('.time, .date, td.date')
            if time_elem:
                mail_info['time'] = time_elem.get_text(strip=True)

            # 提取是否已读
            # 常见的选择器: '.unread'（未读）, '.read'（已读）
            if mail_elem.select('.unread'):
                mail_info['read'] = False
            else:
                mail_info['read'] = True

            # 提取其他可能的信息
            mail_info['raw_html'] = str(mail_elem)

            return mail_info if mail_info else None

        except Exception as e:
            logger.error(f"解析邮件元素时出错: {e}")
            return None

    def _parse_mail_json(self, raw_mail: Dict) -> Optional[Dict]:
        """
        解析JSON格式的邮件数据

        Args:
            raw_mail: JSON格式的原始邮件数据

        Returns:
            邮件信息字典
        """
        try:
            mail_info = {}

            # 提取基本信息
            mail_info['id'] = raw_mail.get('id', '')
            mail_info['fid'] = raw_mail.get('fid', '')
            mail_info['subject'] = raw_mail.get('subject', '无标题')
            mail_info['from'] = raw_mail.get('from', '未知发件人')
            mail_info['sender'] = raw_mail.get('from', '未知发件人')  # 兼容旧字段
            mail_info['to'] = raw_mail.get('to', '')
            mail_info['size'] = raw_mail.get('size', 0)

            # 处理日期字段
            sent_date = raw_mail.get('sentDate', '')
            received_date = raw_mail.get('receivedDate', '')
            modified_date = raw_mail.get('modifiedDate', '')

            mail_info['sentDate'] = sent_date
            mail_info['receivedDate'] = received_date
            mail_info['modifiedDate'] = modified_date

            # 使用接收日期作为显示时间，如果没有则使用发送日期
            display_date = received_date if received_date else sent_date
            mail_info['time'] = display_date
            mail_info['date'] = display_date  # 兼容旧字段

            # 邮件状态
            flags = raw_mail.get('flags', {})
            mail_info['read'] = flags.get('read', True)
            mail_info['flags'] = flags

            # 其他字段
            mail_info['priority'] = raw_mail.get('priority', 3)
            mail_info['backgroundColor'] = raw_mail.get('backgroundColor', 0)
            mail_info['antiVirusStatus'] = raw_mail.get('antiVirusStatus', '')
            mail_info['label0'] = raw_mail.get('label0', 0)
            mail_info['hmid'] = raw_mail.get('hmid', '')

            # 构造邮件链接（如果需要查看邮件详情）
            # 注意：API返回的邮件可能没有直接链接，需要根据ID构造
            if mail_info['id'] and self.current_sid:
                # 构造邮件查看URL（可能需要根据实际情况调整）
                mail_info['link'] = f"{self.base_url}/coremail/s?func=mbox:readMessage&id={mail_info['id']}&sid={self.current_sid}"

            return mail_info

        except Exception as e:
            logger.error(f"解析JSON邮件数据时出错: {e}")
            return None

    def _parse_json_message(self, msg_data: Dict) -> Dict:
        """
        解析Coremail JSON API返回的消息数据

        Args:
            msg_data: API返回的消息数据字典

        Returns:
            标准化的邮件内容字典
        """
        mail_content = {}
        mail_content['subject'] = msg_data.get('subject', '')
        mail_content['from'] = msg_data.get('from', '')
        mail_content['to'] = msg_data.get('to', '')
        mail_content['date'] = msg_data.get('sentDate', msg_data.get('receivedDate', ''))

        # 从parts中提取正文（Coremail返回的邮件结构）
        body_text = ''
        body_html = ''
        parts = msg_data.get('part', [])
        if isinstance(parts, list):
            for part in parts:
                ct = part.get('ct', '')
                content = part.get('content', part.get('body', ''))
                if 'text/plain' in ct and content:
                    body_text = content
                elif 'text/html' in ct and content:
                    body_html = content

        # 回退到直接字段
        if not body_text and not body_html:
            body_text = msg_data.get('body', msg_data.get('content', ''))

        # 如果有HTML正文，提取纯文本
        if body_html and not body_text:
            soup = BeautifulSoup(body_html, 'lxml')
            for tag in soup(["script", "style"]):
                tag.decompose()
            body_text = soup.get_text(separator='\n', strip=True)

        mail_content['body'] = body_text.strip()
        mail_content['body_html'] = body_html

        # 附件信息
        attachments = msg_data.get('attach', [])
        if isinstance(attachments, list):
            mail_content['attachments'] = [
                {'name': a.get('name', '未命名'), 'size': a.get('size', 0)}
                for a in attachments
            ]

        return mail_content

    def get_mail_content(self, mail_url: str) -> Optional[Dict]:
        """
        获取邮件详细内容（优先使用Coremail JSON API）

        Args:
            mail_url: 邮件详情页URL（含id参数）

        Returns:
            邮件内容字典
        """
        if not self.is_logged_in:
            logger.error("未登录，请先登录")
            return None

        try:
            # 从URL中提取邮件ID（兼容 mid 和 id 两种参数名）
            id_match = re.search(r'[?&]mid=([^&\s]+)', mail_url)
            if not id_match:
                id_match = re.search(r'[?&]id=([^&\s]+)', mail_url)
            mail_id = id_match.group(1) if id_match else None

            api_headers = {
                'Referer': f"{self.base_url}/coremail/XT/index.jsp?sid={self.current_sid}",
                'X-Requested-With': 'XMLHttpRequest',
                'Accept': 'application/json, text/javascript, */*; q=0.01'
            }

            # 尝试多种Coremail JSON API方式
            if mail_id and self.current_sid:
                api_url = f"{self.base_url}/coremail/s/json"
                attempts = [
                    # 方式1：GET + mid（NUDT Coremail 唯一返回 S_OK 的方式）
                    ('get', api_url, {'func': 'mbox:readMessage', 'mid': mail_id, 'sid': self.current_sid}),
                    # 方式2：GET + id
                    ('get', api_url, {'func': 'mbox:readMessage', 'id': mail_id, 'sid': self.current_sid}),
                    # 方式3：POST + mid
                    ('post', f"{api_url}?func=mbox:readMessage&sid={self.current_sid}", {'mid': mail_id}),
                    # 方式4：POST + id
                    ('post', f"{api_url}?func=mbox:readMessage&sid={self.current_sid}", {'id': mail_id}),
                ]
                for method, url, payload in attempts:
                    kwargs = {'data': payload} if method == 'post' else {'params': payload}
                    response = self._safe_request(url, method=method, headers=api_headers, **kwargs)
                    if response:
                        try:
                            data = json.loads(response.text)
                            if data.get('code') == 'S_OK' and 'var' in data:
                                logger.info(f"JSON API获取邮件内容成功 ({method.upper()} {url})")
                                return self._parse_json_message(data['var'])
                        except (json.JSONDecodeError, Exception):
                            pass

            # 所有JSON API方式均失败，返回空内容（避免把错误文本当正文）
            logger.debug(f"所有JSON API方式均未返回邮件内容: {mail_url}")
            return {'body': '', 'attachments': []}

        except Exception as e:
            logger.error(f"获取邮件内容时发生错误: {e}")
            return None

    @staticmethod
    def get_mail_content_playwright(username: str, password: str,
                                     mail_list: List[Dict]) -> Dict[str, str]:
        """
        通过 Playwright 浏览器自动化批量获取邮件正文。

        登录后调用 readMessage.jsp 获取每封邮件的 HTML 正文。
        readMessage.jsp 返回 mainPartData.content 字段包含完整的邮件 HTML 内容。

        Args:
            username: 邮箱用户名
            password: 邮箱密码
            mail_list: 邮件元数据列表（含 id, subject 等字段）

        Returns:
            {原始mail_id: body_text} 字典
        """
        result = {}
        if not mail_list:
            return result
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.warning("未安装 playwright，请运行: pip install playwright && playwright install chromium")
            return result

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(ignore_https_errors=True)
            page = ctx.new_page()

            # 登录
            page.goto('https://mail.nudt.edu.cn', wait_until='networkidle')
            login_js = '''async (creds) => {
                var scripts = document.querySelectorAll('script');
                var sid = '';
                for (var s of scripts) {
                    var m = s.textContent.match(/sid=([A-Za-z0-9]+)/);
                    if (m) { sid = m[1]; break; }
                }
                var fd = new URLSearchParams();
                fd.append('uid', creds.username);
                fd.append('password', creds.password);
                fd.append('locale', 'zh_CN');
                fd.append('destURL', '');
                fd.append('action:login', '');
                fd.append('nodetect', 'false');
                fd.append('supportLoginDevice', 'true');
                fd.append('supportDynamicPwd', 'true');
                fd.append('supportBind2FA', 'true');
                var resp = await fetch('/coremail/index.jsp?cus=1&sid=' + sid, {
                    method: 'POST', body: fd.toString(),
                    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                    redirect: 'follow'
                });
                var text = await resp.text();
                var newSid = text.match(/sid=([A-Za-z0-9]+)/);
                return newSid ? newSid[1] : '';
            }'''
            sid = page.evaluate(login_js, {'username': username, 'password': password})

            if not sid:
                logger.error("Playwright 登录失败")
                browser.close()
                return result

            logger.info(f"Playwright 登录成功")

            # 导航到邮箱主页（建立会话上下文）
            page.goto(f'https://mail.nudt.edu.cn/coremail/XT/index.jsp?sid={sid}',
                       wait_until='networkidle')

            # 逐封获取邮件正文
            read_js = '''async (args) => {
                var fd = new URLSearchParams();
                fd.append('mid', args.mid);
                fd.append('mode', 'html');
                var resp = await fetch('/coremail/XT/jsp/readMessage.jsp?sid=' + args.sid, {
                    method: 'POST', body: fd.toString(),
                    headers: {'Content-Type': 'application/x-www-form-urlencoded'}
                });
                var data = await resp.json();
                if (data.code !== 'S_OK') return {ok: false, error: data.code};
                var mail = data.var && data.var.mail;
                if (!mail) return {ok: false, error: 'no mail'};
                var mpd = mail.mainPartData;
                if (mpd && mpd.content) {
                    var div = document.createElement('div');
                    div.innerHTML = mpd.content;
                    return {ok: true, text: div.innerText.trim()};
                }
                return {ok: false, error: 'no content'};
            }'''

            for mail in mail_list:
                orig_id = mail.get('id', '')
                subject = mail.get('subject', '无标题')
                if not orig_id:
                    continue

                try:
                    resp = page.evaluate(read_js, {'sid': sid, 'mid': orig_id})
                    if resp.get('ok'):
                        body_text = resp.get('text', '')
                        result[orig_id] = body_text
                        logger.info(f"Playwright 获取正文成功 [{subject[:30]}]: {len(body_text)} 字符")
                    else:
                        error = resp.get('error', '')
                        logger.warning(f"Playwright 获取正文失败 [{subject[:30]}]: {error}")
                        result[orig_id] = ''
                except Exception as e:
                    logger.warning(f"Playwright 读取邮件 [{subject[:30]}] 失败: {e}")
                    result[orig_id] = ''

            browser.close()

        return result

    def send_mail(self, to: str, subject: str, body: str, cc: str = '', bcc: str = '',
                  is_html: bool = False, priority: int = 3,
                  attachments: List[str] = None, username: str = '', password: str = '') -> bool:
        """
        发送邮件（优先 Coremail API，失败则回退 SMTP）

        Args:
            to: 收件人邮箱，多个用逗号分隔
            subject: 邮件主题
            body: 邮件正文
            cc: 抄送，多个用逗号分隔
            bcc: 密送，多个用逗号分隔
            is_html: 正文是否为HTML格式（默认False，纯文本）
            priority: 优先级 (3=普通, 1=紧急, 5=低)
            attachments: 附件文件路径列表
            username: 登录用户名
            password: 登录密码

        Returns:
            是否发送成功
        """
        if not username or not password:
            logger.error("发送需要提供用户名和密码")
            return False

        return self._send_mail_smtp(to, subject, body, cc, bcc, is_html, priority, attachments, username, password)

    def _send_mail_smtp(self, to: str, subject: str, body: str, cc: str = '', bcc: str = '',
                        is_html: bool = False, priority: int = 3,
                        attachments: List[str] = None, username: str = '', password: str = '') -> bool:
        """通过 SMTP 发送邮件（自动尝试 SOCKS5 代理 + SSL）"""

        from_addr = username

        try:
            # 构建邮件
            if is_html or attachments:
                msg = MIMEMultipart()
                subtype = 'html' if is_html else 'plain'
                msg.attach(MIMEText(body, subtype, 'utf-8'))
            else:
                msg = MIMEText(body, 'plain', 'utf-8')

            msg['From'] = from_addr
            msg['To'] = to
            msg['Subject'] = subject
            if cc:
                msg['Cc'] = cc
            if priority == 1:
                msg['X-Priority'] = '1 (Highest)'
            elif priority == 5:
                msg['X-Priority'] = '5 (Lowest)'

            # 添加附件
            if attachments:
                for filepath in attachments:
                    if not os.path.isfile(filepath):
                        logger.warning(f"附件不存在，跳过: {filepath}")
                        continue
                    with open(filepath, 'rb') as f:
                        part = MIMEBase('application', 'octet-stream')
                        part.set_payload(f.read())
                        encoders.encode_base64(part)
                        filename = os.path.basename(filepath)
                        part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
                        msg.attach(part)
                        logger.info(f"已添加附件: {filename}")

            # 收集所有收件人
            recipients = [addr.strip() for addr in to.split(',') if addr.strip()]
            if cc:
                recipients += [addr.strip() for addr in cc.split(',') if addr.strip()]
            if bcc:
                recipients += [addr.strip() for addr in bcc.split(',') if addr.strip()]

            # 尝试 SOCKS5 代理 + SSL 端口 465（绕过代理工具对 SMTP 的干扰）
            server = None
            for attempt in ['socks_ssl', 'direct']:
                try:
                    if attempt == 'socks_ssl':
                        try:
                            import socks
                            socks.set_default_proxy(socks.SOCKS5, '127.0.0.1', 7897)
                            import socket as _socket
                            _socket.socket = socks.socksocket
                            import ssl as _ssl
                            ctx = _ssl.create_default_context()
                            ctx.check_hostname = False
                            ctx.verify_mode = _ssl.CERT_NONE
                            server = smtplib.SMTP_SSL(self.smtp_host, 465, timeout=15, context=ctx)
                            logger.info("通过 SOCKS5 代理连接 SMTP (端口465 SSL)")
                        except ImportError:
                            continue
                    else:
                        if self.smtp_port == 465:
                            server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=15)
                        else:
                            server = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=15)
                            server.ehlo()
                        logger.info(f"直接连接 SMTP 服务器: {self.smtp_host}:{self.smtp_port}")

                    server.login(username, password)
                    server.sendmail(from_addr, recipients, msg.as_string())
                    server.quit()
                    logger.info(f"邮件发送成功: to={to}, subject={subject}")
                    return True
                except Exception as e:
                    if server:
                        try:
                            server.quit()
                        except:
                            pass
                    server = None
                    if attempt == 'socks_ssl':
                        logger.warning(f"SOCKS5 SSL 发送失败，尝试直连: {e}")
                    else:
                        raise

        except smtplib.SMTPAuthenticationError:
            logger.error("SMTP 认证失败，请检查用户名和密码")
        except smtplib.SMTPConnectError:
            logger.error(f"无法连接到 SMTP 服务器 {self.smtp_host}:{self.smtp_port}")
        except Exception as e:
            logger.error(f"发送邮件时发生错误: {e}")
        return False

    def save_mails(self, mails: List[Dict], output_dir: str = 'mails'):
        """
        保存邮件数据

        Args:
            mails: 邮件数据列表
            output_dir: 输出目录
        """
        if not mails:
            logger.warning("没有邮件数据可保存")
            return

        os.makedirs(output_dir, exist_ok=True)

        for i, mail in enumerate(mails):
            try:
                # 生成文件名
                subject = mail.get('subject', f'mail_{i+1}')
                # 清理文件名中的非法字符
                safe_subject = ''.join(c for c in subject if c.isalnum() or c in ' _-')
                safe_subject = safe_subject[:100]  # 限制长度

                filename = f"{output_dir}/mail_{i+1:03d}_{safe_subject}.json"

                # 保存为JSON
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(mail, f, ensure_ascii=False, indent=2)

                logger.info(f"已保存邮件: {filename}")

            except Exception as e:
                logger.error(f"保存第 {i+1} 个邮件时出错: {e}")

    def logout(self, keep_session: bool = True, session_file: str = '.session_cache.json') -> None:
        """
        退出登录

        Args:
            keep_session: True时保留服务器会话（不调用服务器logout），只清除本地状态；
                          False时调用服务器logout并删除缓存文件
        """
        if keep_session:
            # 只清除本地登录状态，不通知服务器，会话可继续复用
            self.is_logged_in = False
            logger.info("已清除本地登录状态（会话已缓存，下次可直接使用）")
        else:
            try:
                logout_url = f"{self.base_url}/coremail/s/json?func=user:logout&sid={self.current_sid}"
                self.session.get(logout_url, timeout=5)
            except Exception:
                pass
            self.is_logged_in = False
            # 删除缓存文件
            if os.path.exists(session_file):
                try:
                    os.remove(session_file)
                except Exception:
                    pass
            logger.info("已退出登录并清除会话缓存")

    @staticmethod
    def is_date_mail(mail_info: Dict, target_date: date) -> bool:
        """
        检查邮件是否是指定日期的

        Args:
            mail_info: 邮件信息字典
            target_date: 目标日期

        Returns:
            如果是指定日期则返回True
        """
        try:
            # 尝试从邮件信息中提取时间字段
            time_str = None
            for field in ['time', 'date', 'receivedDate', 'sentDate', 'received', 'sent']:
                if field in mail_info and mail_info[field]:
                    time_str = str(mail_info[field])
                    break

            if not time_str:
                return False

            # 首先尝试简单字符串包含（API返回的日期格式为"2020-07-20 21:42:10"）
            target_date_str = target_date.strftime('%Y-%m-%d')
            if target_date_str in time_str:
                return True

            # 尝试其他格式的字符串包含
            alt_formats = [
                target_date.strftime('%Y/%m/%d'),
                target_date.strftime('%Y.%m.%d'),
                target_date.strftime('%Y年%m月%d日'),
            ]
            for fmt in alt_formats:
                if fmt in time_str:
                    return True

            # 常见日期时间格式正则表达式
            patterns = [
                r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})',  # YYYY-MM-DD, YYYY/MM/DD
                r'(\d{1,2})[-/](\d{1,2})[-/](\d{4})',  # DD-MM-YYYY, DD/MM/YYYY
                r'(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})',  # DD Month YYYY
                r'([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})', # Month DD, YYYY
            ]

            for pattern_idx, pattern in enumerate(patterns):
                match = re.search(pattern, time_str)
                if match:
                    groups = match.groups()
                    if len(groups) == 3:
                        # 尝试解析日期
                        try:
                            if pattern_idx == 0:  # YYYY-MM-DD
                                year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
                            elif pattern_idx == 1:  # DD-MM-YYYY
                                day, month, year = int(groups[0]), int(groups[1]), int(groups[2])
                            elif pattern_idx == 2:  # DD Month YYYY
                                day, month_str, year = int(groups[0]), groups[1], int(groups[2])
                                month = datetime.strptime(month_str, '%B').month if month_str.isalpha() else int(month_str)
                            elif pattern_idx == 3:  # Month DD, YYYY
                                month_str, day, year = groups[0], int(groups[1]), int(groups[2])
                                month = datetime.strptime(month_str, '%B').month if month_str.isalpha() else int(month_str)
                            else:
                                continue

                            mail_date = date(year, month, day)
                            return mail_date == target_date
                        except (ValueError, TypeError):
                            continue

            # 如果包含日期关键词
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

    @staticmethod
    def is_today_mail(mail_info: Dict) -> bool:
        """
        检查邮件是否是今天的

        Args:
            mail_info: 邮件信息字典

        Returns:
            如果是今天则返回True
        """
        return MailCrawler.is_date_mail(mail_info, date.today())

    @staticmethod
    def is_date_range_mail(mail_info: Dict, start_date: date, end_date: date) -> bool:
        """
        检查邮件是否在指定日期范围内

        Args:
            mail_info: 邮件信息字典
            start_date: 起始日期（含）
            end_date: 结束日期（含）

        Returns:
            如果在范围内则返回True
        """
        try:
            time_str = None
            for field in ['time', 'date', 'receivedDate', 'sentDate', 'received', 'sent']:
                if field in mail_info and mail_info[field]:
                    time_str = str(mail_info[field])
                    break

            if not time_str:
                return False

            # 提取邮件日期
            patterns = [
                r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})',  # YYYY-MM-DD, YYYY/MM/DD
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

    @staticmethod
    def generate_summary(mails: List[Dict], target_date: date = None) -> str:
        """
        生成一段话总结邮件内容

        Args:
            mails: 邮件列表，包含主题和内容
            target_date: 目标日期，如果为None则使用当天日期

        Returns:
            一段话的总结
        """
        # 格式化日期前缀
        if target_date is None:
            date_str = ""
        else:
            date_str = target_date.strftime('%Y年%m月%d日')
        if not mails:
            if date_str:
                return f"{date_str}没有收到邮件。"
            return "未找到匹配的邮件。"

        # 统计邮件数量
        total_mails = len(mails)
        unread_mails = [mail for mail in mails if not mail.get('read', True)]
        unread_count = len(unread_mails)

        # 收集发件人信息
        senders = {}
        for mail in mails:
            sender = mail.get('sender', mail.get('from', '未知发件人'))
            senders[sender] = senders.get(sender, 0) + 1

        # 收集所有可用文本（标题 + 正文）
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

        # 基本统计
        if total_mails == 1:
            summary_parts.append(f"{date_str}收到了1封邮件")
        else:
            summary_parts.append(f"{date_str}共收到了{total_mails}封邮件")

        # 发件人信息
        if len(senders) == 1:
            summary_parts.append(f"全部来自{list(senders.keys())[0]}")
        elif len(senders) <= 3:
            summary_parts.append(f"来自{'、'.join(senders.keys())}等{len(senders)}位发件人")
        else:
            top_names = "、".join([n for n, _ in sorted(senders.items(), key=lambda x: x[1], reverse=True)[:3]])
            summary_parts.append(f"主要来自{top_names}等{len(senders)}位发件人")

        # 主题类别
        if topic_counts:
            topic_text = "、".join([t for t in sorted(topic_counts, key=topic_counts.get, reverse=True)[:3]])
            summary_parts.append(f"内容涉及{topic_text}相关事项")

        # 正文关键信息提取
        body_keywords = ['截止', '截稿', '会议室', '附件', '请回复', '尽快', '紧急', '重要']
        found = [w for w in body_keywords if w in combined_text]
        if found:
            summary_parts.append(f"邮件中提到{'、'.join(found[:3])}等关键词")

        # 未读邮件
        if unread_count == 1:
            summary_parts.append(f"有1封未读邮件待处理")
        elif unread_count > 1:
            summary_parts.append(f"有{unread_count}封未读邮件待查看")

        summary = "，".join(summary_parts) + "。"
        if len(summary) > 500:
            summary = summary[:500] + "..."
        return summary

    @staticmethod
    def ai_classify_and_summarize(mails: List[Dict], api_key: str, api_base: str,
                                   model: str) -> Optional[Dict]:
        """
        通过 AI（Anthropic 兼容 API）对邮件进行分类和总结。

        Args:
            mails: 邮件列表（需含 subject, body 字段）
            api_key: API Key
            api_base: API Base URL
            model: 模型名称

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
                    # 解析 "1. 广告推广" 格式
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

    def save_session(self, username: str, session_file: str = '.session_cache.json') -> None:
        """保存会话到本地文件，下次运行可直接复用，避免频繁登录"""
        try:
            data = {
                'username': username,
                'sid': self.current_sid,
                'cookies': {k: v for k, v in self.session.cookies.items()},
                'saved_at': datetime.now().isoformat()
            }
            with open(session_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
            try:
                os.chmod(session_file, 0o600)  # 仅自己可读（Unix有效）
            except Exception:
                pass
            logger.info(f"会话已缓存到 {session_file}")
        except Exception as e:
            logger.warning(f"保存会话失败: {e}")

    def load_session(self, username: str, session_file: str = '.session_cache.json',
                     max_age_hours: int = 8) -> bool:
        """从本地文件加载会话，验证有效性后返回是否成功"""
        if not os.path.exists(session_file):
            return False
        try:
            with open(session_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 验证用户名
            if data.get('username') != username:
                logger.info("缓存会话用户名不匹配，将重新登录")
                return False

            # 验证时效（默认8小时）
            saved_at = datetime.fromisoformat(data['saved_at'])
            age_hours = (datetime.now() - saved_at).total_seconds() / 3600
            if age_hours > max_age_hours:
                logger.info(f"缓存会话已超过 {max_age_hours} 小时，将重新登录")
                return False

            # 恢复 cookies 和 SID
            for k, v in data.get('cookies', {}).items():
                self.session.cookies.set(k, v)
            self.current_sid = data.get('sid')
            if not self.current_sid:
                return False

            # 用轻量级API调用验证会话是否仍然有效
            api_url = f"{self.base_url}/coremail/s/json"
            headers = {
                'Referer': f"{self.base_url}/coremail/XT/index.jsp?sid={self.current_sid}",
                'X-Requested-With': 'XMLHttpRequest',
            }
            response = self._safe_request(
                api_url, method='get',
                params={'func': 'mbox:listMessages', 'fid': '1', 'sid': self.current_sid,
                        'start': '0', 'limit': '1'},
                headers=headers
            )
            if response:
                try:
                    result = json.loads(response.text)
                    if result.get('code') == 'S_OK':
                        self.is_logged_in = True
                        logger.info("缓存会话有效，跳过登录")
                        return True
                except Exception:
                    pass

            logger.info("缓存会话已失效，将重新登录")
            return False

        except Exception as e:
            logger.warning(f"加载缓存会话失败: {e}")
            return False

    def _random_delay(self, min_seconds: float = 1.0, max_seconds: float = 3.0) -> None:
        """
        添加随机延迟，避免请求过快被封号

        Args:
            min_seconds: 最小延迟秒数
            max_seconds: 最大延迟秒数
        """
        delay = random.uniform(min_seconds, max_seconds)
        logger.debug(f"添加随机延迟: {delay:.2f} 秒")
        time.sleep(delay)

    def _safe_request(self, url: str, method: str = 'get', **kwargs) -> Optional[requests.Response]:
        """
        安全的请求方法，包含随机延迟和错误处理

        Args:
            url: 请求URL
            method: 请求方法（get/post）
            **kwargs: 其他请求参数

        Returns:
            响应对象或None
        """
        try:
            # 在请求前添加随机延迟（缩短至0.3-0.8秒）
            self._random_delay(0.3, 0.8)

            if method.lower() == 'get':
                response = self.session.get(url, **kwargs)
            elif method.lower() == 'post':
                response = self.session.post(url, **kwargs)
            else:
                logger.error(f"不支持的请求方法: {method}")
                return None

            response.raise_for_status()

            # 请求后添加短延迟（0.2-0.5秒）
            time.sleep(random.uniform(0.2, 0.5))

            return response

        except requests.exceptions.RequestException as e:
            logger.error(f"请求失败: {url} - {e}")
            # 请求失败后等待较长时间再重试
            time.sleep(random.uniform(2.0, 3.0))
            return None
        except Exception as e:
            logger.error(f"请求发生未知错误: {url} - {e}")
            return None


def parse_date_input(date_str: str) -> date:
    """解析日期输入字符串，支持多种格式（YYYY-M-D / YYYY/M/D / YYYY年M月D日）"""
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%Y年%m月%d日'):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            pass
    logger.warning(f"无法解析日期: {date_str}，使用当天日期")
    return date.today()


def main():
    """主函数"""
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

    args = parser.parse_args()

    # 根据--verbose参数调整日志级别
    if args.verbose:
        logging.getLogger().setLevel(logging.INFO)
        logger.setLevel(logging.INFO)

    # 自动加载 config.json（如果存在），--config 可指定其他路径
    config = {}
    config_path = args.config or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

    username = args.username or config.get('username')
    password = args.password or config.get('password')

    # AI 配置（命令行优先，其次从 config.json 读取）
    api_key = args.api_key or config.get('ai_api_key')
    api_base = args.api_base or config.get('ai_api_base', 'https://token-plan-cn.xiaomimimo.com/anthropic')
    ai_model = args.ai_model or config.get('ai_model', 'mimo-v2-flash')

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
        # 发送模式且已有凭据（命令行传入），提醒已使用命令行凭据
        logger.info("使用命令行提供的凭据发送邮件")
    else:
        # 爬取模式且已有凭据
        logger.info("使用命令行提供的凭据登录邮箱")

    # 日期选择（关键词搜索模式下跳过）
    selected_date = None
    date_start = None
    date_end = None
    if args.send:
        selected_date = date.today()  # 发送模式不需要日期选择
    elif args.keyword:
        selected_date = None  # 关键词模式不需要日期
    elif args.start_date or args.end_date:
        # 日期范围模式
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
            print("用法: python email_crawler.py --send --username user@domain.com --password pwd "
                  "--to recipient@example.com --subject '主题' --body '正文'")
            return

        to_addr = args.to
        subject = args.subject
        body = args.body
        cc = args.cc or ''
        bcc = args.bcc or ''
        is_html = not args.text
        attachments = args.attachments or []

        print(f"\n正在发送邮件...")
        print(f"  发件人: {username}")
        print(f"  收件人: {to_addr}")
        print(f"  主题: {subject}")
        if cc:
            print(f"  抄送: {cc}")
        if bcc:
            print(f"  密送: {bcc}")
        if attachments:
            print(f"  附件: {', '.join(attachments)}")

        success = crawler.send_mail(
            to=to_addr, subject=subject, body=body,
            cc=cc, bcc=bcc, is_html=is_html,
            attachments=attachments,
            username=username, password=password,
        )
        if success:
            print(f"\n邮件发送成功！")
        else:
            print(f"\n邮件发送失败，请检查日志。")
        return

    # ===== 邮件爬取/搜索模式（需要网页登录）=====
    session_file = '.session_cache.json'

    # 优先复用缓存会话，避免频繁登录
    session_loaded = crawler.load_session(username, session_file)
    if session_loaded:
        print("复用缓存会话，无需重新登录。\n")
    else:
        print("正在登录邮箱...")
        if not crawler.login(username, password):
            logger.error("登录失败，程序退出")
            return
        print("登录成功！\n")
        # 保存会话供下次使用
        crawler.save_session(username, session_file)

    try:
        all_mails = []
        search_keyword = args.keyword  # 关键词搜索模式

        if search_keyword:
            # 关键词搜索模式：跨日期搜索，最多20页
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
                    break  # 最后一页，无需继续
                if page < max_search_pages:
                    time.sleep(1)

            # 去重（按邮件ID或主题+时间组合去重）
            seen = set()
            deduped = []
            for m in all_mails:
                key = m.get('id') or f"{m.get('subject','')}|{m.get('time','')}"
                if key not in seen:
                    seen.add(key)
                    deduped.append(m)
            all_mails = deduped

            # 客户端关键词过滤（主题/发件人不区分大小写）
            kw_lower = search_keyword.lower()
            all_mails = [
                m for m in all_mails
                if kw_lower in m.get('subject', '').lower()
                or kw_lower in m.get('sender', '').lower()
                or kw_lower in m.get('from', '').lower()
            ]
            print(f"共找到 {len(all_mails)} 封匹配邮件\n")
        else:
            # 日期模式：按日期获取邮件
            print("正在获取邮件列表...")
            # 日期范围模式拉取更多页
            fetch_pages = args.pages
            if date_start and date_end:
                days_span = (date_end - date_start).days + 1
                fetch_pages = max(args.pages, min(40, days_span))
            target_date = selected_date  # 单日模式传给 API 做服务端过滤
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

            # 去重
            seen_ids = set()
            deduped = []
            for mail in all_mails:
                mid = mail.get('id', '')
                if mid and mid not in seen_ids:
                    seen_ids.add(mid)
                    deduped.append(mail)
            all_mails = deduped

            # 筛选日期
            if date_start and date_end:
                print(f"正在筛选 {date_start} ~ {date_end} 的邮件...")
                date_mails = [mail for mail in all_mails if MailCrawler.is_date_range_mail(mail, date_start, date_end)]
                logger.info(f"{date_start} ~ {date_end} 的邮件数量: {len(date_mails)} / {len(all_mails)}")
                all_mails = date_mails
            else:
                print(f"正在筛选 {selected_date} 的邮件...")
                date_mails = [mail for mail in all_mails if MailCrawler.is_date_mail(mail, selected_date)]
                logger.info(f"{selected_date} 的邮件数量: {len(date_mails)} / {len(all_mails)}")
                all_mails = date_mails

        # 获取邮件内容（如果用户需要）
        if all_mails and not args.no_content:
            print(f"\n正在获取邮件内容（最多 {args.max_content} 封）...")
            max_content = min(args.max_content, len(all_mails))
            target_mails = all_mails[:max_content]

            # 优先使用 Playwright 批量读取邮件正文
            pw_bodies = MailCrawler.get_mail_content_playwright(username, password, target_mails)

            content_mails = []
            for i, mail in enumerate(target_mails):
                mail_id = mail.get('id', '')
                body = pw_bodies.get(mail_id, '')
                mail['content'] = body
                mail['body'] = body
                content_mails.append(mail)
                if body:
                    print(f"  获取邮件 {i+1}/{max_content}: {mail.get('subject', '无标题')} ({len(body)}字)")

            # 如果获取了部分邮件的内容，保留其他邮件的元数据
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
            # 中文整理总结邮件内容
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

            # 一段话总结（AI 或关键词模式）
            ai_result = None
            if args.ai:
                print(f"\n正在调用 AI 分类总结...")
                ai_result = MailCrawler.ai_classify_and_summarize(all_mails, api_key, api_base, ai_model)

            if ai_result and ai_result.get('summary'):
                print(f"\n【邮件总结】")
                print(f"{ai_result['summary']}")
            else:
                summary_date = selected_date if not search_keyword else None
                summary = MailCrawler.generate_summary(all_mails, summary_date)
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

                    # 显示关键信息
                    time_str = mail.get('time', mail.get('date', '未知时间'))
                    read_status = '已读' if mail.get('read', True) else '未读'

                    print(f"     时间：{time_str}")
                    print(f"     状态：{read_status}")

                    # 显示邮件正文预览（如果已获取）
                    body = mail.get('body', '')
                    if body:
                        # 清除多余空格，显示完整内容
                        preview = ' '.join(body.split())
                        if preview:
                            print(f"     内容：{preview}")

                    # 显示附件信息（如果已获取）
                    attachments = mail.get('attachments', [])
                    if attachments:
                        attach_names = [attach.get('name', '未命名') for attach in attachments]
                        print(f"     附件：{', '.join(attach_names)}")

            # 分类总结
            print(f"\n【分类总结】")

            if ai_result and ai_result.get('categories'):
                # AI 分类模式
                for category, indices in ai_result['categories'].items():
                    print(f"  * {category}：{len(indices)} 封")
                    for idx in indices:
                        if 0 <= idx < len(all_mails):
                            mail = all_mails[idx]
                            print(f"    - {mail.get('subject', '无标题')}")
            else:
                # 关键词分类模式
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

                # 计算其他类别
                other_count = len(all_mails) - sum(category_counts.values())
                if other_count > 0:
                    category_counts['其他'] = other_count

                # 输出分类统计
                for category, count in category_counts.items():
                    print(f"  * {category}：{count} 封")

            # 建议和提醒
            print(f"\n【建议和提醒】")

            # 检查未读邮件
            unread_mails = [mail for mail in all_mails if not mail.get('read', True)]
            if unread_mails:
                print(f"  [注意] 有 {len(unread_mails)} 封未读邮件需要处理")

            # 检查重要邮件（包含紧急、重要等关键词）
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

            # 附件提醒（如果已获取附件信息）
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
        # 保留服务器会话（不调用logout），下次运行可直接复用
        crawler.logout(keep_session=True)


if __name__ == "__main__":
    main()