import re

from .staff_i18n import normalize_ui_language, static_ui_pairs


_TEXT_NODE_CACHE = {}
_ATTR_CACHE = {}


def _patterns(language):
    language=normalize_ui_language(language)
    cached=_TEXT_NODE_CACHE.get(language)
    if cached is not None:
        return cached,_ATTR_CACHE[language]

    text_patterns=[]
    attr_patterns=[]
    for source,target in static_ui_pairs(language):
        escaped=re.escape(source)
        # Exact rendered text nodes only; do not replace arbitrary substrings.
        text_patterns.append((
            re.compile(r'(?<=>)(?P<lead>\s*)'+escaped+r'(?P<trail>\s*)(?=<)'),
            target,
        ))
        # Exact values only for common UI attributes.
        attr_patterns.append((
            re.compile(
                r'(?P<prefix>\b(?:placeholder|title|aria-label|alt|value)\s*=\s*)(?P<q>["\'])'
                + escaped +
                r'(?P=q)'
            ),
            target,
        ))

    _TEXT_NODE_CACHE[language]=tuple(text_patterns)
    _ATTR_CACHE[language]=tuple(attr_patterns)
    return _TEXT_NODE_CACHE[language],_ATTR_CACHE[language]


def localize_html_exact(html, language):
    language=normalize_ui_language(language)
    if language == 'fa' or not html:
        return html

    # Protect script/style/textarea/pre/code blocks: these can contain dynamic
    # user data or JavaScript strings and must never be mass-translated.
    protected=[]
    block_re=re.compile(
        r'<(?P<tag>script|style|textarea|pre|code)\b[^>]*>.*?</(?P=tag)>',
        flags=re.IGNORECASE|re.DOTALL,
    )
    def protect(match):
        token=f'__GL_I18N_PROTECTED_{len(protected)}__'
        protected.append(match.group(0))
        return token

    output=block_re.sub(protect,html)
    text_patterns,attr_patterns=_patterns(language)

    for pattern,target in text_patterns:
        output=pattern.sub(lambda m: f"{m.group('lead')}{target}{m.group('trail')}",output)

    for pattern,target in attr_patterns:
        output=pattern.sub(lambda m: f"{m.group('prefix')}{m.group('q')}{target}{m.group('q')}",output)

    for idx,block in enumerate(protected):
        output=output.replace(f'__GL_I18N_PROTECTED_{idx}__',block)
    return output


class StaticUiLocalizationMiddleware:
    """Exact-match fallback for remaining legacy Persian UI copy.

    Explicit gl_t/gl_choice translations remain the primary mechanism. This
    middleware only translates known complete text nodes and UI attributes,
    and deliberately avoids scripts, styles, textareas, pre/code, JSON, APIs,
    and arbitrary user-entered substrings.
    """

    def __init__(self,get_response):
        self.get_response=get_response

    def __call__(self,request):
        response=self.get_response(request)
        language=getattr(request,'ui_language','fa')
        if normalize_ui_language(language) == 'fa':
            return response

        content_type=(response.get('Content-Type') or '').lower()
        if 'text/html' not in content_type:
            return response
        if getattr(response,'streaming',False):
            return response
        if response.status_code >= 400:
            return response

        try:
            charset=response.charset or 'utf-8'
            html=response.content.decode(charset)
            localized=localize_html_exact(html,language)
            if localized != html:
                response.content=localized.encode(charset)
                if response.has_header('Content-Length'):
                    response['Content-Length']=str(len(response.content))
        except (UnicodeDecodeError,UnicodeEncodeError,AttributeError):
            return response
        return response
