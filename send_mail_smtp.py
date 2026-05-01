"""通过 SMTP 发送邮件 - mail.nudt.edu.cn"""
import smtplib
import getpass
from email.mime.text import MIMEText
from datetime import datetime

SMTP_HOST = "mail.nudt.edu.cn"
SMTP_PORT = 25

username = input("请输入邮箱用户名: ").strip()
password = getpass.getpass("请输入邮箱密码: ").strip()

TO = input("请输入收件人: ").strip()
SUBJECT = datetime.now().strftime("%Y-%m-%d")
BODY = "hello"

msg = MIMEText(BODY, "plain", "utf-8")
msg["From"] = username
msg["To"] = TO
msg["Subject"] = SUBJECT

server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15)
server.ehlo()
server.login(username, password)
server.sendmail(username, [TO], msg.as_string())
server.quit()

print(f"邮件已发送: {SUBJECT} → {TO}")
