"""
Browser Exploration Agent.
Executes bounded Playwright sessions, captures state transitions, network events.
Stops at payment/destructive boundaries.
"""
import asyncio
import json
import uuid
from datetime import datetime
from urllib.parse import urlparse
from utils.logger import get_logger
from config import settings
from db.nosql import evidence_col
from services.dynamic.state_exploration import record_state, record_transition
from services.dynamic.network_inspection import record_network_event
from backend.agents.bus import EventBus, EventEnvelope

logger = get_logger(__name__)

# Destructive/payment boundary signals
_PAYMENT_SIGNALS = [
    "payment", "checkout", "buy now", "place order", "submit payment",
    "confirm purchase", "pay now", "complete order", "authorize",
]
_DANGEROUS_ACTIONS = ["delete account", "cancel subscription", "unsubscribe from all", "submit payment"]

def _is_payment_boundary(label: str, url: str) -> bool:
    label_lower = label.lower()
    return any(sig in label_lower for sig in _PAYMENT_SIGNALS)

# Exploration targets per the System Design Document
EXPLORATION_TARGETS = [
    "consent_cookie",       # consent/cookie banners
    "signup_form",          # signup flow (no payment)
    "subscription_disclosure",  # trial/subscription disclosure
    "cancellation_flow",    # cancellation/unsubscribe (observe, do NOT execute)
    "privacy_rights",       # CCPA opt-out, DPDP withdrawal surfaces
]

class BrowserExplorationSession:
    """
    Bounded Playwright exploration session.

    Budgets (from config or defaults):
    - max_actions: 50 per session
    - max_states: 30
    - max_time_seconds: 300
    - allowed_domains: root domain only (unless subdomain traversal enabled)
    """
    def __init__(self, audit_id: str, root_url: str, config: dict, bus: EventBus):
        self.audit_id = audit_id
        self.root_url = root_url
        self.config = config
        self.bus = bus
        self.domain = urlparse(root_url).netloc
        self.max_actions = config.get("max_actions", 50)
        self.max_states = config.get("max_states", 30)
        self.actions_taken = 0
        self.states_visited: set[str] = set()
        self.evidence_collected: list[dict] = []

    async def run(self) -> dict:
        """Run a bounded exploration session. Returns summary."""
        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    viewport={"width": self.config.get("viewport_width", 1366),
                               "height": self.config.get("viewport_height", 768)},
                    record_har_path=None,
                )
                page = await context.new_page()

                # Network interception
                network_events = []
                async def handle_response(response):
                    try:
                        body = await response.body()
                        body_text = body.decode("utf-8", errors="replace")[:5000]
                    except:
                        body_text = ""
                    network_events.append({
                        "url": response.url, "method": response.request.method,
                        "status": response.status,
                        "req_headers": dict(response.request.headers),
                        "resp_headers": dict(response.headers),
                        "body": body_text,
                    })

                page.on("response", lambda r: asyncio.create_task(handle_response(r)) if not r.url.endswith(('.png','.jpg','.css','.js')) else None)

                await page.goto(self.root_url, wait_until="networkidle", timeout=30000)
                initial_state = await self._capture_state(page, parent_state_id=None)

                # Explore consent/cookie banners
                await self._explore_consent(page, initial_state["_id"])

                # Explore privacy rights surfaces
                await self._explore_privacy_rights(page, initial_state["_id"])

                await browser.close()

                # Store network events
                for ne in network_events[:100]:  # limit
                    await record_network_event(
                        self.audit_id, initial_state["_id"],
                        ne["url"], ne["method"], ne["status"],
                        ne["req_headers"], ne["resp_headers"],
                        None, ne["body"],
                    )

                logger.info("Browser session complete",
                            extra={"audit_id": self.audit_id, "states": len(self.states_visited),
                                   "actions": self.actions_taken})
                return {"states": len(self.states_visited), "actions": self.actions_taken,
                        "evidence_count": len(self.evidence_collected)}
        except Exception as exc:
            logger.error("Browser session error", extra={"audit_id": self.audit_id, "error": str(exc)}, exc_info=exc)
            return {"states": 0, "actions": 0, "evidence_count": 0, "error": str(exc)}

    async def _capture_state(self, page, parent_state_id: str | None) -> dict:
        """Capture current page state and record it."""
        url = page.url
        dom = await page.content()
        visible_text = await page.evaluate("() => document.body.innerText")
        cookies = await page.context.cookies()
        screenshot = await page.screenshot(type="png")

        # Upload screenshot
        from db.sql import get_supabase
        state_id = str(uuid.uuid4())
        screenshot_path = f"audits/{self.audit_id}/states/{state_id}/screenshot.png"
        try:
            client = await get_supabase()
            await client.storage.from_("pattern-proof").upload(
                screenshot_path, screenshot,
                file_options={"content-type": "image/png", "upsert": "true"}
            )
            screenshot_uri = f"supabase://pattern-proof/{screenshot_path}"
        except Exception:
            screenshot_uri = ""

        state = await record_state(
            self.audit_id, None, url, dom[:2000], visible_text[:2000],
            [{"name": c["name"]} for c in cookies], {},
            screenshot_uri, "", ""
        )
        self.states_visited.add(state["state_hash"])
        return state

    async def _explore_consent(self, page, current_state_id: str) -> None:
        """Find and interact with consent/cookie banners. Record before/after states."""
        try:
            consent_selectors = [
                "[id*='cookie'] button", "[class*='consent'] button",
                "[id*='consent'] button", "[aria-label*='Accept']",
                "button:has-text('Accept')", "button:has-text('Reject')",
                "button:has-text('Decline')", ".cookie-banner button",
            ]
            for sel in consent_selectors:
                try:
                    el = await page.query_selector(sel)
                    if el and await el.is_visible():
                        label = await el.inner_text() or sel
                        if not _is_payment_boundary(label, page.url):
                            before_state = await self._capture_state(page, current_state_id)
                            await el.click()
                            await page.wait_for_timeout(1000)
                            after_state = await self._capture_state(page, before_state["_id"])
                            await record_transition(
                                self.audit_id, before_state["_id"], after_state["_id"],
                                "click", f"consent: {label}"
                            )
                            self.actions_taken += 1
                            break
                except Exception:
                    continue
        except Exception as exc:
            logger.debug("Consent exploration error", extra={"error": str(exc)})

    async def _explore_privacy_rights(self, page, current_state_id: str) -> None:
        """Look for CCPA/DPDP privacy rights surfaces."""
        try:
            privacy_signals = [
                "Do Not Sell", "opt out", "privacy rights", "data request",
                "right to know", "CCPA", "privacy settings",
            ]
            links = await page.query_selector_all("a, button")
            for el in links[:50]:
                try:
                    text = (await el.inner_text() or "").strip()
                    if any(sig.lower() in text.lower() for sig in privacy_signals) and len(text) < 100:
                        # Record as evidence (observation only, do not click external links)
                        ev_doc = {
                            "_id": str(uuid.uuid4()),
                            "audit_id": self.audit_id,
                            "source": "dynamic",
                            "taxonomy_scope": ["ccpa", "dpdp"],
                            "evidence_type": "privacy_rights_surface_found",
                            "url": page.url,
                            "claim": f"Privacy rights surface visible: '{text}'",
                            "raw_observation": text,
                            "confidence": 0.8,
                            "artifact_uris": [],  # will be linked to state screenshot
                            "created_at": datetime.utcnow().isoformat(),
                        }
                        await evidence_col().insert_one(ev_doc)
                        self.evidence_collected.append(ev_doc)
                except Exception:
                    continue
        except Exception as exc:
            logger.debug("Privacy rights exploration error", extra={"error": str(exc)})


async def run_dynamic_analysis(audit_id: str, root_url: str, pages: list[dict], config: dict, bus: EventBus) -> None:
    """
    Entry point for dynamic analysis. Called by orchestrator on dynamic.started event.
    """
    import uuid as _uuid
    try:
        session = BrowserExplorationSession(audit_id, root_url, config, bus)
        result = await session.run()

        envelope = EventEnvelope(
            event_type="dynamic.completed",
            audit_id=_uuid.UUID(audit_id),
            correlation_id=audit_id,
            payload={**result, "config": config, "url": root_url},
        )
        await bus.publish("dynamic.completed", envelope)
    except Exception as exc:
        logger.error("Dynamic analysis failed", extra={"audit_id": audit_id, "error": str(exc)}, exc_info=exc)
        fail_env = EventEnvelope(
            event_type="audit.failed",
            audit_id=_uuid.UUID(audit_id),
            correlation_id=audit_id,
            payload={"error": str(exc)},
        )
        await bus.publish("audit.failed", fail_env)
