from CTFd import plugins

from CTFd.plugins.computest.challenges import NotifyingChallenge
from CTFd.plugins.computest.views import (
    disable_teams, scoreboard_by_category, define_routes)


def load(app):
    # Create plugin tables.
    app.db.create_all()

    # Disable teams list.
    disable_teams()

    # Display scores per category on scoreboard.
    scoreboard_by_category(app)

    # Register the notifying challenge type.
    plugins.register_plugin_assets_directory(
        app, base_path='/plugins/computest/assets/')
    plugins.challenges.CHALLENGE_CLASSES['notifying'] = NotifyingChallenge

    # Add custom routes.
    define_routes(app)
