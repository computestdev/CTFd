import logging
import os
import smtplib
import sys

from flask import (
    render_template, render_template_string, redirect, url_for, request,
    session)
from sqlalchemy.sql.expression import union_all
from sqlalchemy import distinct

from CTFd import utils
from CTFd.models import db, Teams, Solves, Awards, Challenges, Keys, WrongKeys
from CTFd.plugins import challenges, register_plugin_assets_directory


DIR_PATH = os.path.dirname(os.path.realpath(__file__))
MAIL_TEMPLATE_SOLVED = """Hello,

User {team.name} (id: {team.id}) just solved challenge {challenge.name} of category {challenge.category} with key '{flag}'.

Regards,
Computest Challenges
"""
MAIL_TEMPLATE_FAILED = """Hello,

User {team.name} (id: {team.id}) just failed challenge {challenge.name} of category {challenge.category} with key '{flag}'.

Regards,
Computest Challenges
"""
STDERR_FORMAT = "ctfd[%(process)d]: %(name)s %(levelname)s: %(message)s"

logger = logging.getLogger('ctfd.plugins.computest')
logger.setLevel(logging.NOTSET)

stderr_handler = logging.StreamHandler(sys.stderr)
stderr_handler.setFormatter(logging.Formatter(STDERR_FORMAT))
stderr_handler.setLevel(logging.INFO)

logger.addHandler(stderr_handler)

# challenge types

class NotifyingChallenge(challenges.CTFdStandardChallenge):

    """Challenge type that sends notifications for solves/fails.

    The :meth:`solve` and :meth:`fail` methods are overwritten to send email
    notifications. The :meth:`create` method is only overwritten so that the
    :class:`NotifyingChallenges` model is used to store challenges.
    """

    id = "notifying"
    name = "notifying"
    templates = {
        'create': '/plugins/computest/assets/notifying-challenge-create.hbs',
        'update': '/plugins/challenges/assets/standard-challenge-update.hbs',
        'modal': '/plugins/challenges/assets/standard-challenge-modal.hbs',
    }
    scripts = {
        'create': '/plugins/challenges/assets/standard-challenge-create.js',
        'update': '/plugins/challenges/assets/standard-challenge-update.js',
        'modal': '/plugins/challenges/assets/standard-challenge-modal.js',
    }

    @staticmethod
    def send_email(text):
        to_address = utils.get_config('challenge_notification_address')
        if to_address is None:
            logger.error(
                "failed to send email notification because "
                "challenge_notification_address is not set")
            return

        sent = False
        try:
            sent = utils.sendmail(to_address, text)

        except smtplib.SMTPException:
            logger.exception(
                "an exception occurred while trying to send email notification")

        if not sent:
            logger.warning("failed to send email notification")

    @classmethod
    def send_notification(cls, solve):
        if not isinstance(solve, (WrongKeys, Solves)):
            raise TypeError("expected a Solves or WrongKeys instance")

        challenge = Challenges.query.get(solve.chalid)
        team = Teams.query.get(solve.teamid)

        if isinstance(solve, WrongKeys):
            cls.send_email(MAIL_TEMPLATE_FAILED.format(
                flag=solve.flag, challenge=challenge, team=team))
        elif isinstance(solve, Solves):
            cls.send_email(MAIL_TEMPLATE_SOLVED.format(
                flag=solve.flag, challenge=challenge, team=team))

    @staticmethod
    def create(request):
        files = request.files.getlist('files[]')

        # Create challenge
        chal = NotifyingChallenges(
            name=request.form['name'],
            description=request.form['desc'],
            value=request.form['value'],
            category=request.form['category'],
            type=request.form['chaltype']
        )

        if 'hidden' in request.form:
            chal.hidden = True
        else:
            chal.hidden = False

        max_attempts = request.form.get('max_attempts')
        if max_attempts and max_attempts.isdigit():
            chal.max_attempts = int(max_attempts)

        db.session.add(chal)
        db.session.commit()

        flag = Keys(chal.id, request.form['key'], request.form['key_type[0]'])
        if request.form.get('keydata'):
            flag.data = request.form.get('keydata')
        db.session.add(flag)

        db.session.commit()

        for f in files:
            utils.upload_file(file=f, chalid=chal.id)

        db.session.commit()

    @classmethod
    def solve(cls, team, chal, request):
        provided_key = request.form['key'].strip()
        solve = Solves(teamid=team.id, chalid=chal.id,
                       ip=utils.get_ip(req=request), flag=provided_key)
        db.session.add(solve)
        cls.send_notification(solve)
        db.session.commit()
        db.session.close()

    @classmethod
    def fail(cls, team, chal, request):
        provided_key = request.form['key'].strip()
        wrong = WrongKeys(teamid=team.id, chalid=chal.id,
                          ip=utils.get_ip(request), flag=provided_key)
        db.session.add(wrong)
        cls.send_notification(wrong)
        db.session.commit()
        db.session.close()


# models


class NotifyingChallenges(Challenges):

    """Define the Challenge model for NotifyingChallenge.

    This is required for NotifyingChallenge to work.
    """

    __mapper_args__ = {
        'polymorphic_identity': 'notifying'
    }


class TeamScoreVisibility(db.Model):

    """Team visibility on scoreboards.

    If `visible` is set to False, the team/user is not displayed on the public
    scoreboard.
    """

    id = db.Column(db.Integer, primary_key=True)
    team = db.Column(db.Integer, db.ForeignKey('teams.id'))
    visible = db.Column(db.Boolean, default=False)

    def __init__(self, team, visible):
        self.team = team
        self.visible = visible


def disable_teams():
    """Overwrite the teams template to disable the teams list."""
    teams_template = os.path.join(DIR_PATH, 'templates/teams_disabled.html')
    utils.override_template('teams.html', open(teams_template).read())


def get_standings(category=None, count=None):
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


def load(app):
    # Create plugin tables.
    app.db.create_all()

    # Disable teams list.
    disable_teams()

    # Display scores per category on scoreboard.
    scoreboard_by_category(app)

    # Register the notifying challenge type.
    register_plugin_assets_directory(app, base_path='/plugins/computest/assets/')
    challenges.CHALLENGE_CLASSES["notifying"] = NotifyingChallenge

    # Add custom routes.
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
