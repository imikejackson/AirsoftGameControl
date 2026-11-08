"""Timer: just the game clock, for games the boxes don't run (fabric-flag King
of the Hill, objective games, ...). No box logic and no scoring; the field
speaker's callouts and reminders (announcer.py) carry the game."""
from . import Mode


class Timer(Mode):
    name = "timer"
    label = "Timer"
