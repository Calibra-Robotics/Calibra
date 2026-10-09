"""calibra_ee.plugin — registers Calibra Cloud commands and hooks with the core."""

from __future__ import annotations

from calibra.plugins import PluginRegistry


def _login(argv: list[str]) -> None:
    from calibra_ee.cloud.auth import run_login

    run_login()


def _logout(argv: list[str]) -> None:
    from calibra_ee.cloud.auth import run_logout

    run_logout()


def _whoami(argv: list[str]) -> None:
    from calibra_ee.cloud.auth import run_whoami

    run_whoami()


def _cloud(argv: list[str]) -> None:
    from calibra_ee.cloud.push import run_cloud

    run_cloud(argv)


def register(registry: PluginRegistry) -> None:
    from calibra_ee import community, sync

    registry.add_command("login", _login)
    registry.add_command("logout", _logout)
    registry.add_command("whoami", _whoami)
    registry.add_command("cloud", _cloud)
    registry.outcome_recorded.append(sync.on_outcome_recorded)
    registry.card_pushed.append(community.register_badge)
    registry.badge_url = community.badge_url
