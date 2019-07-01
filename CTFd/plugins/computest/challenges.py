import cgi
import logging
import smtplib
import sys

from flask import Blueprint

from CTFd import utils
from CTFd.utils.user import get_ip
from CTFd.utils.email import sendmail
from CTFd.models import (
    db,
    Challenges,
    Fails,
    Solves,
    Users,
)
from CTFd.plugins import challenges


MAIL_TEMPLATE_SOLVED = """Hello,

User {user.name} (id: {user.id}) just SOLVED challenge {challenge.name} of category {challenge.category} with key '{key}'.

Regards,
Computest Challenges
"""
MAIL_TEMPLATE_FAILED = """Hello,

User {user.name} (id: {user.id}) just FAILED challenge {challenge.name} of category {challenge.category} with key '{key}'.

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


class NotifyingChallenge(challenges.CTFdStandardChallenge):

    """Challenge type that sends notifications for solves/fails.

    The :meth:`solve` and :meth:`fail` methods are overwritten to send email
    notifications.
    """

    id = "notifying"
    name = "notifying"
    templates = {
        # Copy of /plugins/challenges/assets/create.html but with "type" set to "notifying".
        'create': '/plugins/computest/assets/create.html',
        'update': '/plugins/challenges/assets/update.html',
        'view': '/plugins/challenges/assets/view.html',
    }
    scripts = {
        'create': '/plugins/challenges/assets/create.js',
        'update': '/plugins/challenges/assets/update.js',
        'view': '/plugins/challenges/assets/view.js',
    }
    route = '/plugins/computest/assets/'
    blueprint = Blueprint('standard', __name__, template_folder='templates', static_folder='assets')

    @classmethod
    def solve(cls, user, team, challenge, request):
        data = request.form or request.get_json()
        submission = data['submission'].strip()
        solve = Solves(
            user_id=user.id,
            team_id=team.id if team else None,
            challenge_id=challenge.id,
            ip=get_ip(req=request),
            provided=submission
        )
        db.session.add(solve)
        db.session.commit()
        cls.send_notification(solve)
        db.session.close()

    @classmethod
    def fail(cls, user, team, challenge, request):
        data = request.form or request.get_json()
        submission = data['submission'].strip()
        wrong = Fails(
            user_id=user.id,
            team_id=team.id if team else None,
            challenge_id=challenge.id,
            ip=get_ip(request),
            provided=submission
        )
        db.session.add(wrong)
        db.session.commit()
        cls.send_notification(wrong)
        db.session.close()

    @classmethod
    def send_notification(cls, solve):
        if not isinstance(solve, (Fails, Solves)):
            raise TypeError(
                "expected a Solves or Fails instance, got {!r}".format(solve))

        challenge = Challenges.query.get(solve.challenge_id)
        user = Users.query.get(solve.user_id)

        if isinstance(solve, Fails):
            cls.send_email(MAIL_TEMPLATE_FAILED.format(
                key=solve.provided, challenge=challenge, user=user))
        elif isinstance(solve, Solves):
            cls.send_email(MAIL_TEMPLATE_SOLVED.format(
                key=solve.provided, challenge=challenge, user=user))

    @staticmethod
    def send_email(text):
        to_address = utils.get_config('challenge_notification_address')

        # Mail is sent using `utils.email.sendmail`, which currently uses
        # `MIMEText` to wrap the message, so HTML escaping is not necessary,
        # but we escape it anyways since this may change if CTFd code is
        # updated.
        text_escaped = cgi.escape(text)

        if to_address is None:
            logger.error(
                "failed to send email notification because "
                "challenge_notification_address is not set")
            return

        sent = False
        try:
            sent = sendmail(to_address, text_escaped)

        except smtplib.SMTPException:
            logger.exception(
                "an exception occurred while trying to send email notification")

        if not sent:
            logger.warning("failed to send email notification")
