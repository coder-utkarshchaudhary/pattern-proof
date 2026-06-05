"""
Authoritative taxonomy definitions for Pattern Proof.

Covers: audit lifecycle, Mathur dark-pattern categories/patterns,
DPDP and CCPA/CPRA privacy dimensions, evidence sources, severity,
user roles, page types, action types, and risk-scoring constants.
"""
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Audit lifecycle
# ---------------------------------------------------------------------------

class AuditStatus(str, Enum):
    CREATED = "created"
    QUEUED = "queued"
    DISCOVERING = "discovering"
    STATIC_ANALYSIS = "static_analysis"
    DYNAMIC_ANALYSIS = "dynamic_analysis"
    DETECTING_PATTERNS = "detecting_patterns"
    REPORTING = "reporting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# Mathur dark-pattern categories
# ---------------------------------------------------------------------------

class MathurCategory(str, Enum):
    SNEAKING = "sneaking"
    OBSTRUCTION = "obstruction"
    FORCED_ACTION = "forced_action"
    INTERFACE_INTERFERENCE = "interface_interference"
    NAGGING = "nagging"
    SOCIAL_PROOF = "social_proof"
    SCARCITY = "scarcity"
    URGENCY = "urgency"
    CONFIRMSHAMING = "confirmshaming"
    ROACH_MOTEL = "roach_motel"
    FORCED_CONTINUITY = "forced_continuity"


# ---------------------------------------------------------------------------
# Mathur sub-patterns
# ---------------------------------------------------------------------------

class MathurPattern(str, Enum):
    HIDDEN_FEES = "hidden_fees"
    DRIP_PRICING = "drip_pricing"
    HIDDEN_SUBSCRIPTION = "hidden_subscription"
    PRESELECTED_ADDONS = "preselected_addons"
    DATA_SHARING_CONCEALED = "data_sharing_concealed"
    HARD_CANCELLATION = "hard_cancellation"
    HARD_OPT_OUT = "hard_opt_out"
    HARD_ACCOUNT_DELETION = "hard_account_deletion"
    EXCESSIVE_STEPS = "excessive_steps"
    DEAD_END = "dead_end"
    FORCED_REGISTRATION = "forced_registration"
    FORCED_CONSENT = "forced_consent"
    FORCED_DATA_DISCLOSURE = "forced_data_disclosure"
    FORCED_SHARING = "forced_sharing"
    VISUAL_HIERARCHY_MANIPULATION = "visual_hierarchy_manipulation"
    HIDDEN_LOW_CONTRAST_CHOICE = "hidden_low_contrast_choice"
    MISLEADING_BUTTON_LABEL = "misleading_button_label"
    TRICK_QUESTION = "trick_question"
    PRESELECTION = "preselection"
    REPEATED_POPUP = "repeated_popup"
    REPEATED_CONSENT_PROMPT = "repeated_consent_prompt"
    FAKE_POPULARITY = "fake_popularity"
    FAKE_ACTIVITY = "fake_activity"
    LOW_STOCK_CLAIM = "low_stock_claim"
    LIMITED_AVAILABILITY = "limited_availability"
    COUNTDOWN_TIMER = "countdown_timer"
    EXPIRING_OFFER = "expiring_offer"
    GUILT_REJECTION_LABEL = "guilt_rejection_label"


# ---------------------------------------------------------------------------
# DPDP dimensions
# ---------------------------------------------------------------------------

class DPDPDimension(str, Enum):
    NOTICE_CLARITY = "dpdp_notice_clarity"
    CONSENT_SPECIFICITY = "dpdp_consent_specificity"
    WITHDRAWAL_PARITY = "dpdp_withdrawal_parity"
    CONSENT_MANAGER = "dpdp_consent_manager"
    DATA_PRINCIPAL_ACCESS = "dpdp_data_principal_access"
    CORRECTION_ERASURE = "dpdp_correction_erasure"
    GRIEVANCE_REDRESSAL = "dpdp_grievance_redressal"
    NOMINATION = "dpdp_nomination"
    CHILD_DATA_GUARDIAN_CONSENT = "dpdp_child_data_guardian_consent"
    DATA_MINIMIZATION = "dpdp_data_minimization"
    SECURITY_BREACH_NOTICE_SURFACE = "dpdp_security_breach_notice_surface"


# ---------------------------------------------------------------------------
# CCPA/CPRA dimensions
# ---------------------------------------------------------------------------

class CCPADimension(str, Enum):
    NOTICE_AT_COLLECTION = "ccpa_notice_at_collection"
    PRIVACY_POLICY_RIGHTS = "ccpa_privacy_policy_rights"
    RIGHT_TO_KNOW_ACCESS = "ccpa_right_to_know_access"
    RIGHT_TO_DELETE = "ccpa_right_to_delete"
    RIGHT_TO_CORRECT = "ccpa_right_to_correct"
    OPT_OUT_SALE_SHARE = "ccpa_opt_out_sale_share"
    GPC_SIGNAL = "ccpa_gpc_signal"
    LIMIT_SENSITIVE_PI = "ccpa_limit_sensitive_pi"
    NON_DISCRIMINATION = "ccpa_non_discrimination"
    AUTHORIZED_AGENT = "ccpa_authorized_agent"


# ---------------------------------------------------------------------------
# Shared taxonomy enums
# ---------------------------------------------------------------------------

class PrivacyFramework(str, Enum):
    DPDP = "dpdp"
    CCPA = "ccpa"


class PrivacyFindingStatus(str, Enum):
    PRESENT = "present"
    MISSING = "missing"
    UNCLEAR = "unclear"
    POTENTIAL_ISSUE = "potential_issue"


class JurisdictionScope(str, Enum):
    MATHUR = "mathur"
    DPDP = "dpdp"
    CCPA = "ccpa"


class EvidenceSource(str, Enum):
    DOM = "dom"
    CSS = "css"
    OCR = "ocr"
    ACCESSIBILITY = "accessibility"
    VISUAL = "visual"
    NETWORK = "network"
    DYNAMIC = "dynamic"
    TRAJECTORY = "trajectory"


class FindingSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class UserRole(str, Enum):
    USER = "user"
    ADMIN = "admin"
    DEV = "dev"


class PageType(str, Enum):
    HOME = "home"
    PRODUCT = "product"
    CART = "cart"
    CHECKOUT = "checkout"
    SIGNUP = "signup"
    LOGIN = "login"
    ACCOUNT = "account"
    SUBSCRIPTION = "subscription"
    CANCELLATION = "cancellation"
    PRIVACY_POLICY = "privacy_policy"
    CONSENT = "consent"
    SETTINGS = "settings"
    OTHER = "other"


class ActionType(str, Enum):
    NAVIGATE = "navigate"
    CLICK = "click"
    SCROLL = "scroll"
    FILL = "fill"
    SELECT = "select"
    SUBMIT = "submit"


# ---------------------------------------------------------------------------
# Taxonomy result model for privacy analysis
# ---------------------------------------------------------------------------

class PrivacyTaxonomyResult(BaseModel):
    """Result of a single privacy-taxonomy dimension check."""

    framework: PrivacyFramework
    dimension: str  # DPDPDimension or CCPADimension value
    status: PrivacyFindingStatus
    summary: str
    evidence_ids: list[UUID] = []
    confidence: float = Field(ge=0.0, le=1.0)
    requires_human_review: bool = True


# ---------------------------------------------------------------------------
# Risk-scoring constants
# ---------------------------------------------------------------------------

SEVERITY_WEIGHTS: dict[str, float] = {
    "low": 5.0,
    "medium": 12.0,
    "high": 25.0,
    "critical": 40.0,
}

EVIDENCE_DIVERSITY_MULTIPLIERS: dict[int, float] = {1: 1.0, 2: 1.15}
EVIDENCE_DIVERSITY_MAX_MULTIPLIER: float = 1.3
TRAJECTORY_MULTIPLIER: float = 1.25
PRIVACY_MULTIPLIER: float = 1.15
