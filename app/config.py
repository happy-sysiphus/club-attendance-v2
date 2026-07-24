import os

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
NOTION_PARENT_PAGE_ID = os.environ.get("NOTION_PARENT_PAGE_ID", "")
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret")
DB_PATH = os.environ.get("DB_PATH", "attendance.db")
