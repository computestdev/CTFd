from sqlalchemy.ext.hybrid import hybrid_property

from CTFd.models import db, Challenges
from CTFd.utils import get_config


class NotifyingChallenges(Challenges):

    """Define the Challenge model for NotifyingChallenge.

    This is required for NotifyingChallenge to work.
    """

    __mapper_args__ = {
        'polymorphic_identity': 'notifying'
    }


class AccountScoreVisibility(db.Model):

    """Account visibility on scoreboards.

    If `visible` is set to False, the team/user is not displayed on the public
    scoreboard.
    """

    __tablename__ = 'account_score_visibility'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'))
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id', ondelete='CASCADE'))
    visible = db.Column(db.Boolean, default=False)

    def __init__(self, *args, **kwargs):
        super(AccountScoreVisibility, self).__init__(**kwargs)

    @hybrid_property
    def account_id(self):
        user_mode = get_config('user_mode')
        if user_mode == 'teams':
            return self.team_id
        elif user_mode == 'users':
            return self.user_id

    def __repr__(self):
        return '<AccountScoreVisibility %r>' % self.id
