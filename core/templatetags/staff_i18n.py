from django import template

from core.staff_i18n import translate, translate_choice, translate_country_name

register = template.Library()


@register.simple_tag(takes_context=True)
def gl_t(context, key, **kwargs):
    request = context.get('request')
    language = getattr(request, 'ui_language', context.get('ui_language', 'fa'))
    return translate(key, language, **kwargs)


@register.simple_tag(takes_context=True)
def gl_choice(context, namespace, value, fallback=''):
    request = context.get('request')
    language = getattr(request, 'ui_language', context.get('ui_language', 'fa'))
    return translate_choice(namespace, value, language, fallback=fallback)



@register.simple_tag(takes_context=True)
def gl_country_name(context, country):
    request = context.get('request')
    language = getattr(request, 'ui_language', context.get('ui_language', 'fa'))
    return translate_country_name(country, language)
