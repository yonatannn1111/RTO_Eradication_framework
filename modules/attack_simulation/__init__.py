"""Attack simulation package."""

from .attacks import (
    attack_timer, attack_counter, attack_flag, run_attacks,
)
from .variants import (
    TimerAttack, CounterAttack, FlagAttack,
    ATTACK_REGISTRY, get_attack_class,
)
from .logger import get_attack_logger, read_log_tail

__all__ = [
    # one-shot
    "attack_timer", "attack_counter", "attack_flag", "run_attacks",
    # persistent
    "TimerAttack", "CounterAttack", "FlagAttack",
    "ATTACK_REGISTRY", "get_attack_class",
    # logging
    "get_attack_logger", "read_log_tail",
]