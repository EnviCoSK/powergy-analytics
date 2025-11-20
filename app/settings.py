import os

DATABASE_URL = os.getenv('DATABASE_URL')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
KYOS_URL = os.getenv('KYOS_URL', 'https://gas.kyos.com/')
APP_BASE_URL = os.getenv('APP_BASE_URL', '')
