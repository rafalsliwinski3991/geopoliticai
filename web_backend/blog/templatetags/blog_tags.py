"""The `render_markdown` filter for the blog template layer.

Posts are author-only (every post is edited exclusively through the admin),
so the rendered HTML is trusted into the page with `mark_safe`. That trust
has exactly one author and one input channel; if the blog ever gains a
second author, the plan's sanitization requirement kicks in (§3 unit 12).
"""

from __future__ import annotations

import json
from django.core.serializers.json import DjangoJSONEncoder
import markdown

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

_JSON_ESCAPES = {ord("<"): "\\u003C", ord(">"): "\\u003E", ord("&"): "\\u0026"}

register = template.Library()


@register.filter
def render_markdown(body: str) -> str:
    # mark_safe is the plan-sanctioned trust for author-only posts; the
    # docstring states the single-author boundary that keeps it true.
    body_html = markdown.markdown(body, output_format="html")
    return mark_safe(body_html)


@register.filter
def jsonld(value: dict) -> str:
    # Django's `json_script` only emits type="application/json"; this is the
    # same escaping, so a post title cannot close the script element.
    payload = json.dumps(value, cls=DjangoJSONEncoder).translate(_JSON_ESCAPES)
    return format_html('<script type="application/ld+json">{}</script>', mark_safe(payload))
