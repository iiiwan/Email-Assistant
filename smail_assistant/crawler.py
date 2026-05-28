"""MailCrawler 核心类：登录、邮件列表、邮件内容、会话管理"""

import re
import json
import time
import random
import os
import logging
import traceback
from datetime import datetime, date
from typing import List, Dict, Optional

import requests
import urllib3
from urllib3.exceptions import InsecureRequestWarning
from bs4 import BeautifulSoup

from .sender import send_mail
from .utils import save_mails

logger = logging.getLogger(__name__)


def _show_qr_popup(qr_img_path):
    """弹出二维码窗口（不阻塞），返回 root 对象"""
    import tkinter as tk

    root = tk.Tk()
    root.title("邮箱登录 - 扫码验证")
    root.resizable(False, False)
    root.configure(bg="#f5f5f5")

    # 标题栏
    header = tk.Frame(root, bg="#2b5797", height=50)
    header.pack(fill="x")
    header.pack_propagate(False)
    tk.Label(header, text="NUDT 邮箱登录", font=("", 14, "bold"),
             bg="#2b5797", fg="white").pack(expand=True)

    # 提示文字
    tk.Label(root, text="请使用微信扫描下方二维码完成登录",
             font=("", 10), bg="#f5f5f5", fg="#555").pack(pady=(12, 5))

    # 二维码区域（加边框）
    qr_frame = tk.Frame(root, bg="white", bd=2, relief="groove")
    qr_frame.pack(padx=20, pady=5)
    photo = tk.PhotoImage(file=qr_img_path)
    label = tk.Label(qr_frame, image=photo, bg="white")
    label.image = photo
    label.pack(padx=8, pady=8)

    # 底部提示
    tk.Label(root, text="扫码后窗口将自动关闭", font=("", 9),
             bg="#f5f5f5", fg="#999").pack(pady=(5, 12))

    # 窗口居中
    root.update_idletasks()
    w = root.winfo_width()
    h = root.winfo_height()
    x = (root.winfo_screenwidth() - w) // 2
    y = (root.winfo_screenheight() - h) // 2
    root.geometry(f"+{x}+{y}")

    return root


def _poll_login(page, root, result):
    """用 root.after() 在同一线程轮询页面 URL（Playwright 基于 greenlet，不能跨线程）"""
    try:
        url = page.url
        if 'coremail' in url and 'login' not in url.lower() and 'sid=' in url:
            try:
                content = page.content()
                if '收件箱' in content or 'inbox' in content.lower():
                    result['success'] = True
                    root.destroy()
                    return
            except Exception:
                pass
    except Exception:
        pass

    result['poll_count'] = result.get('poll_count', 0) + 1
    if result['poll_count'] < 60:  # 最多 120 秒（每次 2 秒）
        root.after(2000, lambda: _poll_login(page, root, result))
    else:
        root.destroy()


class MailCrawler:
    """邮件爬取器"""

    def __init__(self, base_url: str = "https://mail.nudt.edu.cn", disable_ssl_verify: bool = True,
                 smtp_host: str = "mail.nudt.edu.cn", smtp_port: int = 25):
        self.base_url = base_url
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.session = requests.Session()
        if disable_ssl_verify:
            self.session.verify = False
            urllib3.disable_warnings(InsecureRequestWarning)
            logger.warning("SSL证书验证已禁用，可能存在安全风险")
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
        self.is_logged_in = False
        self.current_sid = None

    def login(self, username: str, password: str, **kwargs) -> bool:
        """登录邮箱系统"""
        try:
            logger.info(f"访问邮箱主页: {self.base_url}")
            response = self._safe_request(self.base_url, method='get')
            if not response:
                logger.error("访问邮箱主页失败")
                return False
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'lxml')

            # 查找包含sid参数的登录表单
            form = None
            for form_candidate in soup.find_all('form'):
                action = form_candidate.get('action', '')
                if 'coremail' in action and 'sid=' in action:
                    form = form_candidate
                    logger.info(f"找到Coremail登录表单: {action}")
                    break

            if not form:
                logger.info("未找到标准Coremail表单，尝试通用选择器")
                for selector in ['form.j-login-form', 'form.u-form', 'form[action*="coremail"]', 'form[action*="index.jsp"]', 'form']:
                    form = soup.select_one(selector)
                    if form:
                        logger.info(f"使用选择器 '{selector}' 找到表单")
                        break

            skip_html_form = False
            if not form:
                logger.warning("未找到HTML表单，尝试从JavaScript中提取登录信息")

                sid = None
                sid_patterns = [
                    r"s:\s*['\"]([A-Za-z0-9]+)['\"]",
                    r"sid=([A-Za-z0-9]+)",
                    r'"sid"\s*:\s*"([A-Za-z0-9]+)"'
                ]
                for pattern in sid_patterns:
                    match = re.search(pattern, response.text)
                    if match:
                        sid = match.group(1)
                        logger.info(f"找到sid: {sid}")
                        break

                if not sid:
                    x_pattern = r"X\s*=\s*\{[^}]*s:\s*['\"]([A-Za-z0-9]+)['\"]"
                    match = re.search(x_pattern, response.text, re.DOTALL)
                    if match:
                        sid = match.group(1)
                        logger.info(f"从X对象中找到sid: {sid}")

                if sid:
                    logger.info(f"使用提取的sid构建登录请求: {sid}")
                    form_action = f"/coremail/index.jsp?cus=1&sid={sid}"
                    form_method = "post"
                    login_data = {
                        'uid': username, 'password': password, 'locale': 'zh_CN',
                        'destURL': '', 'action:login': '', 'nodetect': 'false',
                        'supportLoginDevice': 'true', 'supportDynamicPwd': 'true', 'supportBind2FA': 'true'
                    }
                    skip_html_form = True
                else:
                    logger.error("未找到登录表单和sid")
                    with open('login_debug.html', 'w', encoding='utf-8') as f:
                        f.write(response.text)
                    return False
            else:
                form_action = form.get('action', '')
                form_method = form.get('method', 'post').lower()

            if not skip_html_form:
                login_data = {}
                for input_tag in form.select('input'):
                    name = input_tag.get('name')
                    value = input_tag.get('value', '')
                    input_type = input_tag.get('type', '')
                    input_id = input_tag.get('id', '')
                    if name:
                        if name == 'uid':
                            login_data[name] = username
                        elif name == 'password':
                            login_data[name] = password
                        elif 'user' in name.lower() or 'account' in name.lower() or 'login' in name.lower():
                            login_data[name] = username
                        elif 'pass' in name.lower() or 'pwd' in name.lower():
                            login_data[name] = password
                        elif input_type == 'text' and not value:
                            if input_id in ['uid', 'username', 'user', 'account', 'loginname']:
                                login_data[name] = username
                        elif input_type == 'password':
                            login_data[name] = password
                        elif value:
                            login_data[name] = value

                if 'uid' not in login_data:
                    uid_input = form.select_one('input[name="uid"]')
                    if uid_input:
                        login_data['uid'] = username
                    else:
                        for field in ['username', 'user', 'email', 'account', 'loginname']:
                            if form.select_one(f'input[name="{field}"]'):
                                login_data[field] = username
                                break

                if 'password' not in login_data:
                    password_input = form.select_one('input[name="password"]')
                    if password_input:
                        login_data['password'] = password
                    else:
                        for field in ['pass', 'pwd', 'passwd']:
                            if form.select_one(f'input[name="{field}"]'):
                                login_data[field] = password
                                break

                if not any(key in login_data for key in ['uid', 'username', 'user', 'account']):
                    logger.error("未找到用户名字段")
                    return False
                if not any(key in login_data for key in ['password', 'pass', 'pwd']):
                    logger.error("未找到密码字段")
                    return False

                for field in ['locale', 'destURL', 'action:login']:
                    if field not in login_data:
                        field_input = form.select_one(f'input[name="{field}"]')
                        if field_input:
                            login_data[field] = field_input.get('value', '')

            logger.info(f"登录数据: { {k: '***' if 'pass' in k.lower() else v for k, v in login_data.items()} }")

            if form_action.startswith('http'):
                submit_url = form_action
            elif form_action.startswith('/'):
                submit_url = f"{self.base_url}{form_action}"
            else:
                submit_url = f"{self.base_url}/{form_action}"

            logger.info(f"提交登录请求到: {submit_url}")

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

            response_text = response.text

            # 检查页面成功标识
            if '收件箱' in response_text or 'inbox' in response_text.lower() or 'logout' in response_text.lower():
                self.is_logged_in = True
                sid_match = re.search(r'sid=([A-Za-z0-9]+)', response_text)
                if sid_match:
                    self.current_sid = sid_match.group(1)
                    logger.info(f"提取到SID: {self.current_sid}")
                logger.info("登录成功（页面包含成功标识）")
                return True

            # 检查HTTP重定向
            elif 'location' in response.headers or 'Location' in response.headers:
                redirect_url = response.headers.get('location') or response.headers.get('Location')
                logger.info(f"登录重定向到: {redirect_url}")
                redirect_response = self._safe_request(redirect_url, method='get')
                if not redirect_response:
                    logger.warning("重定向请求失败")
                    return False
                if '收件箱' in redirect_response.text or 'inbox' in redirect_response.text.lower():
                    self.is_logged_in = True
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

            # 检查JavaScript重定向
            elif 'var mainUrl' in response_text and 'coremail/XT/index.jsp?sid=' in response_text:
                logger.info("检测到JavaScript重定向，登录可能成功")
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
                    redirect_url = f"{self.base_url}/coremail/XT/index.jsp?sid={new_sid}"
                    redirect_response = self._safe_request(redirect_url, method='get')
                    if not redirect_response:
                        return False
                    if '收件箱' in redirect_response.text or 'inbox' in redirect_response.text.lower():
                        self.is_logged_in = True
                        self.current_sid = new_sid
                        logger.info("登录成功（通过JavaScript重定向验证）")
                        return True
                    elif '邮箱' in redirect_response.text or 'mail' in redirect_response.text.lower():
                        self.is_logged_in = True
                        self.current_sid = new_sid
                        logger.info("登录成功（页面包含邮箱相关元素）")
                        return True
                return False

            # 检查tokenUid
            elif 'tokenUid' in response_text and 'coremail' in response_text:
                sid_match = re.search(r'sid=([A-Za-z0-9]+)', response_text)
                if sid_match:
                    new_sid = sid_match.group(1)
                    redirect_url = f"{self.base_url}/coremail/XT/index.jsp?sid={new_sid}"
                    redirect_response = self._safe_request(redirect_url, method='get')
                    if redirect_response and ('收件箱' in redirect_response.text or 'inbox' in redirect_response.text.lower() or '邮箱' in redirect_response.text):
                        self.is_logged_in = True
                        self.current_sid = new_sid
                        logger.info("登录成功（通过sid重定向验证）")
                        return True
                if username in response_text:
                    self.is_logged_in = True
                    sid_match = re.search(r'sid=([A-Za-z0-9]+)', response_text)
                    if sid_match:
                        self.current_sid = sid_match.group(1)
                    logger.info(f"登录成功（页面包含用户名: {username}）")
                    return True

            logger.warning("登录可能失败，页面不包含成功标识")
            with open('login_response_debug.html', 'w', encoding='utf-8') as f:
                f.write(response_text)
            return False

        except Exception as e:
            logger.error(f"登录过程中发生错误: {e}")
            logger.error(f"错误详情: {traceback.format_exc()}")
            return False

    def get_mail_list(self, mailbox: str = 'inbox', page: int = 1,
                      target_date: 'date' = None) -> List[Dict]:
        """获取邮件列表（Coremail JSON API）"""
        if not self.is_logged_in:
            logger.error("未登录，请先登录")
            return []
        if not self.current_sid:
            logger.error("未获取到会话ID，请重新登录")
            return []

        try:
            mailbox_map = {'inbox': '1', 'sent': '2', 'draft': '3', 'trash': '4', 'spam': '5'}
            fid = mailbox_map.get(mailbox, '1')

            items_per_page = 50
            start = (page - 1) * items_per_page

            api_url = f"{self.base_url}/coremail/s/json"
            params = {
                'func': 'mbox:listMessages',
                'fid': fid,
                'sid': self.current_sid,
                'start': start,
                'limit': items_per_page
            }

            if target_date:
                date_str = target_date.strftime('%Y%m%d')
                params['startDate'] = date_str
                params['endDate'] = date_str

            logger.info(f"获取邮件列表: 邮箱类型={mailbox}(fid={fid}), 页码={page}, 起始={start}")

            headers = {
                'Referer': f"{self.base_url}/coremail/XT/index.jsp?sid={self.current_sid}",
                'X-Requested-With': 'XMLHttpRequest',
                'Accept': 'application/json, text/javascript, */*; q=0.01'
            }

            response = self._safe_request(api_url, method='get', params=params, headers=headers)
            if not response:
                return []
            response.raise_for_status()

            try:
                data = json.loads(response.text)
            except json.JSONDecodeError as e:
                logger.error(f"JSON解析失败: {e}")
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
                        mail_info['index'] = idx + 1 + start
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
        """解析单个 HTML 邮件元素"""
        try:
            mail_info = {}
            link_elem = mail_elem.select_one('a')
            if link_elem and link_elem.get('href'):
                mail_info['link'] = link_elem['href']
                if not mail_info['link'].startswith('http'):
                    mail_info['link'] = f"{self.base_url}{mail_info['link']}"

            subject_elem = mail_elem.select_one('.subject, .mail-subject, td.subject')
            if subject_elem:
                mail_info['subject'] = subject_elem.get_text(strip=True)

            sender_elem = mail_elem.select_one('.sender, .from, td.from')
            if sender_elem:
                mail_info['sender'] = sender_elem.get_text(strip=True)

            time_elem = mail_elem.select_one('.time, .date, td.date')
            if time_elem:
                mail_info['time'] = time_elem.get_text(strip=True)

            mail_info['read'] = not bool(mail_elem.select('.unread'))
            mail_info['raw_html'] = str(mail_elem)
            return mail_info if mail_info else None
        except Exception as e:
            logger.error(f"解析邮件元素时出错: {e}")
            return None

    def _parse_mail_json(self, raw_mail: Dict) -> Optional[Dict]:
        """解析 JSON 格式的邮件数据"""
        try:
            mail_info = {}
            mail_info['id'] = raw_mail.get('id', '')
            mail_info['fid'] = raw_mail.get('fid', '')
            mail_info['subject'] = raw_mail.get('subject', '无标题')
            mail_info['from'] = raw_mail.get('from', '未知发件人')
            mail_info['sender'] = raw_mail.get('from', '未知发件人')
            mail_info['to'] = raw_mail.get('to', '')
            mail_info['size'] = raw_mail.get('size', 0)

            sent_date = raw_mail.get('sentDate', '')
            received_date = raw_mail.get('receivedDate', '')
            mail_info['sentDate'] = sent_date
            mail_info['receivedDate'] = received_date
            mail_info['modifiedDate'] = raw_mail.get('modifiedDate', '')

            display_date = received_date if received_date else sent_date
            mail_info['time'] = display_date
            mail_info['date'] = display_date

            flags = raw_mail.get('flags', {})
            mail_info['read'] = flags.get('read', True)
            mail_info['flags'] = flags
            mail_info['priority'] = raw_mail.get('priority', 3)
            mail_info['backgroundColor'] = raw_mail.get('backgroundColor', 0)
            mail_info['antiVirusStatus'] = raw_mail.get('antiVirusStatus', '')
            mail_info['label0'] = raw_mail.get('label0', 0)
            mail_info['hmid'] = raw_mail.get('hmid', '')

            if mail_info['id'] and self.current_sid:
                mail_info['link'] = f"{self.base_url}/coremail/s?func=mbox:readMessage&id={mail_info['id']}&sid={self.current_sid}"

            return mail_info
        except Exception as e:
            logger.error(f"解析JSON邮件数据时出错: {e}")
            return None

    def _parse_json_message(self, msg_data: Dict) -> Dict:
        """解析 Coremail JSON API 返回的消息内容"""
        mail_content = {}
        mail_content['subject'] = msg_data.get('subject', '')
        mail_content['from'] = msg_data.get('from', '')
        mail_content['to'] = msg_data.get('to', '')
        mail_content['date'] = msg_data.get('sentDate', msg_data.get('receivedDate', ''))

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

        if not body_text and not body_html:
            body_text = msg_data.get('body', msg_data.get('content', ''))

        if body_html and not body_text:
            soup = BeautifulSoup(body_html, 'lxml')
            for tag in soup(["script", "style"]):
                tag.decompose()
            body_text = soup.get_text(separator='\n', strip=True)

        mail_content['body'] = body_text.strip()
        mail_content['body_html'] = body_html

        attachments = msg_data.get('attach', [])
        if isinstance(attachments, list):
            mail_content['attachments'] = [
                {'name': a.get('name', '未命名'), 'size': a.get('size', 0)}
                for a in attachments
            ]

        return mail_content

    def get_mail_content(self, mail_url: str) -> Optional[Dict]:
        """获取邮件详细内容（Coremail JSON API）"""
        if not self.is_logged_in:
            logger.error("未登录，请先登录")
            return None

        try:
            id_match = re.search(r'[?&]mid=([^&\s]+)', mail_url)
            if not id_match:
                id_match = re.search(r'[?&]id=([^&\s]+)', mail_url)
            mail_id = id_match.group(1) if id_match else None

            api_headers = {
                'Referer': f"{self.base_url}/coremail/XT/index.jsp?sid={self.current_sid}",
                'X-Requested-With': 'XMLHttpRequest',
                'Accept': 'application/json, text/javascript, */*; q=0.01'
            }

            if mail_id and self.current_sid:
                api_url = f"{self.base_url}/coremail/s/json"
                attempts = [
                    ('get', api_url, {'func': 'mbox:readMessage', 'mid': mail_id, 'sid': self.current_sid}),
                    ('get', api_url, {'func': 'mbox:readMessage', 'id': mail_id, 'sid': self.current_sid}),
                    ('post', f"{api_url}?func=mbox:readMessage&sid={self.current_sid}", {'mid': mail_id}),
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

            return {'body': '', 'attachments': []}

        except Exception as e:
            logger.error(f"获取邮件内容时发生错误: {e}")
            return None

    def login_browser(self, username: str, password: str,
                      session_file: str = '.session_cache.json') -> bool:
        """通过 Playwright 浏览器登录，支持 2FA 二次验证（二维码弹窗显示）"""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.error("未安装 playwright，请运行: pip install playwright && playwright install chromium")
            return False

        browser = None
        print("正在启动浏览器登录...")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(ignore_https_errors=True)
                page = ctx.new_page()

                # 访问邮箱主页
                page.goto('https://mail.nudt.edu.cn', wait_until='networkidle')

                # 自动填写用户名和密码
                try:
                    uid_input = page.locator('input[name="uid"]')
                    if uid_input.count() > 0:
                        uid_input.fill(username)
                    pwd_input = page.locator('#fakePassword, input[name="fakePassword"]')
                    if pwd_input.count() > 0:
                        pwd_input.fill(password)
                    logger.info("已自动填写用户名和密码")
                except Exception as e:
                    logger.warning(f"自动填写凭据失败: {e}")

                # 自动点击登录按钮
                try:
                    login_btn = page.locator('button.j-submit, button:has-text("登录")')
                    if login_btn.count() > 0:
                        login_btn.first.click()
                        logger.info("已自动点击登录按钮")
                        page.wait_for_timeout(2000)
                except Exception as e:
                    logger.warning(f"自动点击登录按钮失败: {e}")

                # 检查是否需要二次验证（二维码/动态口令）
                qr_detected = False
                qr_selectors = [
                    '.j-second-auth-wrap:not(.f-dn)',
                    '.QRCode img', '.qrcode img',
                    '.second-auth-wrap img',
                ]
                try:
                    for sel in qr_selectors:
                        elem = page.locator(sel)
                        if elem.count() > 0:
                            qr_detected = True
                            break
                    if not qr_detected:
                        dynamic_pwd = page.locator('input[name="dynamicPwd"]')
                        if dynamic_pwd.count() > 0 and dynamic_pwd.is_visible():
                            qr_detected = True
                except Exception:
                    pass

                if qr_detected:
                    # 从浏览器页面提取二维码，弹窗显示
                    qr_img_path = 'login_qrcode.png'
                    extracted = False
                    try:
                        # 优先用 alt="Scan me!" 定位真正的二维码（避免抓到小图标）
                        qr_img = page.locator('img[alt="Scan me!"]')
                        if qr_img.count() > 0 and qr_img.first.is_visible():
                            qr_img.first.screenshot(path=qr_img_path)
                            extracted = True
                        else:
                            # 兜底：找最大的可见 img 元素
                            best = None
                            best_area = 0
                            for sel in qr_selectors:
                                elem = page.locator(sel)
                                for i in range(elem.count()):
                                    el = elem.nth(i)
                                    if el.is_visible():
                                        box = el.bounding_box()
                                        if box and box['width'] * box['height'] > best_area:
                                            best_area = box['width'] * box['height']
                                            best = el
                            if best:
                                best.screenshot(path=qr_img_path)
                                extracted = True
                    except Exception:
                        pass

                    if extracted:
                        print()
                        print("=" * 55)
                        print("  需要二次验证！请用微信扫描弹出的二维码")
                        print("=" * 55)

                        # 弹窗显示二维码，用 root.after() 同线程轮询（兼容 Playwright greenlet）
                        root = _show_qr_popup(qr_img_path)
                        result = {'success': False}
                        root.after(2000, lambda: _poll_login(page, root, result))
                        root.mainloop()

                        if not result['success']:
                            print("扫码超时，请重试")
                            return False
                    else:
                        print()
                        print("=" * 55)
                        print("  需要二次验证！请在浏览器中扫码登录")
                        print("=" * 55)
                        try:
                            page.wait_for_url("**/coremail/**/*", timeout=120000)
                        except Exception:
                            logger.warning("等待超时")
                else:
                    # 没有 2FA，直接等待跳转
                    try:
                        page.wait_for_url("**/coremail/**/index.jsp?sid=*", timeout=30000)
                    except Exception:
                        try:
                            page.wait_for_url("**/coremail/**/*", timeout=30000)
                        except Exception:
                            logger.warning("等待登录跳转超时")

                # 提取 SID
                current_url = page.url
                sid_match = re.search(r'sid=([A-Za-z0-9]+)', current_url)
                if not sid_match:
                    try:
                        content = page.content()
                        sid_match = re.search(r'sid=([A-Za-z0-9]+)', content)
                    except Exception:
                        pass

                if not sid_match:
                    logger.error("无法从浏览器中提取 SID，登录可能未成功")
                    return False

                self.current_sid = sid_match.group(1)
                logger.info(f"提取到 SID: {self.current_sid}")

                # 提取浏览器 cookies
                cookies = ctx.cookies()
                for cookie in cookies:
                    self.session.cookies.set(cookie['name'], cookie['value'],
                                             domain=cookie.get('domain', ''),
                                             path=cookie.get('path', '/'))

                self.is_logged_in = True

                # 保存会话
                data = {
                    'username': username,
                    'sid': self.current_sid,
                    'cookies': {c['name']: c['value'] for c in cookies},
                    'saved_at': datetime.now().isoformat()
                }
                try:
                    with open(session_file, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False)
                    logger.info(f"会话已缓存到 {session_file}")
                except Exception as e:
                    logger.warning(f"保存会话失败: {e}")

                print("登录成功！")
                return True

        except Exception as e:
            logger.error(f"浏览器登录出错: {e}")
            return False
        finally:
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass

    def send_mail(self, to: str, subject: str, body: str, cc: str = '', bcc: str = '',
                  is_html: bool = False, priority: int = 3,
                  attachments: List[str] = None, username: str = '', password: str = '') -> bool:
        """发送邮件（委托给 sender 模块）"""
        return send_mail(
            to=to, subject=subject, body=body,
            username=username, password=password,
            smtp_host=self.smtp_host, smtp_port=self.smtp_port,
            cc=cc, bcc=bcc, is_html=is_html, priority=priority,
            attachments=attachments,
        )

    def save_mails(self, mails: List[Dict], output_dir: str = 'mails') -> None:
        """保存邮件数据"""
        save_mails(mails, output_dir)

    def logout(self, keep_session: bool = True, session_file: str = '.session_cache.json') -> None:
        """退出登录"""
        if keep_session:
            self.is_logged_in = False
            logger.info("已清除本地登录状态（会话已缓存，下次可直接使用）")
        else:
            try:
                logout_url = f"{self.base_url}/coremail/s/json?func=user:logout&sid={self.current_sid}"
                self.session.get(logout_url, timeout=5)
            except Exception:
                pass
            self.is_logged_in = False
            if os.path.exists(session_file):
                try:
                    os.remove(session_file)
                except Exception:
                    pass
            logger.info("已退出登录并清除会话缓存")

    def save_session(self, username: str, session_file: str = '.session_cache.json') -> None:
        """保存会话到本地文件"""
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
                os.chmod(session_file, 0o600)
            except Exception:
                pass
            logger.info(f"会话已缓存到 {session_file}")
        except Exception as e:
            logger.warning(f"保存会话失败: {e}")

    def load_session(self, username: str, session_file: str = '.session_cache.json',
                     max_age_hours: int = 8) -> bool:
        """从本地文件加载会话，验证有效性"""
        if not os.path.exists(session_file):
            return False
        try:
            with open(session_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if data.get('username') != username:
                logger.info("缓存会话用户名不匹配，将重新登录")
                return False

            saved_at = datetime.fromisoformat(data['saved_at'])
            age_hours = (datetime.now() - saved_at).total_seconds() / 3600
            if age_hours > max_age_hours:
                logger.info(f"缓存会话已超过 {max_age_hours} 小时，将重新登录")
                return False

            for k, v in data.get('cookies', {}).items():
                self.session.cookies.set(k, v)
            self.current_sid = data.get('sid')
            if not self.current_sid:
                return False

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
        """添加随机延迟，避免请求过快被封号"""
        delay = random.uniform(min_seconds, max_seconds)
        logger.debug(f"添加随机延迟: {delay:.2f} 秒")
        time.sleep(delay)

    def _safe_request(self, url: str, method: str = 'get', **kwargs) -> Optional[requests.Response]:
        """安全的请求方法，包含随机延迟和错误处理"""
        try:
            self._random_delay(0.3, 0.8)
            if method.lower() == 'get':
                response = self.session.get(url, **kwargs)
            elif method.lower() == 'post':
                response = self.session.post(url, **kwargs)
            else:
                logger.error(f"不支持的请求方法: {method}")
                return None
            response.raise_for_status()
            time.sleep(random.uniform(0.2, 0.5))
            return response
        except requests.exceptions.RequestException as e:
            logger.error(f"请求失败: {url} - {e}")
            time.sleep(random.uniform(2.0, 3.0))
            return None
        except Exception as e:
            logger.error(f"请求发生未知错误: {url} - {e}")
            return None
