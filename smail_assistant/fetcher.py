"""Playwright 浏览器自动化获取邮件正文"""

import json
import logging
import os
from typing import List, Dict

from tqdm import tqdm

logger = logging.getLogger(__name__)


def get_mail_content_playwright(username: str, password: str,
                                mail_list: List[Dict],
                                session_file: str = '.session_cache.json') -> Dict[str, str]:
    """
    通过 Playwright 浏览器自动化批量获取邮件正文。

    优先复用已缓存的会话（SID + cookies），避免重复登录触发 2FA。

    Args:
        username: 邮箱用户名
        password: 邮箱密码
        mail_list: 邮件元数据列表（含 id, subject 等字段）
        session_file: 会话缓存文件路径

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

    # 尝试从缓存加载会话
    cached_sid = None
    cached_cookies = None
    if os.path.exists(session_file):
        try:
            with open(session_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if data.get('username') == username:
                cached_sid = data.get('sid')
                cached_cookies = data.get('cookies', {})
                logger.info(f"从缓存加载会话，SID: {cached_sid[:8]}...")
        except Exception as e:
            logger.warning(f"加载缓存会话失败: {e}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # 如果有缓存 cookies，注入到浏览器上下文
        if cached_cookies:
            cookies_for_ctx = [
                {'name': k, 'value': v, 'domain': 'mail.nudt.edu.cn', 'path': '/'}
                for k, v in cached_cookies.items()
            ]
            ctx = browser.new_context(ignore_https_errors=True)
            ctx.add_cookies(cookies_for_ctx)
        else:
            ctx = browser.new_context(ignore_https_errors=True)

        page = ctx.new_page()

        # 确定使用的 SID
        sid = cached_sid

        if sid:
            # 先尝试用缓存 SID 访问邮箱主页，验证会话是否有效
            page.goto(f'https://mail.nudt.edu.cn/coremail/XT/index.jsp?sid={sid}',
                       wait_until='networkidle')
            # 测试 API 是否可用
            test_js = '''async (args) => {
                var resp = await fetch('/coremail/XT/jsp/readMessage.jsp?sid=' + args.sid, {
                    method: 'POST',
                    body: 'mid=test&mode=html',
                    headers: {'Content-Type': 'application/x-www-form-urlencoded'}
                });
                try { await resp.json(); return {ok: true}; }
                catch(e) { return {ok: false, status: resp.status}; }
            }'''
            test = page.evaluate(test_js, {'sid': sid})
            if not test.get('ok'):
                logger.warning("缓存会话已失效，需要重新登录")
                sid = None

        if not sid:
            # 需要重新登录（回退到程序化登录）
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
                logger.error("Playwright 登录失败（可能需要 2FA），请先用 --browser-login 手动登录")
                browser.close()
                return result
            logger.info(f"Playwright 登录成功")
            page.goto(f'https://mail.nudt.edu.cn/coremail/XT/index.jsp?sid={sid}',
                       wait_until='networkidle')

        logger.info(f"使用 SID: {sid[:8]}... 读取邮件正文")

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

        for mail in tqdm(mail_list, desc="读取邮件正文", unit="封"):
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
