from CTFd.models import db, Challenges


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
