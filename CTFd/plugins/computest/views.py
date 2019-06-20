import os

from flask import (
    abort,
    current_app as app,
    jsonify,
    redirect,
    render_template,
    render_template_string,
    request,
    session,
    url_for,
)

from CTFd import utils, teams, users
from CTFd.models import db, Solves, Awards
from CTFd.utils import config
from CTFd.utils.plugins import override_template
from CTFd.utils.decorators import admins_only, authed_only
from CTFd.utils.decorators.visibility import check_score_visibility
from CTFd.utils.user import get_current_user, get_current_team, is_admin
from CTFd.utils.helpers import get_errors

from CTFd.plugins.computest.utils import get_standings, get_standings_per_category
from CTFd.plugins.computest.models import AccountScoreVisibility


DIR_PATH = os.path.dirname(os.path.realpath(__file__))


@check_score_visibility
def scoreboard_listing():
    """Render scores per category on scoreboard."""
    standings = get_standings()
    standings_per_category = get_standings_per_category()
    template = os.path.join(
        DIR_PATH, 'templates/scoreboard_by_category.html')

    return render_template_string(
        open(template).read(),
        standings=standings,
        standings_per_category=standings_per_category,
        score_frozen=config.is_scoreboard_frozen())


def teams_listing():
    """Restrict viewing of team listing to admin."""
    if not is_admin():
        abort(404)

    return teams.listing()


def teams_public(team_id):
    """Restrict viewing of public team page to admin or owner."""
    current_team = get_current_team()
    if not is_admin() and team_id != current_team.id:
        abort(404)

    return teams.public(team_id)


def users_listing():
    """Restrict viewing of user listing to admin."""
    if not is_admin():
        abort(404)

    return users.listing()


def users_public(user_id):
    """Restrict viewing of public user page to admin or owner."""
    current_user = get_current_user()
    if not is_admin() and user_id != current_user.id:
        abort(404)

    return users.public(user_id)


class ScoreboardList:
    """Unmodified copy of :meth:`api.v1.scoreboard.ScoreboardList`.

    This uses the local modified :meth:`get_standings` so that banned and
    hidden users are not displayed.
    """
    # TODO: Find out how to overwrite API endpoints.
    # See https://github.com/CTFd/CTFd/issues/1042


"""Define custom routes."""


@app.route('/user/preferences', methods=['GET'])
@authed_only
def profile_preferences():
    """View for displaying profile preferences."""
    if config.is_teams_mode():
        account_word = 'team'
        account = get_current_team()
    else:
        account_word = 'username'
        account = get_current_user()

    if config.is_teams_mode() and account is None:
        abort(403)

    visible = (
        db.session.query(AccountScoreVisibility.visible)
        .filter_by(account_id=account.id)
        .scalar()
    )

    if visible is None:
        visible = False

    template = os.path.join(DIR_PATH, 'templates/preferences.html')

    return render_template_string(
        open(template).read(),
        nonce=session.get('nonce'),
        visible=visible,
        success=False,
        account=account_word)

@app.route('/user/preferences', methods=['POST'])
@authed_only
def profile_preferences_submit():
    """View for submitting profile preferences."""
    template = os.path.join(DIR_PATH, 'templates/preferences.html')
    errors = get_errors()
    visible = request.form.get('visible') == 'on'
    current_user = get_current_user()
    current_team = get_current_team()

    if config.is_teams_mode():
        account_word = 'team'
        account = current_team
    else:
        account_word = 'username'
        account = current_user

    if config.is_teams_mode():
        if current_team is None:
            abort(403)

        if current_team.captain_id != current_user.id:
            errors.append('Only the team captain can change this setting')

            return render_template_string(
                open(template).read(),
                nonce=session.get('nonce'),
                visible=visible,
                success=False,
                errors=errors,
                account=account_word)

    visibility = (
        AccountScoreVisibility.query
        .filter_by(account_id=account.id)
        .first()
    )

    if visibility is None:
        if config.is_teams_mode():
            visibility = AccountScoreVisibility(
                team_id=account.id,
                visible=visible)
        else:
            visibility = AccountScoreVisibility(
                user_id=account.id,
                visible=visible)

        db.session.add(visibility)
    else:
        visibility.visible = visible

    db.session.commit()
    db.session.close()

    return render_template_string(
        open(template).read(),
        nonce=session.get('nonce'),
        visible=visible,
        success=True,
        account=account_word)

@app.route('/admin/computest', methods=['GET'])
@admins_only
def admin_computest():
    """View for displaying admin preferences for the Computest plugin."""
    challenge_notification_address = utils.get_config(
        'challenge_notification_address') or ''

    template = os.path.join(DIR_PATH, 'templates/admin_computest.html')

    return render_template_string(
        open(template).read(),
        nonce=session.get('nonce'),
        challenge_notification_address=challenge_notification_address,
        success=False)

@app.route('/admin/computest', methods=['POST'])
@admins_only
def admin_computest_submit():
    """View for submitting admin preferences for the Computest plugin."""
    utils.set_config(
        'challenge_notification_address',
        request.form.get('challenge_notification_address', None))

    challenge_notification_address = utils.get_config(
        'challenge_notification_address') or ''

    template = os.path.join(DIR_PATH, 'templates/admin_computest.html')

    return render_template_string(
        open(template).read(),
        nonce=session.get('nonce'),
        challenge_notification_address=challenge_notification_address,
        success=True)
