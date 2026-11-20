"""Local API credit reconciliation. Never presents local estimates as live billing."""
import json
import math
import os
from pathlib import Path
import tempfile
import time


def credit_root():
    return Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'Pulse Capture'


def read_json(path):
    if path.stat().st_size > 1_000_000:
        raise ValueError('Credit record is too large.')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Credit record must be an object.')
    return value


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def local_requests(root):
    """One event per durable paid attempt; cached reuse creates no new event."""
    root = Path(root)
    requests = {}
    for marker in (root / 'voiceovers').glob('*.attempt'):
        # WAV responses have no billed token usage. Never guess their actual cost.
        requests['speech:' + marker.stem] = None
    for path in (root / 'auto-edit/jobs').glob('*/usage.json'):
        try:
            ledger = read_json(path)
            if ledger.get('status') == 'local_only':
                continue
            usage = ledger.get('measured_usage') or {}
            pricing = ledger.get('quote', {}).get('pricing', {})
            values = [usage.get('input_tokens'), usage.get('output_tokens'),
                      pricing.get('input_usd_per_million'), pricing.get('output_usd_per_million')]
            cost = (values[0]*values[2]+values[1]*values[3])/1_000_000 if all(number(v) for v in values) else None
            requests['plan:' + path.parent.name] = cost
        except (OSError, ValueError, TypeError, AttributeError):
            requests['plan:' + path.parent.name] = None
    return requests


class CreditCounter:
    def __init__(self, root=None):
        self.root = Path(root) if root else credit_root()
        self.path = self.root/'api-credit-counter.json'

    def reconcile(self, balance_usd):
        if not number(balance_usd) or balance_usd > 1_000_000:
            raise ValueError('Enter a finite USD balance between 0 and 1,000,000.')
        state = {'balance_usd':balance_usd, 'checked_at':time.time(),
                 'included_requests':sorted(local_requests(self.root)), 'version':1}
        self.root.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='credits-', suffix='.tmp', dir=self.root)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump(state, handle, indent=2)
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def summary(self):
        requests = local_requests(self.root)
        state = read_json(self.path) if self.path.is_file() else {}
        baseline = set(state.get('included_requests', []))
        new = {key:value for key,value in requests.items() if key not in baseline}
        spent = sum(value for value in new.values() if value is not None)
        unknown = sum(value is None for value in new.values())
        balance = state.get('balance_usd')
        if balance is not None and not number(balance):
            raise ValueError('Saved credit balance is invalid. Check it against OpenAI billing.')
        remaining = balance-spent if balance is not None and not unknown else None
        return {'remaining_estimate_usd':remaining, 'last_balance_usd':balance,
                'estimated_spend_usd':spent, 'unpriced_requests':unknown,
                'requests_since_check':len(new), 'checked_at':state.get('checked_at')}
