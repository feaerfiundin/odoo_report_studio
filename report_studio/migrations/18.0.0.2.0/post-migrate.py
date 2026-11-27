# Copyright 2026 feaerfiundin
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""18.0.0.2.0: the Print menu becomes an explicit choice (in_print_menu).

Before, every active report was in the Print menu: those reports stay there.
"""


def migrate(cr, version):
    cr.execute(
        """
        UPDATE rs_report r
           SET in_print_menu = TRUE
          FROM ir_act_report_xml a
         WHERE a.id = r.action_id AND a.binding_model_id IS NOT NULL
        """
    )
