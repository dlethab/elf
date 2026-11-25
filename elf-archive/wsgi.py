"""Production entry point:  gunicorn --workers 3 --bind 127.0.0.1:8000 wsgi:app"""
from elf_archive import create_app

app = create_app()
