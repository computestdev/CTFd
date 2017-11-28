import os

from CTFd.utils import override_template

def disable_teams():
    """Overwrite the teams template to disable the teams list."""
    dir_path = os.path.dirname(os.path.realpath(__file__))
    teams_template = os.path.join(dir_path, 'templates/teams_disabled.html')
    override_template('teams.html', open(teams_template).read())

def load(app):
    disable_teams()
