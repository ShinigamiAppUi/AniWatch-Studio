"""agents - the AniWatch pipeline agents that walk in the office.

Each agent is a plain function wrapped in `base.Agent`, which puts a character
at its desk (`hermes_bridge.bridge`) and reports the steps. The work itself is
deterministic and file/DB based: nothing here depends on the office being up
(ADR-3), so a pipeline run works headless and the characters are a view of it.
"""

__all__ = ['analytics', 'base', 'cache_warmer', 'channels', 'config', 'growth_data', 'inbox', 'kb',
           'mailer', 'marketing', 'media', 'moderator', 'ops', 'orchestrator', 'pipeline',
           'episode_scheduler', 'notifier', 'recommendation', 'retention', 'seo', 'social', 'store',
           'support', 'user_report']
