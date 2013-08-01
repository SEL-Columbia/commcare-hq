from dimagi.utils.decorators.memoized import memoized
from sqlagg.columns import *
from django.utils.translation import ugettext as _, ugettext_noop
from corehq.apps.reports.datatables import DataTablesHeader, DataTablesColumn
from corehq.apps.reports.sqlreport import SqlTabularReport, DatabaseColumn, SqlData, DataTabulator
from corehq.apps.reports.standard import CustomProjectReport, DatespanMixin
from corehq.apps.users.util import user_id_to_username


HF_MONTHLY_REPORT = [
    {
        'section': ugettext_noop('Home Visits'),
        'columns': [
            'home_visits_pregnant',
            'home_visits_postpartem',
            'home_visits_newborn',
            'home_visits_children',
            'home_visits_other',
            'home_visits_total',
        ]
    },

    {
        'section': ugettext_noop('RDT'),
        'columns': [
            "rdt_positive_children",
            "rdt_positive_adults",
            "rdt_others",
            "rdt_total",
        ]
    },

    {
        'section': ugettext_noop('Diagnosed Cases'),
        'columns': [
            "diagnosed_malaria_child",
            "diagnosed_malaria_adult",
            "diagnosed_diarrhea",
            "diagnosed_ari",
            "diagnosed_total",
        ]
    },

    {
        'section': ugettext_noop('Treated Cases'),
        'columns': [
            "treated_malaria",
            "treated_diarrhea",
            "treated_ari",
            "treated_total",
        ]
    },

    {
        'section': ugettext_noop('Transfers'),
        'columns': [
            "transfer_malnutrition",
            "transfer_incomplete_vaccination",
            "transfer_danger_signs",
            "transfer_prenatal_consult",
            "transfer_missing_malaria_meds",
            "transfer_other",
            "transfer_total",
        ]
    },

    {
        'section': ugettext_noop('Deaths'),
        'columns': [
            "deaths_newborn",
            "deaths_children",
            "deaths_mothers",
            "deaths_other",
            "deaths_total",
        ]
    },
    {
        'section': ugettext_noop('Health Education'),
        'columns': [
            "heath_ed_talks",
            "heath_ed_participants",
        ]
    },
]

def transpose(columns, data):
    return [[column.data_tables_column.html] + [r[i] for r in data] \
            for i, column in enumerate(columns)]

class Section(SqlData):
    """
    A way to represent sections in a report. I wonder if we should genericize/pull this out.
    """
    def __init__(self, report, section_def):
        self.report = report
        self.section_def = section_def

    def __getattribute__(self, item):
        if item in ['table_name', 'group_by', 'filters', 'filter_values', 'keys']:
            return getattr(self.report, item)
        return super(Section, self).__getattribute__(item)

    def title(self):
        return self.section_def['section']

    @property
    @memoized
    def columns(self):
        return [DatabaseColumn(slug, SumColumn('%s_total' % slug)) for slug in self.section_def['columns']]

    @property
    @memoized
    def rows(self):
        raw_data = list(DataTabulator(self).tabulate())
        ret = transpose(self.columns, raw_data)
        return ret

class HeathFacilityMonthly(SqlTabularReport, CustomProjectReport, DatespanMixin):

    exportable = True
    emailable = True
    slug = 'hf_monthly'
    name = "Health Facility Monthly Report"
    table_name = "mc-inscale_MalariaConsortiumFluff"

    report_template_path = "mc/reports/sectioned_tabular.html"
    fields = ['corehq.apps.reports.fields.DatespanField']

    @property
    def filters(self):
        return ["domain = :domain", "date between :startdate and :enddate"]


    @property
    def group_by(self):
        return ['user_id']

    @property
    def filter_values(self):
        return dict(domain=self.domain,
                    startdate=self.datespan.startdate_param_utc,
                    enddate=self.datespan.enddate_param_utc)

    @property
    @memoized
    def sections(self):
        return [Section(self, section) for section in HF_MONTHLY_REPORT]

    @property
    def columns(self):
        user = DatabaseColumn("User", SimpleColumn("user_id"))
        columns = [user]
        for section in self.sections:
            columns.extend(section.columns)
        return columns

    @memoized
    def user_column(self, user_id):
        return DataTablesColumn(user_id_to_username(user_id))

    @property
    def headers(self):
        return DataTablesHeader(DataTablesColumn(_('Indicator')),
                                *[self.user_column(u['html']) for u in [r[0] for r in self._raw_rows]])

    @property
    @memoized
    def _raw_rows(self):
        return list(super(HeathFacilityMonthly, self).rows)

    @property
    def rows(self):
        # a bit of a hack. rows aren't really rows, but the template knows
        # how to deal with them
        return self.sections