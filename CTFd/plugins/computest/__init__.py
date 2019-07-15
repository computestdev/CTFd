"""
This plugin implements customizations for the Computest challenge site.

Customizations include:

    * Restrict viewing of team listing to admin.
    * Restrict viewing of public team page to admin or owner.
    * Restrict viewing of user listing to admin.
    * Restrict viewing of public user page to admin or owner.
    * Make team/user display on scoreboard opt-in. When the site is in team
      mode, only the team captain can change this setting.
    * Show score per category on the scoreboard.
    * Make the teams/users on the scoreboard non-clickable.
    * A custom "notifying" challenge type, which sends an email notification of
      every solve attempt. The email address to which notifications should be
      sent can be configured from the admin panel.
    * Only display non-hidden teams/users on the scoreboard graph. This is
      partially implemented by overriding the core standings function because
      the APIs can't be overridden using a plugin.
    * Link to the Preferences page from Settings page (implemented in the
      Computest theme).
    * Remove the OAuth button from the login form.
    * Add a "Register an account" link to the login form.
    * Remove the OAuth button from the registration form.
"""

from CTFd import plugins

from CTFd.plugins.computest.challenges import NotifyingChallenge
from CTFd.plugins.computest import views


def load(app):
    """Load the plugin."""

    # Create database tables.
    app.db.create_all()

    # Register the notifying challenge type.
    plugins.register_plugin_assets_directory(
        app, base_path='/plugins/computest/assets/')
    plugins.challenges.CHALLENGE_CLASSES['notifying'] = NotifyingChallenge

    # Modify existing routes.
    app.view_functions['scoreboard.listing'] = views.scoreboard_listing
    app.view_functions['teams.listing'] = views.teams_listing
    app.view_functions['teams.public'] = views.teams_public
    app.view_functions['users.listing'] = views.users_listing
    app.view_functions['users.public'] = views.users_public
