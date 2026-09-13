from django import template

from core.call_center_identity import call_center_display_name

register = template.Library()


@register.filter
def flower_name(value):
    return call_center_display_name(value)
