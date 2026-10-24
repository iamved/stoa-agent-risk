"""Policy as code for agents: the ``stoa-policy/0.1`` schema, the shipped
packs, the recommendation engine and the kill switch.

Policies live in ``stoa.policy.toml`` at the repository root and are
evaluated locally by the runtime SDK at tool-call entry (observe first,
enforce per policy). Nothing here calls a network.
"""

from .killswitch import KillSwitch, drill, kill, release  # noqa: F401
from .packs import PACK_NAMES, load_pack  # noqa: F401
from .recommend import recommend  # noqa: F401
from .schema import (  # noqa: F401
    ACTIONS,
    POLICY_SCHEMA,
    TRIGGERS,
    PolicyDocument,
    PolicySpec,
    load_policy_document,
    parse_policy_document,
    policy_to_toml,
    validate_document,
)
