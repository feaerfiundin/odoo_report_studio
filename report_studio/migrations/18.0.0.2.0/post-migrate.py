# -*- coding: utf-8 -*-
"""18.0.0.2.0: il menu Stampa diventa una scelta esplicita (in_print_menu).

Prima ogni report attivo era nel menu Stampa: i report che lo erano ci restano.
"""


def migrate(cr, version):
    cr.execute("""
        UPDATE rs_report r
           SET in_print_menu = TRUE
          FROM ir_act_report_xml a
         WHERE a.id = r.action_id AND a.binding_model_id IS NOT NULL
    """)
