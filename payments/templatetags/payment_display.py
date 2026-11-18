"""Consistent names for payment participants without changing user records."""

from django import template

from payments.history import display_name


register = template.Library()


@register.filter
def payment_person(user):
    return display_name(user)
