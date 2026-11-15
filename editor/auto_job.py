"""Reusable Auto Edit job orchestration; UI workers and verification use this path."""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path

from .auto_ai import PROMPT_VERSION, build_request, request_plan
from .auto_analysis import analyse, atomic_json, check_cancel, local_plan, read_transcript
from .auto_plan import editor_state, validate_plan


def default_cache():
    return Path(os.environ.get('LOCALAPPDATA', Path.home()))/'Pulse Capture'/'auto-edit'


class AutoJob:
    def __init__(self, backend, media, options, pricing, cache_root=None):
        options.validate()
        pricing.validate()
        self.backend, self.media, self.options, self.pricing = backend, media, options, pricing
        self.cache_root = Path(cache_root) if cache_root else default_cache()
        self.analysis = self.analysis_folder = self.folder = self.request = self.quote = None
        self.transcript, self.transcript_note = [], ''

    def prepare(self, cancel, progress=lambda message: None):
        if self.media.duration < self.options.minimum:
            raise ValueError('Source is shorter than the minimum target duration.')
        self.analysis, self.analysis_folder = analyse(self.backend, self.media, self.cache_root, cancel, progress)
        self.transcript, self.transcript_note = read_transcript(self.media.path, self.media.duration)
        if not self.media.path.with_suffix('.srt').exists():
            from .auto_transcribe import local_transcript
            self.transcript, self.transcript_note = local_transcript(self.media, self.analysis_folder, cancel, progress)
        identity = {'source': self.analysis['digest'], 'options': asdict(self.options),
                    'transcript': self.transcript, 'planner_version': PROMPT_VERSION}
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        self.folder = self.cache_root/'jobs'/digest
        self.folder.mkdir(parents=True, exist_ok=True)
        try:
            self.request, self.quote = build_request(self.analysis, self.analysis_folder, self.transcript,
                                                      self.options, self.pricing)
            self.ai_error = ''
        except ValueError as exc:
            self.request = self.quote = None
            self.ai_error = str(exc)
        return self

    def save_plan(self, plan, mode, usage, cached=False):
        validate_plan(plan, self.media, self.options)
        for short in plan['shorts']:
            editor_state(short, self.media, self.transcript)
        payload = {'version': 1, 'source': str(self.media.path.resolve()), 'source_sha256': self.analysis['digest'],
                   'analysis_file': str(self.analysis_folder/'analysis.json'), 'options': asdict(self.options),
                   'mode': mode, 'plan': plan, 'transcript': self.transcript, 'transcript_note': self.transcript_note,
                   'usage': usage, 'cached_ai_result': cached, 'review_required': True}
        path = self.folder/('ai-plan.json' if mode == 'AI-assisted' else 'local-plan.json')
        atomic_json(path, payload)
        return payload, path

    def local(self, cancel):
        check_cancel(cancel)
        plan = local_plan(self.analysis, self.media, self.options, self.transcript)
        # A local fallback still reports an earlier charged/uncertain API attempt.
        ledger = self.folder/'usage.json'
        usage = json.loads(ledger.read_text(encoding='utf-8')) if ledger.exists() else {
            'status': 'local_only', 'measured_cost_gbp': 0, 'reserved_gbp': 0, 'measured_usage': None}
        return self.save_plan(plan, 'Local-only', usage)

    def ai(self, cancel, key, **kwargs):
        if self.request is None:
            raise ValueError(self.ai_error or 'Analyse the source first.')
        plan, usage, cached = request_plan(self.request, self.quote, self.pricing, self.media,
                                          self.options, self.transcript, self.folder, cancel, key, **kwargs)
        return self.save_plan(plan, 'AI-assisted', usage, cached)
