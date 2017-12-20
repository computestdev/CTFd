import cgi
import logging
import smtplib
import sys

from CTFd import utils
from CTFd.models import db, Teams, Solves, Challenges, Keys, WrongKeys
from CTFd.plugins import challenges

from CTFd.plugins.computest.models import NotifyingChallenges


MAIL_TEMPLATE_SOLVED = """Hello,

User {team.name} (id: {team.id}) just SOLVED challenge {challenge.name} of category {challenge.category} with key '{flag}'.

Regards,
Computest Challenges
"""
MAIL_TEMPLATE_FAILED = """Hello,

User {team.name} (id: {team.id}) just FAILED challenge {challenge.name} of category {challenge.category} with key '{flag}'.

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

        # Mail is sent using `utils.sendmail`, which currently uses `MIMEText`
        # to wrap the message, so HTML escaping is not necessary, but we escape
        # it anyways since this may change if CTFd code is updated.
        text_escaped = cgi.escape(text)

        if to_address is None:
            logger.error(
                "failed to send email notification because "
                "challenge_notification_address is not set")
            return

        sent = False
        try:
            sent = utils.sendmail(to_address, text_escaped)

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
        db.session.commit()
        cls.send_notification(solve)
        db.session.close()

    @classmethod
    def fail(cls, team, chal, request):
        provided_key = request.form['key'].strip()
        wrong = WrongKeys(teamid=team.id, chalid=chal.id,
                          ip=utils.get_ip(request), flag=provided_key)

        db.session.add(wrong)
        db.session.commit()
        cls.send_notification(wrong)
        db.session.close()
