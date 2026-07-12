"""Browser-agent layer (demo-scope).

Drives a SELF-BUILT synthetic payer portal (``browser_agent.portal``) with
Playwright to look up authorization statuses. Everything here is demo-scope:
the portal is a local FastAPI app in this repo populated with synthetic case
data, the agent only ever talks to that local portal, and there is no PHI. This
is not RPA against any real payer website and does not resemble one.
"""
