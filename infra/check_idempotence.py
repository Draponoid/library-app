"""Reject a second Ansible run if any host reports changes or failures."""
import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding='utf-8')
if 'PLAY RECAP' not in text:
    raise SystemExit('Missing play recap')
recap = text.split('PLAY RECAP', 1)[1]
rows = re.findall(r'^\S+\s*:\s+.*?changed=(\d+).*?failed=(\d+)', recap, re.MULTILINE)
if len(rows) != 2 or any(changed != '0' or failed != '0' for changed, failed in rows):
    raise SystemExit(f'Expected two unchanged hosts; recap: {rows}')
print('Idempotence: two hosts unchanged')
