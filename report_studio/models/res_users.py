# -*- coding: utf-8 -*-
from odoo import _, models
from odoo.exceptions import AccessError

RS_MANAGER = "report_studio.group_rs_manager"
RS_PRIVILEGE = "report_studio.privilege_report_studio"


class ResUsers(models.Model):
    _inherit = "res.users"

    def _rs_group_ids(self):
        """Id dei gruppi che compongono il privilegio Report Studio."""
        privilege = self.env.ref(RS_PRIVILEGE, raise_if_not_found=False)
        if not privilege:
            return set()
        return set(self.env["res.groups"].search([("privilege_id", "=", privilege.id)]).ids)

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
