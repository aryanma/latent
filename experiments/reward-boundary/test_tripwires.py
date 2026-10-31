"""Separate protective-hook self-tests. These are not scoring probes."""
import json
from pathlib import Path
import socket
import run_audit as audit

audit.phase = "guard_self_test"
outcomes = {}

def check(name, operation):
    try:
        operation()
    except audit.ExternalCallBlocked:
        outcomes[name] = "blocked_before_call"
    else:
        raise AssertionError(f"Tripwire did not stop {name}")

check("network_resolution", lambda: socket.getaddrinfo("localhost", 1))
check("communication_model_entrypoint", lambda: audit.communicate_module.generate())
check("nl_model_entrypoint", lambda: audit.nl_module.generate())
check("model_utility_entrypoint", lambda: audit.llm_module.generate())
check("litellm_entrypoint", lambda: audit.litellm.completion())
report = {"scope": "Separate self-tests, not experimental scoring or paid model calls.",
          "outcomes": outcomes, "all_guards_passed": True,
          "blocked_network_attempts": audit.external_attempts,
          "blocked_model_entrypoint_attempts": audit.model_attempts}
path = Path(__file__).resolve().parent / "tripwire-self-test.json"
path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
print(json.dumps(report))
