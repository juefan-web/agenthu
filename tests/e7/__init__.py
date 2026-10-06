"""E7 acceptance machinery (M5 P0-7 prep): deterministic seed, pre-registered
manifest and registry-driven verification against a real isolated stack.

Gated by ``AGENTHU_E7_STACK=1``; without the gate the case drivers are not
collected at all, so the regular CI shape is unchanged. The frozen protocol
lives in AGENT_CONTEXT/TASKS/m5-e7-acceptance.md; the stack runbook in this
package's README.md.
"""
