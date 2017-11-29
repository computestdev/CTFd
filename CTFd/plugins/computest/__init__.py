import os

from flask import (
    render_template, render_template_string, redirect, url_for, request)
from sqlalchemy.sql.expression import union_all
from sqlalchemy import distinct

from CTFd import utils
from CTFd.models import db, Teams, Solves, Awards, Challenges


DIR_PATH = os.path.dirname(os.path.realpath(__file__))


def disable_teams():
    """Overwrite the teams template to disable the teams list."""
    teams_template = os.path.join(DIR_PATH, 'templates/teams_disabled.html')
    utils.override_template('teams.html', open(teams_template).read())


def get_standings(category=None, count=None):
    """Get scoreboard standigs.

    Optionally filtered by challenge/award `category`, and limited to `count`
    users.

    This function was modified from :meth:`CTFd.scoreboard.get_standings`. The
    `admin` agument was removed and the `category` argument was added.
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

    # Filters out banned users.
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
        .filter(Teams.banned == False)
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
    """Get scoreboard standigs per challenge/award category.

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


def load(app):
    disable_teams()
    scoreboard_by_category(app)
