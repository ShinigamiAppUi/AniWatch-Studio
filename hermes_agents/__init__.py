"""agents - the AniWatch pipeline agents that walk in the office.

Each agent is a plain function wrapped in `base.Agent`, which puts a character
at its desk (`hermes_bridge.bridge`) and reports the steps. The work itself is
deterministic and file/DB based: nothing here depends on the office being up
(ADR-3), so a pipeline run works headless and the characters are a view of it.
"""

__all__ = ['base', 'config', 'inbox', 'kb', 'mailer', 'media', 'moderator', 'ops', 'pipeline',
           'episode_scheduler', 'notifier', 'store', 'support', 'user_report']
