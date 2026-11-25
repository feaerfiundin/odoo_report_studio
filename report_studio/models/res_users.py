# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import AccessError

RS_MANAGER = "report_studio.group_rs_manager"

# Ruoli dal più alto al più basso: ogni ruolo include i precedenti.
RS_ROLES = [
    ("manager", "report_studio.group_rs_manager"),
    ("editor", "report_studio.group_rs_editor"),
    ("viewer", "report_studio.group_rs_viewer"),
    ("user", "report_studio.group_rs_user"),
]


class ResUsers(models.Model):
    _inherit = "res.users"

    report_studio_role = fields.Selection(
        selection=[
            ("none", ""),
            ("user", "Utente"),
            ("viewer", "Visualizzatore"),
            ("editor", "Editor"),
            ("manager", "Amministratore"),
        ],
        string="Report Studio",
        compute="_compute_report_studio_role",
        inverse="_inverse_report_studio_role",
        help="Ruolo di Report Studio. Vuoto = nessun accesso.",
    )

    def _rs_group_ids(self):
        """Id di tutti i gruppi Report Studio."""
        ids = set()
        for _role, xmlid in RS_ROLES:
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if group:
                ids.add(group.id)
        return ids

    @api.depends("group_ids")
    def _compute_report_studio_role(self):
        for user in self:
            role = "none"
            for name, xmlid in RS_ROLES:
                group = self.env.ref(xmlid, raise_if_not_found=False)
                if group and group in user.group_ids:
                    role = name
                    break
            user.report_studio_role = role

    def _inverse_report_studio_role(self):
        rs_groups = self._rs_group_ids()
        for user in self:
            # Rimuove tutti i gruppi Report Studio, poi aggiunge quelli del ruolo scelto.
            commands = [(3, gid) for gid in rs_groups & set(user.group_ids.ids)]
            role = user.report_studio_role
            if role and role != "none":
                for name, xmlid in RS_ROLES:
                    group = self.env.ref(xmlid, raise_if_not_found=False)
                    if group:
                        commands.append((4, group.id))
                    if name == role:
                        break
            if commands:
                user.write({"group_ids": commands})

    def write(self, vals):
        """Solo l'Amministratore Report Studio può cambiare i ruoli Report Studio."""
        if (
            "group_ids" not in vals
            or self.env.su
            or self.env.user.has_group("base.group_system")
            or self.env.user.has_group(RS_MANAGER)
        ):
            return super().write(vals)

        rs_groups = self._rs_group_ids()
        before = {user.id: set(user.group_ids.ids) & rs_groups for user in self}
        result = super().write(vals)
        for user in self:
            if (set(user.group_ids.ids) & rs_groups) != before[user.id]:
                raise AccessError(
                    _("Solo un Amministratore di Report Studio può modificare i ruoli Report Studio.")
                )
        return result
