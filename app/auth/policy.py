"""Every permission check lives here (§3). Views call these; nothing else decides access.

Rule D3: only a space's own members edit that space. Webmasters and superadmins get
no override on maker content.
"""


def _ok(user) -> bool:
    return bool(user) and user.is_authenticated and user.is_active


def can_edit_space(user, space) -> bool:
    # Membership only: no webmaster or superadmin override (D3)
    return _ok(user) and space.status in ("draft", "published") and space.id in user.member_space_ids


def can_edit_site(user) -> bool:
    return _ok(user) and (user.is_superadmin or user.has_role("webmaster"))


can_remove_maker = can_edit_site
can_approve_slug = can_edit_site
can_invite = can_edit_site


def can_manage_lifecycle(user) -> bool:  # restore, purge now, postpone, release slug
    return _ok(user) and user.is_superadmin


def can_manage_roles(user) -> bool:
    return _ok(user) and user.is_superadmin


def can_view_audit(user, space=None) -> bool:
    if can_edit_site(user):
        return True
    return space is not None and can_edit_space(user, space)
