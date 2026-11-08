"""Game modes. Each mode is a Mode subclass in its own module.

Adding a mode: subclass Mode in a new module, override the hooks it needs,
and add an instance to ALL below. Every mode keeps its own state as keys in
hub.game (always under hub.game_lock unless a hook says otherwise).
"""


class Mode:
    name = ""        # id used in commands and payloads ("domination", ...)
    label = ""       # shown to people

    def init(self, game):
        """Add this mode's default keys to the game dict (at startup)."""

    def on_select(self, game):
        """The referee switched modes (any mode, idle only): reset round state."""

    def on_start(self, game, active):
        """A new round started. active = this is the selected mode."""

    def on_reset_all(self, game):
        """The referee pressed Reset All."""

    def on_time_up(self, game):
        """The countdown reached 0 in this mode. Return True to keep running."""
        return False

    def tick(self, now, dt):
        """Called every clock tick while this mode is selected. No lock held:
        read boxes first (hub.nodes_lock), then update under hub.game_lock."""

    def after_tick(self):
        """Called every clock tick for EVERY mode (no lock held)."""

    def payload(self, game):
        """Extra fields for the browser game payload (always, any mode)."""
        return {}

    def node_fields(self, p):
        """Extra fields for airsoft/game/state while this mode is selected.
        p is the browser payload."""
        return {}

    def signature(self, game):
        """Values whose change should republish the game state."""
        return ()

    def command(self, action, body):
        """Handle a referee command for this mode. Return a Flask response
        (or (response, status)), or None if the action isn't this mode's."""
        return None


from .domination import Domination  # noqa: E402
from .rush import Rush              # noqa: E402

ALL = [Domination(), Rush()]
BY_NAME = {m.name: m for m in ALL}


def _init():
    from .. import hub
    with hub.game_lock:
        for m in ALL:
            m.init(hub.game)


_init()


def current(name):
    return BY_NAME.get(name, ALL[0])
