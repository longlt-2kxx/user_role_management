from odoo import api, fields, models
from odoo.exceptions import UserError
import logging
import threading
_logger = logging.getLogger(__name__)
_sync_local = threading.local()

class ResUsers(models.Model):
    _inherit = "res.users"

    _CTX_SKIP = "skip_roles_sync"
    # Set chứa id của các user đang trong quá trình sync
    # để chặn vòng lặp write() ngược từ ORM Many2many

    x_user_role_ids = fields.Many2many(
        "res.groups",
        relation="res_users_x_role_rel",  # ← tên unique, không trùng với bảng nào
        compute="_compute_x_user_role_ids",
        store=False,
        string="User Role",
    )

    x_update_additional_rights = fields.Boolean(
        string="Update additional rights",
        help="If enabled, user can keep additional groups besides the selected role.",
        default=False,
    )

    allowed_country_ids = fields.Many2many(
        "res.country",
        compute="_compute_allowed_countries",
        store=False,
        string="Allowed Countries",
    )

    def _compute_x_user_role_ids(self):
        priv = self.env.ref(
            "user_role_management.privilege_access_right",
            raise_if_not_found=False,
        )
        for user in self:
            if not priv:
                user.x_user_role_ids = False
                continue
            user.x_user_role_ids = user.group_ids.filtered(
                lambda g: g.privilege_id == priv
            )

    def _compute_allowed_countries(self):
        for user in self:
            user.allowed_country_ids = user.company_ids.mapped("country_id")

    def _all_implied(self, groups):
        implied = self.env["res.groups"]
        stack = groups
        while stack:
            g = stack[0]
            stack -= g
            new = g.implied_ids - implied
            implied |= new
            stack |= new
        return implied

    def _get_role_privilege(self):
        return self.env.ref(
            "user_role_management.privilege_access_right",
            raise_if_not_found=False,
        )

    def _get_role_groups_from_groups(self, groups):
        priv = self._get_role_privilege()
        if not priv:
            return self.env["res.groups"]
        return groups.filtered(lambda g: g.privilege_id == priv)

    def _force_single_user_type(self, groups, prefer_portal=False):
        internal = self.env.ref("base.group_user", raise_if_not_found=False)
        portal = self.env.ref("base.group_portal", raise_if_not_found=False)
        public = self.env.ref("base.group_public", raise_if_not_found=False)

        user_types = self.env["res.groups"]
        for g in (internal, portal, public):
            if g:
                user_types |= g

        groups -= user_types

        chosen = self.env["res.groups"]
        if prefer_portal and portal:
            chosen = portal
        elif internal:
            chosen = internal
        elif portal:
            chosen = portal
        elif public:
            chosen = public

        if chosen:
            groups |= chosen
        return groups

    def _apply_clear_role_baseline(self):
        internal_user = self.env.ref("base.group_user", raise_if_not_found=False)
        admin_group = self.env.ref("base.group_system", raise_if_not_found=False)
        current_company = self.env.company

        for user in self:
            keep = self.env["res.groups"]
            if internal_user:
                keep |= internal_user
            if admin_group and admin_group in user.group_ids:
                keep |= admin_group

            user.with_context(**{self._CTX_SKIP: True}).write({
                "group_ids": [(6, 0, keep.ids)],
                "company_id": current_company.id,
                "company_ids": [(6, 0, [current_company.id])],
            })

    def action_clear_role(self):
        """
        Server action: xoá toàn bộ role của user được chọn,
        giữ lại internal user + admin nếu có.
        """
        for user in self:
            user._apply_clear_role_baseline()

    def _sync_by_roles(self, previous_roles_map=None):
        """
        - Untick: role only
        - Tick: role + additional rights
        previous_roles_map: {user.id: res.groups(recordset role cũ)}
        """
        internal = self.env.ref("base.group_user", raise_if_not_found=False)
        portal = self.env.ref("base.group_portal", raise_if_not_found=False)
        public = self.env.ref("base.group_public", raise_if_not_found=False)
        admin_group = self.env.ref("base.group_system", raise_if_not_found=False)
        priv = self._get_role_privilege()

        if not priv:
            _logger.warning("[SYNC] Missing privilege_access_right")
            return

        previous_roles_map = previous_roles_map or {}

        for user in self:
            if not user.active:
                continue

            is_public = public and public in user.group_ids
            is_internal = internal and internal in user.group_ids
            is_portal = portal and portal in user.group_ids

            # pure anonymous public -> skip
            if is_public and not (is_internal or is_portal):
                continue

            try:
                current_roles = user._get_role_groups_from_groups(user.group_ids)

                # ưu tiên role hiện tại; nếu user làm mất role lúc save thì dùng role cũ kéo lại
                roles = current_roles

                if not roles:
                    user._apply_clear_role_baseline()
                    continue

                # business nên chỉ có 1 role chính
                if len(roles) > 1:
                    _logger.warning(
                        "[SYNC] User %s (%s) has multiple roles: %s — using all",
                        user.login, user.id, roles.mapped("name")
                    )

                implied = user._all_implied(roles)
                role_allowed = roles | implied

                prefer_portal = bool(
                    self.env.context.get("signup")
                    or self.env.context.get("signup_force_type") == "portal"
                )

                role_allowed = user._force_single_user_type(
                    role_allowed,
                    prefer_portal=prefer_portal if not roles else False,
                )

                if public:
                    role_allowed -= public

                if admin_group and admin_group in user.group_ids:
                    role_allowed |= admin_group

                if user.x_update_additional_rights:
                    manual_extra = user.group_ids - roles - implied

                    # bỏ các role group khác
                    manual_extra -= manual_extra.filtered(
                        lambda g: g.privilege_id == priv
                    )

                    # bỏ user type khác và public
                    user_types = self.env["res.groups"]
                    for g in (internal, portal, public):
                        if g:
                            user_types |= g
                    manual_extra -= user_types

                    final_allowed = role_allowed | manual_extra
                else:
                    # untick = role only tuyệt đối
                    final_allowed = role_allowed

                if set(final_allowed.ids) != set(user.group_ids.ids):
                    user.with_context(**{self._CTX_SKIP: True}).write({
                        "group_ids": [(6, 0, final_allowed.ids)]
                    })

            except Exception as e:
                _logger.exception(
                    "[SYNC][ERROR] user=%s (%s) %s", user.login, user.id, e
                )

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        if not self.env.context.get(self._CTX_SKIP):
            users._sync_by_roles()
        return users

    def write(self, vals):
        if self.env.context.get(self._CTX_SKIP):
            return super().write(vals)

        syncing = getattr(_sync_local, 'ids', set())

        users_to_sync = self.filtered(lambda u: u.id not in syncing)

        previous_roles_map = {
            u.id: u._get_role_groups_from_groups(u.group_ids)
            for u in users_to_sync
        }

        res = super().write(vals)

        if users_to_sync:
            if not hasattr(_sync_local, 'ids'):
                _sync_local.ids = set()
            _sync_local.ids.update(users_to_sync.ids)
            try:
                users_to_sync._sync_by_roles(previous_roles_map=previous_roles_map)
            finally:
                _sync_local.ids.difference_update(users_to_sync.ids)

        return res