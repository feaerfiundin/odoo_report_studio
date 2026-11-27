# Copyright 2026 feaerfiundin
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import api, fields, models
from odoo.exceptions import AccessError

RS_MANAGER = "report_studio.group_rs_manager"

# Roles from the highest to the lowest: each group implies the next ones
# (implied_ids).
RS_ROLES = [
    ("manager", "report_studio.group_rs_manager"),
    ("editor", "report_studio.group_rs_editor"),
    ("viewer", "report_studio.group_rs_viewer"),
    ("user", "report_studio.group_rs_user"),
]

# Name of the field holding the user groups in this Odoo version.
GROUPS_FIELD = "groups_id"


class ResUsers(models.Model):
    _inherit = "res.users"

    report_studio_role = fields.Selection(
        selection=[
            ("none", ""),
            ("user", "User"),
            ("viewer", "Viewer"),
            ("editor", "Editor"),
            ("manager", "Administrator"),
        ],
        string="Report Studio",
        compute="_compute_report_studio_role",
        inverse="_inverse_report_studio_role",
        help="Report Studio role. Empty = no access.",
    )

    def _rs_role_groups(self):
        """{role: group} from the highest to the lowest, existing groups only."""
        roles = {}
        for role, xmlid in RS_ROLES:
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if group:
                roles[role] = group
        return roles

    @api.depends(GROUPS_FIELD)
    def _compute_report_studio_role(self):
        roles = self._rs_role_groups()
        for user in self:
            user_groups = user[GROUPS_FIELD]
            user.report_studio_role = next(
                (role for role, group in roles.items() if group in user_groups), "none"
            )

    def _inverse_report_studio_role(self):
        roles = self._rs_role_groups()
        rs_group_ids = {group.id for group in roles.values()}
        for user in self:
            # Remove every Report Studio group, then add only the group of the
            # chosen role: the lower roles come from implied_ids.
            commands = [(3, gid) for gid in rs_group_ids & set(user[GROUPS_FIELD].ids)]
            group = roles.get(user.report_studio_role)
            if group:
                commands.append((4, group.id))
            if commands:
                user.write({GROUPS_FIELD: commands})

    def write(self, vals):
        """Only the Report Studio Administrator can change Report Studio roles."""
        if (
            GROUPS_FIELD not in vals
            or self.env.su
            or self.env.user.has_group("base.group_system")
            or self.env.user.has_group(RS_MANAGER)
        ):
            return super().write(vals)

        rs_group_ids = {group.id for group in self._rs_role_groups().values()}
        before = {user.id: set(user[GROUPS_FIELD].ids) & rs_group_ids for user in self}
        result = super().write(vals)
        for user in self:
            if (set(user[GROUPS_FIELD].ids) & rs_group_ids) != before[user.id]:
                raise AccessError(
                    self.env._(
                        "Only a Report Studio Administrator can change "
                        "Report Studio roles."
                    )
                )
        return result
