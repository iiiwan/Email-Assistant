"""SMTP 邮件发送（支持 SOCKS5 代理 + SSL 回退）"""

import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from typing import List

logger = logging.getLogger(__name__)


def send_mail(to: str, subject: str, body: str,
              username: str, password: str,
              smtp_host: str = 'mail.nudt.edu.cn', smtp_port: int = 25,
              cc: str = '', bcc: str = '',
              is_html: bool = False, priority: int = 3,
              attachments: List[str] = None) -> bool:
    """发送邮件入口"""
    if not username or not password:
        logger.error("发送需要提供用户名和密码")
        return False

    return _send_mail_smtp(
        to=to, subject=subject, body=body,
        cc=cc, bcc=bcc, is_html=is_html, priority=priority,
        attachments=attachments or [],
        username=username, password=password,
        smtp_host=smtp_host, smtp_port=smtp_port,
    )


def _send_mail_smtp(to: str, subject: str, body: str,
                     cc: str = '', bcc: str = '',
                     is_html: bool = False, priority: int = 3,
                     attachments: List[str] = None,
                     username: str = '', password: str = '',
                     smtp_host: str = 'mail.nudt.edu.cn',
                     smtp_port: int = 25) -> bool:
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
                        server = smtplib.SMTP_SSL(smtp_host, 465, timeout=15, context=ctx)
                        logger.info("通过 SOCKS5 代理连接 SMTP (端口465 SSL)")
                    except ImportError:
                        continue
                else:
                    if smtp_port == 465:
                        server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15)
                    else:
                        server = smtplib.SMTP(smtp_host, smtp_port, timeout=15)
                        server.ehlo()
                    logger.info(f"直接连接 SMTP 服务器: {smtp_host}:{smtp_port}")

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
        logger.error(f"无法连接到 SMTP 服务器 {smtp_host}:{smtp_port}")
        print("\n提示：如果开启了代理（如 Clash），请尝试关闭代理后重试。")
    except Exception as e:
        logger.error(f"发送邮件时发生错误: {e}")
        if 'timed out' in str(e).lower() or 'connection' in str(e).lower() or 'refused' in str(e).lower():
            print("\n提示：发送失败可能是代理软件（如 Clash）干扰了 SMTP 连接。")
            print("请尝试：关闭代理，或将 mail.nudt.edu.cn 加入代理的直连规则后重试。")
    return False
