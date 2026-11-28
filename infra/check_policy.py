"""Reject obvious infrastructure policy violations in tracked files."""
from pathlib import Path
import re
import subprocess
import sys

tracked = subprocess.check_output(['git', 'ls-files', '-z'], text=True).split('\0')
errors = []
for name in filter(None, tracked):
    path = Path(name)
    if name.startswith('infra/secrets/'):
        if not name.endswith('.vault.yml'):
            errors.append(f'{name}: only encrypted *.vault.yml files may be committed')
        elif not path.read_text(encoding='utf-8').startswith('$ANSIBLE_VAULT;'):
            errors.append(f'{name}: expected an encrypted Ansible Vault file')
        continue
    if not name.startswith('infra/') or path.suffix not in ('.yml', '.yaml', '.j2'):
        continue
    text = path.read_text(encoding='utf-8')
    if re.search(r'-----BEGIN (?:[A-Z ]* )?PRIVATE KEY-----', text):
        errors.append(f'{name}: private key detected')
    if re.search(r'(?m)^\s*vault_(?:db_password|secret_key|demo_librarian_password|demo_reader_password|registry_username|registry_token)\s*:\s*\S+', text):
        errors.append(f'{name}: plaintext secret variable detected')
    if re.search(r'(?i)\bimage\s*:\s*[^\n]*:latest\b', text):
        errors.append(f'{name}: latest image forbidden')
    if 'ansible.builtin.shell:' in text:
        errors.append(f'{name}: shell tasks require a reviewed exception')
    if 'ansible.builtin.raw:' in text and name != 'infra/site.yml':
        errors.append(f'{name}: unexpected raw command')
if errors:
    print('\n'.join(errors), file=sys.stderr)
    raise SystemExit(1)
print('Infrastructure policy: OK')
