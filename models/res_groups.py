from odoo import api, fields, models
import logging

_logger = logging.getLogger(__name__)


class ResGroups(models.Model):
    _inherit = "res.groups"

    # ---------- computed counters ----------
    x_menu_count = fields.Integer(compute="_compute_x_counts", store=False, string="Menus")
    x_view_count = fields.Integer(compute="_compute_x_counts", store=False, string="Views")
    x_access_right_count = fields.Integer(compute="_compute_x_counts", store=False, string="Access Rights")
    x_rule_count = fields.Integer(compute="_compute_x_counts", store=False, string="Record Rules")
    x_restriction_count = fields.Integer(compute="_compute_x_counts", store=False, string="Restrictions")

    # ---------- helpers ----------

    def _get_user_field(self):
        """Trả về tên field user trên res.groups (tuỳ Odoo version)."""
        for fname in ("users", "user_ids"):
            if fname in self._fields:
                return fname
        return None

    def _groups_field_name(self, model_name: str) -> str:
        """Trả về tên field groups trên model tương ứng."""
        Model = self.env[model_name]
        for fname in ("groups_id", "groups_ids", "group_ids"):
            if fname in Model._fields:
                return fname
        return ""

    def _get_all_groups(self):
        """Return this group + every group it implies, recursively."""
        self.ensure_one()
        all_groups = self
        queue = self
        while queue:
            queue = queue.mapped("implied_ids") - all_groups
            all_groups |= queue
        return all_groups

    def _visible_domain_for_groups_field(self, field_name, group_ids):
        """Domain trả về record visible với everyone (no groups) HOẶC giao với groups."""
        if not field_name:
            return [("id", "=", -1)]
        return ["|", (field_name, "=", False), (field_name, "in", group_ids)]

    def _get_visible_menu_ids(self, groups):
        """
        Trả về list ids của menu thực sự visible:
        - groups field trống (public) => visible
        - groups field giao với groups => visible
        - Toàn bộ parent chain cũng phải visible (realistic check)
        Dùng chung cho cả _compute_x_counts lẫn action_show_x_menus
        để đảm bảo số đếm = số record hiển thị trong list view.
        """
        Menu = self.env["ir.ui.menu"].sudo()
        field_name = self._groups_field_name("ir.ui.menu")
        if not field_name:
            return []

        candidates = Menu.search(
            self._visible_domain_for_groups_field(field_name, groups.ids)
        )

        cand_set = set(candidates.ids)
        by_id = {m.id: m for m in candidates}

        def parent_chain_ok(menu):
            p = menu.parent_id
            while p:
                if p.id not in cand_set:
                    return False
                p = by_id.get(p.id, p).parent_id
            return True

        return candidates.filtered(parent_chain_ok).ids

    def _get_all_member_users(self):
        """
        Lấy toàn bộ user thuộc recordset này,
        bao gồm user thuộc các group trong implied chain.
        """
        all_groups = self.env["res.groups"]
        for g in self:
            all_groups |= g._get_all_groups()

        if not all_groups:
            return self.env["res.users"]

        user_field = self._get_user_field()
        if not user_field:
            return self.env["res.users"]

        return all_groups.mapped(user_field)

    # ---------- counters ----------

    def _compute_x_counts(self):
        for rec in self:
            groups = rec._get_all_groups()

            # MENUS: dùng _get_visible_menu_ids để count = list view
            rec.x_menu_count = len(rec._get_visible_menu_ids(groups))

            # VIEWS
            view_field = rec._groups_field_name("ir.ui.view")
            rec.x_view_count = rec.env["ir.ui.view"].sudo().search_count(
                rec._visible_domain_for_groups_field(view_field, groups.ids)
            ) if view_field else 0

            # ACCESS RIGHTS
            rec.x_access_right_count = rec.env["ir.model.access"].sudo().search_count(
                [("group_id", "in", groups.ids)]
            )

            # RECORD RULES
            rec.x_rule_count = rec.env["ir.rule"].sudo().search_count(
                [("groups", "in", groups.ids)]
            )

            # RESTRICTIONS: fields bị restrict mà group KHÔNG có quyền xem
            fields_restricted = rec.env["ir.model.fields"].sudo().search(
                [("groups", "!=", False)]
            )
            group_ids_set = set(groups.ids)
            rec.x_restriction_count = sum(
                1 for f in fields_restricted
                if not set(f.groups.ids).intersection(group_ids_set)
            )

    # ---------- buttons ----------

    def action_show_x_menus(self):
        self.ensure_one()
        groups = self._get_all_groups()
        # Dùng chính xác cùng logic với _compute_x_counts → count khớp list
        visible_menu_ids = self._get_visible_menu_ids(groups)

        action = self.env.ref("user_role_management.action_group_menus").read()[0]
        action["domain"] = [("id", "in", visible_menu_ids)]
        action["views"] = [(False, "list"), (False, "form")]
        return action

    def action_show_x_views(self):
        self.ensure_one()
        groups = self._get_all_groups()
        field_name = self._groups_field_name("ir.ui.view")
        domain = (
            self._visible_domain_for_groups_field(field_name, groups.ids)
            if field_name
            else [("id", "=", -1)]
        )
        action = self.env.ref("user_role_management.action_group_views").read()[0]
        action["domain"] = domain
        action["views"] = [(False, "list"), (False, "form")]
        return action

    def action_show_x_access_rights(self):
        self.ensure_one()
        action = self.env.ref("user_role_management.action_group_access_rights").read()[0]
        action["domain"] = [("group_id", "in", self._get_all_groups().ids)]
        action["context"] = {"group_by": "group_id"}
        return action

    def action_show_x_record_rules(self):
        self.ensure_one()
        action = self.env.ref("user_role_management.action_group_record_rules").read()[0]
        action["domain"] = [("groups", "in", self._get_all_groups().ids)]
        action["context"] = {"group_by": "groups"}
        return action

    # ---------- ORM overrides ----------
    def write(self, vals):
        before_users = self._get_all_member_users()

        previous_roles_map = {
            u.id: u._get_role_groups_from_groups(u.group_ids)
            for u in before_users
        }

        # Kiểm tra group này có phải role group không (có privilege_id)
        # và có đang thay đổi implied_ids không
        implied_changed = 'implied_ids' in vals and bool(
            self.filtered(lambda g: g.privilege_id)
        )

        res = super().write(vals)
        self.invalidate_recordset(['implied_ids'])

        after_users = self._get_all_member_users()
        impacted = (before_users | after_users).sudo()

        # User mới được thêm vào group
        new_users = (after_users - before_users).sudo().filtered(
            lambda u: u.active and not u.x_update_additional_rights
        )

        # User có role chính thay đổi
        role_changed_users = impacted.filtered(lambda u:
                                               u.active
                                               and not u.x_update_additional_rights
                                               and u._get_role_groups_from_groups(u.group_ids)
                                               != previous_roles_map.get(u.id, self.env["res.groups"])
                                               )

        # User thuộc role group bị sửa implied_ids
        implied_changed_users = before_users.sudo().filtered(
            lambda u: u.active and not u.x_update_additional_rights
        ) if implied_changed else self.env["res.users"]

        to_sync = role_changed_users | new_users | implied_changed_users

        if to_sync:
            to_sync._sync_by_roles(previous_roles_map=previous_roles_map)

        return res

    @api.model_create_multi
    def create(self, vals_list):
        groups = super().create(vals_list)

        if self.env.context.get("install_mode"):
            return groups

        user_field = self._get_user_field()
        users = groups.mapped(user_field).sudo() if user_field else self.env["res.users"].sudo().browse()

        to_sync = users.filtered(lambda u: u.active and not u.x_update_additional_rights)
        if to_sync:
            to_sync._sync_by_roles()

        return groups