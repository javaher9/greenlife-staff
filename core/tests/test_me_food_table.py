import copy
from django.test import Client
from core.me_food_table import CATALOG, food_table
from core.me_diet_models import MeMealReport
from core.me_sync_models import MeDailyAward
from core.tests.test_me_diet import MeDietTests


class MeFoodTableTests(MeDietTests):
    def table(self, items=None):
        return {'version': CATALOG['version'], 'items': items or [{'id': 'rice', 'servings': 1}, {'id': 'chicken', 'servings': 1}]}

    def submit(self, key='lunch', revision=0, **changes):
        body=dict(action='meal', key=key, status='planned', revision=revision, consumed=True, table=self.table())
        body.update(changes)
        return self.post(**body)

    def test_calculations_use_reference_and_preserve_unknowns(self):
        t=food_table(self.table())
        self.assertAlmostEqual(t['kcal'],205/158*100+142/86*100,places=2)
        self.assertAlmostEqual(t['glKnown'],73*(45-.6)/158,places=2)
        self.assertEqual(t['glMissing'],0)
        pizza=food_table(self.table([{'id':'pizza','servings':2}]))
        self.assertEqual(pizza['kcal'],280)
        self.assertIsNone(pizza['items'][0]['gl'])
        self.assertEqual(pizza['glMissing'],1)

    def test_invalid_inputs_never_persist(self):
        for q in [True, '1', float('nan'), float('inf'), -.25, 0, 4.25, 1.1]:
            self.assertEqual(self.submit(table=self.table([{'id':'rice','servings':q}])).status_code,400)
        for table in [{'version':'old','items':[]},self.table([{'id':'unknown','servings':1}]),self.table([{'id':'rice','servings':1}]*2),{**self.table(),'kcal':0}]:
            self.assertEqual(self.submit(table=table).status_code,400)
        self.assertEqual(self.submit(consumed=False).status_code,400)
        self.assertEqual(self.submit(status='skipped').status_code,400)
        self.assertEqual(MeMealReport.objects.count(),0)
        self.assertEqual(MeDailyAward.objects.count(),0)

    def test_second_device_revision_and_snapshot_survive_catalog_changes(self):
        self.assertEqual(self.submit().status_code,200)
        second=Client();session=second.session;session.update(self.client.session);session.save()
        record=next(m for m in second.get(self.url).json()['meals'] if m['key']=='lunch')['report']
        self.assertEqual(record['table']['items'][0]['grams'],100)
        self.assertEqual(record['revision'],1)
        self.assertEqual(Client().get(self.url).status_code,401)
        original=copy.deepcopy(record['table'])
        self.assertEqual(self.submit().status_code,409)
        self.assertEqual(self.post(action='meal',key='lunch',revision=1,status='partial',note='تغییر گزارش').status_code,200)
        self.assertEqual(MeMealReport.objects.get().food_table,original)
        self.assertEqual(self.post(action='meal',key='lunch',revision=2,status='skipped').status_code,200)
        self.assertEqual(MeMealReport.objects.get().food_table,{})

    def test_heart_award_only_for_complete_day_and_never_twice(self):
        for key in ['breakfast','lunch','dinner']:
            self.assertEqual(self.submit(key=key).status_code,200)
            self.assertEqual(MeDailyAward.objects.count(),0)
        self.assertEqual(self.submit(key='snacks',status='replacement').status_code,200)
        self.assertEqual(MeDailyAward.objects.count(),1)
        self.assertEqual(self.submit(key='snacks').status_code,409)
        self.assertEqual(self.submit(key='snacks',revision=1).status_code,200)
        self.assertEqual(MeDailyAward.objects.count(),1)
