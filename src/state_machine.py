"""Pure agent state machine. No AWS calls.

States: ACTIVE, SUSPENDED (with cooldown_until), KILLED.
  ACTIVE    -> SUSPENDED  when a detection rule fires
  SUSPENDED -> ACTIVE     lazily, on the next request after cooldown
  any       -> KILLED     on a 2nd detection within 24h of the last suspension
                          (real agents only; demo agents are exempt)
  any       -> KILLED     manual kill
  any       -> ACTIVE     manual resume (resets violation history)
"""
from dataclasses import dataclass
from typing import Optional

ACTIVE, SUSPENDED, KILLED = "ACTIVE", "SUSPENDED", "KILLED"


@dataclass
class Gate:
    """Result of checking an agent's status before doing any work."""
    allowed: bool
    http_status: int = 200
    reason: str = ""
    retry_after_s: int = 0
    reactivate: bool = False   # SUSPENDED and cooldown over -> write ACTIVE


def gate(agent, now):
    status = agent.get("status", ACTIVE)
    if status == KILLED:
        return Gate(False, 403, "agent_killed")
    if status == SUSPENDED:
        until = int(agent.get("cooldown_until", 0))
        if now < until:
            return Gate(False, 403, "agent_suspended", retry_after_s=until - int(now))
        return Gate(True, reactivate=True)
    return Gate(True)


@dataclass
class Transition:
    new_status: str
    action: str                     # SUSPENDED | KILLED | RESUMED
    cooldown_until: int = 0
    last_suspended_at: Optional[int] = None


def on_detection(agent, now, limits):
    """Decide what happens when a detection rule fires for an agent."""
    is_demo = bool(agent.get("demo"))
    last = agent.get("last_suspended_at")
    escalate = (
        not is_demo
        and last is not None
        and now - int(last) < limits["escalation_window_s"]
    )
    if escalate:
        return Transition(KILLED, "KILLED", 0, int(now))
    cooldown = limits["demo_cooldown_s"] if is_demo else limits["cooldown_s"]
    return Transition(SUSPENDED, "SUSPENDED", int(now) + int(cooldown), int(now))


def manual_kill(now):
    return Transition(KILLED, "KILLED", 0)


def manual_resume(now):
    return Transition(ACTIVE, "RESUMED", 0)
