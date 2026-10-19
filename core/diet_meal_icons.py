"""Shared meal-slot illustrations for every scheduled diet preview.

The symbols depict meal time, never the prescribed foods. Original media
remains in TreatmentRichMedia for the editor and may be reused later.
"""
from django.templatetags.static import static

MEAL_ICON_NAMES={
    'fasting': 'fasting',
    'breakfast': 'breakfast',
    'snack_am': 'snack-am',
    'pre_lunch': 'pre-lunch',
    'lunch': 'lunch',
    'snack_pm': 'snack-pm',
    'pre_dinner': 'pre-dinner',
    'dinner': 'dinner',
    'bedtime': 'bedtime',
    'pre_suhoor': 'pre-suhoor',
    'suhoor': 'suhoor',
    'iftar': 'iftar',
    'after_iftar': 'after-iftar',
    'other': 'other'
}

def meal_illustration_url(slot):
    return static('core/diet/meal-%s.svg' % MEAL_ICON_NAMES.get(slot, 'other'))
