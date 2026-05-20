# -*- coding: utf-8 -*-
{
    "name": "User Roles Management",
    "version": "19.0.1.0.0",
    "category": "Customizations",
    "summary": "A1 Consulting - Jackie: User Roles Management",
    "description": """
    This module provides custom user role management features.

    Main features:
    - Create and manage custom user roles
    - Define role-related access permissions
    - Extend group and action group configurations
    - Support security access control for role-based management

    Developed by A1 Consulting.
    """,
    "author": "A1 Consulting",
    "website": "https://a1consulting.vn",
    "maintainer": "A1 Consulting",
    "license": "LGPL-3",
    "support": "support@a1consulting.vn",
    "depends": [
        "base",
    ],
    "data": [
        # views
        "security/group.xml",
        "security/ir.model.access.csv",
        "views/user_role_views.xml",
        "views/res_groups_views.xml",
        "views/action_group_views.xml",
    ],
    "assets": {},
    "application": False,
    "installable": True,
    "auto_install": False,
}
