"""Opt-in metadata only. Never capture request bodies, headers or storage."""
from urllib.parse import urlsplit


def redact_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
            return '[REDACTED]'
        # Paths may contain names/CPF; query keys themselves may contain tokens.
        return f'{parsed.scheme}://{parsed.hostname}/[REDACTED]'
    except ValueError:
        return '[REDACTED]'


def response_metadata(response):
    request = response.request
    duration = request.timing.get('responseEnd', -1)
    return {'url': redact_url(request.url), 'method': request.method if request.method in {'GET','POST','HEAD','OPTIONS'} else 'OTHER',
            'resource_type': request.resource_type, 'status': response.status,
            'duration_ms': max(-1, duration)}
