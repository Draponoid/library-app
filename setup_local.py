"""First-run setup: random secrets, no overwriting existing configuration."""
from pathlib import Path
import secrets

root = Path(__file__).resolve().parent
env = root / '.env'
if env.exists():
    raise SystemExit('.env уже существует. Файл не изменён.')
librarian, reader = secrets.token_urlsafe(14), secrets.token_urlsafe(14)
text = (root / '.env.example').read_text(encoding='utf-8')
text = text.replace('replace-with-a-random-string-at-least-32-characters', secrets.token_hex(32))
text = text.replace('ChangeMe-Library-2026!', librarian).replace('ChangeMe-Reader-2026!', reader)
env.write_text(text, encoding='utf-8')
from app import create_app, seed_demo
try:
    seed_demo(create_app())
except Exception:
    print('Конфигурация .env создана, но инициализация базы не завершена. Проверьте сообщение ниже.')
    raise
print('Приложение готово. Сохраните учётные данные из .env:')
print('Библиотекарь: librarian / ' + librarian)
print('Читатель: reader / ' + reader)
