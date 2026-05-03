"""邮件爬取与发送工具 — NUDT 邮箱（Coremail XT 系统）"""

import sys
import warnings
from bs4 import XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# 强制使用UTF-8编码输出，避免Windows GBK编码导致中文乱码
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

# 配置日志
import logging
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

from .crawler import MailCrawler
from .cli import main

__all__ = ['MailCrawler', 'main']
