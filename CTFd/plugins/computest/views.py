import os

from flask import (
    render_template, render_template_string, jsonify, redirect, url_for,
    request, session, abort)

from sqlalchemy.sql.expression import union_all
from sqlalchemy import distinct

from CTFd import utils, views
from CTFd.models import db, Teams, Solves, Awards, Challenges

from CTFd.plugins.computest.models import TeamScoreVisibility


DIR_PATH = os.path.dirname(os.path.realpath(__file__))


def disable_teams():
    """Overwrite the teams template to disable the teams list."""
    teams_template = os.path.join(DIR_PATH, 'templates/teams_disabled.html')
    utils.override_template('teams.html', open(teams_template).read())


def get_standings(category=None, count=None, show_hidden=False):
    """Get scoreboard standings.

    Optionally filtered by challenge/award `category`, and limited to `count`
    users.

    This function was modified from :meth:`CTFd.scoreboard.get_standings`. The
    `admin` agument was removed and the `category` argument was added. The
    `TeamScoreVisibility` model is used to hide teams that don't have
    visibility set to True.
    """
    scores = (
        db.session.query(
            Solves.teamid.label('teamid'),
            db.func.sum(Challenges.value).label('score'),
            db.func.max(Solves.id).label('id'),
            db.func.max(Solves.date).label('date')
        )
        .select_from(Solves)
        .join(Challenges, Challenges.id == Solves.chalid)
        .group_by(Solves.teamid)
    )

    awards = (db.session.query(
            Awards.teamid.label('teamid'),
            db.func.sum(Awards.value).label('score'),
            db.func.max(Awards.id).label('id'),
            db.func.max(Awards.date).label('date')
        )
        .select_from(Awards)
        .group_by(Awards.teamid)
    )

    if category:
        scores = scores.filter(Challenges.category == category)
        awards = awards.filter(Awards.category == category)

    if not show_hidden:
        scores = scores.filter(Challenges.hidden == 0)

    # Filter out solves and awards that are before a specific time point.
    freeze = utils.get_config('freeze')
    if freeze:
        scores = scores.filter(Solves.date < utils.unix_time_to_utc(freeze))
        awards = awards.filter(Awards.date < utils.unix_time_to_utc(freeze))

    # Combine awards and solves with a union. They should have the same amount
    # of columns
    results = union_all(scores, awards).alias('results')

    # Sum each of the results by the team id to get their score.
    sumscores = db.session.query(
        results.columns.teamid.label('teamid'),
        db.func.sum(results.columns.score).label('score'),
        db.func.max(results.columns.id).label('id'),
        db.func.max(results.columns.date).label('date')
    ).group_by(
        results.columns.teamid
    ).subquery()

    # Filters out banned and hidden users.
    # Properly resolves value ties by ID.
    #
    # Different databases treat time precision differently so resolve by the
    # row ID instead.
    standings_query = (
        db.session.query(
            Teams.id.label('teamid'),
            Teams.name.label('name'),
            sumscores.columns.score
        )
        .select_from(Teams)
        .join(sumscores, Teams.id == sumscores.columns.teamid)
        .join(TeamScoreVisibility, Teams.id == TeamScoreVisibility.team)
        .filter(Teams.banned == False)
        .filter(TeamScoreVisibility.visible == True)
        .order_by(
            sumscores.columns.score.desc(),
            sumscores.columns.id
        )
    )

    # Only select a certain amount of users if asked.
    if count is None:
        standings = standings_query.all()
    else:
        standings = standings_query.limit(count).all()

    db.session.close()

    return standings


def get_standings_per_category(count=None):
    """Get scoreboard standings per challenge/award category.

    Optionally limited to `count` users.
    """
    categories = db.session.query(
        distinct(Challenges.category).label('category')
    )

    scores = {}
    for (category,) in categories:
        scores[category] = get_standings(category, count)

    db.session.close()

    return scores


def scoreboard_by_category(app):
    """Overwrite the scoreboard template to group by category."""
    def scoreboard_view():
        if utils.get_config('view_scoreboard_if_authed') and not utils.authed():
            return redirect(url_for('auth.login', next=request.path))

        if utils.hide_scores():
            return render_template(
                'scoreboard.html',
                errors=['Scores are currently hidden'])

        standings = get_standings()
        standings_per_category = get_standings_per_category()
        template = os.path.join(
            DIR_PATH, 'templates/scoreboard_by_category.html')

        return render_template_string(
            open(template).read(),
            standings=standings,
            standings_per_category=standings_per_category,
            score_frozen=utils.is_scoreboard_frozen())

    # Overwrite the view
    app.view_functions['scoreboard.scoreboard_view'] = scoreboard_view


def team(teamid):
    # Don't allow viewing of other teams.
    if not utils.is_admin() and teamid != session.get('id'):
        abort(404)

    return views.team(teamid)


def topteams(count):
    """Unmodified copy of :meth:`scoreboard.topteams`.

    This uses the local modified :meth:`get_standings` so that banned and
    hidden users are not displayed.
    """
    json = {'places': {}}
    if utils.get_config('view_scoreboard_if_authed') and not utils.authed():
        return redirect(url_for('auth.login', next=request.path))
    if utils.hide_scores():
        return jsonify(json)

    if count > 20 or count < 0:
        count = 10

    standings = get_standings(count=count)

    team_ids = [team.teamid for team in standings]

    solves = Solves.query.filter(Solves.teamid.in_(team_ids))
    awards = Awards.query.filter(Awards.teamid.in_(team_ids))

    freeze = utils.get_config('freeze')

    if freeze:
        solves = solves.filter(Solves.date < utils.unix_time_to_utc(freeze))
        awards = awards.filter(Awards.date < utils.unix_time_to_utc(freeze))

    solves = solves.all()
    awards = awards.all()

    for i, team in enumerate(team_ids):
        json['places'][i + 1] = {
            'id': standings[i].teamid,
            'name': standings[i].name,
            'solves': []
        }
        for solve in solves:
            if solve.teamid == team:
                json['places'][i + 1]['solves'].append({
                    'chal': solve.chalid,
                    'team': solve.teamid,
                    'value': solve.chal.value,
                    'time': utils.unix_time(solve.date)
                })
        for award in awards:
            if award.teamid == team:
                json['places'][i + 1]['solves'].append({
                    'chal': None,
                    'team': award.teamid,
                    'value': award.value,
                    'time': utils.unix_time(award.date)
                })
        json['places'][i + 1]['solves'] = sorted(json['places'][i + 1]['solves'], key=lambda k: k['time'])

    return jsonify(json)


def modify_routes(app):
    """Overwrite view functions of existing routes."""
    app.view_functions['views.team'] = team
    app.view_functions['scoreboard.topteams'] = topteams


def define_routes(app):
    """Define custom routes."""

    @app.route('/profile/preferences', methods=['GET'])
    def profile_preferences():
        """View for displaying profile preferences."""
        if not utils.authed():
            return redirect(url_for('auth.login'))

        team_id = session['id']

        if not session.get('nonce'):
            session['nonce'] = utils.sha512(os.urandom(10))

        visible = (
            db.session.query(TeamScoreVisibility.visible)
            .filter_by(team=team_id)
            .scalar()
        )

        if visible is None:
            visible = False

        template = os.path.join(DIR_PATH, 'templates/preferences.html')

        return render_template_string(
            open(template).read(),
            nonce=session.get('nonce'),
            visible=visible,
            success=False)

    @app.route('/profile/preferences', methods=['POST'])
    def profile_preferences_submit():
        """View for submitting profile preferences."""
        if not utils.authed():
            return redirect(url_for('auth.login'))

        team_id = session['id']
        visible = request.form.get('visible') == 'on'

        visibility = TeamScoreVisibility.query.filter_by(team=team_id).first()

        if visibility is None:
            visibility = TeamScoreVisibility(team_id, visible)
            db.session.add(visibility)
        else:
            visibility.visible = visible

        db.session.commit()
        db.session.close()

        template = os.path.join(DIR_PATH, 'templates/preferences.html')

        return render_template_string(
            open(template).read(),
            nonce=session.get('nonce'),
            visible=visible,
            success=True)

    @app.route('/admin/computest', methods=['GET'])
    @utils.admins_only
    def admin_computest():
        """View for displaying admin preferences for the Computest plugin."""
        if not session.get('nonce'):
            session['nonce'] = utils.sha512(os.urandom(10))

        challenge_notification_address = utils.get_config(
            'challenge_notification_address') or ''

        template = os.path.join(DIR_PATH, 'templates/admin_computest.html')

        return render_template_string(
            open(template).read(),
            nonce=session.get('nonce'),
            challenge_notification_address=challenge_notification_address,
            success=False)

    @app.route('/admin/computest', methods=['POST'])
    @utils.admins_only
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
