"""Official text-only Responses adapter with explicit paid approval and a cost ledger."""
import os
import math
import re
import time
from pathlib import Path

import httpx

from .core import count_payload,worst_cost,fingerprint


class ApprovalRequired(RuntimeError):pass


class OpenAIText:
    def __init__(self,approved=False,budget_usd=0,max_calls=0,transport=None):
        self.approved=approved;self.budget_usd=budget_usd;self.max_calls=max_calls
        self.key=None;self.spent_ceiling=0.0;self.completed_cost=0.0;self.calls=0;self.count_calls=0
        self.last_latency=None
        self.count_cache={}
        self.client=httpx.Client(base_url='https://api.openai.com/v1/',timeout=180,follow_redirects=False,transport=transport)

    def _guard(self):
        if not self.approved or not math.isfinite(self.budget_usd) or self.budget_usd<=0 or self.max_calls<=0:
            raise ApprovalRequired('Explicit user approval, positive cost cap and call limit required before any API request')
        self.key=os.getenv('OPENAI_API_KEY')
        if not self.key:raise ApprovalRequired('OPENAI_API_KEY is not configured locally; do not paste it into chat')

    def _post(self,path,payload):
        self._guard()
        try:
            response=self.client.post(path,json=payload,headers={'Authorization':'Bearer '+self.key})
            if response.status_code>=400:
                # Avoid retaining any invalid-key message that can echo key fragments.
                raise RuntimeError(f'OpenAI HTTP {response.status_code}; request_id={response.headers.get("x-request-id","unavailable")}')
            return response.json()
        except httpx.HTTPError as exc:
            raise RuntimeError(type(exc).__name__+' during API request; no automatic retry or spend') from None

    def count_input(self,request):
        self._guard()
        key=fingerprint(count_payload(request))
        if key in self.count_cache:return self.count_cache[key]
        if self.count_calls>=self.max_calls*20:raise ApprovalRequired('Input-token count request limit exhausted')
        result=self._post('responses/input_tokens',count_payload(request))
        self.count_calls+=1
        self.count_cache[key]=result['input_tokens']
        return self.count_cache[key]

    def generate(self,request,input_tokens=None):
        from .core import enforce_budget
        self._guard()
        # Obtain exact count for this immutable request even if caller passed an estimate.
        counted=self.count_input(request)
        enforce_budget(counted,request['max_output_tokens'])
        reservation=worst_cost(counted,request['max_output_tokens'])
        if self.calls>=self.max_calls or self.spent_ceiling+reservation>self.budget_usd:
            raise ApprovalRequired('Approved request count or conservative token-cost cap exhausted')
        # Reserve before network: an uncertain timeout remains reserved; never retry automatically.
        self.calls+=1;self.spent_ceiling+=reservation
        tick=time.perf_counter();raw=self._post('responses',request);self.last_latency=time.perf_counter()-tick
        usage=raw.get('usage',{})
        if 'input_tokens' in usage and 'output_tokens' in usage:
            self.completed_cost+=worst_cost(usage['input_tokens'],usage['output_tokens'])
        return raw

    def ledger(self):
        return {'generation_requests':self.calls,'input_count_requests':self.count_calls,
                'reserved_token_cost_usd':self.spent_ceiling,'reported_uncached_rate_cost_usd':self.completed_cost,
                'approved_token_cost_cap_usd':self.budget_usd,'automatic_retries':0,
                'note':'Conservative standard text token rates; no cached discount assumed. Billing/tax and count endpoint fees are not independently measured.'}
