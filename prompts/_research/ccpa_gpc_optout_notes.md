# CCPA GPC / Opt-Out Signal Research Notes (11 CCR 7025, 7026)

## 11 CCR 7025 — Opt-Out Preference Signals (GPC)

**Key requirements:**
- Businesses must honor opt-out preference signals that use "a format commonly used and recognized by businesses" (e.g., HTTP headers, JavaScript objects)
- The signal source must clearly disclose intent to opt the consumer out of sale and sharing of personal information
- Signals must be treated as legitimate opt-out requests covering both online and offline sales when the consumer is identifiable
- Businesses cannot charge fees, require valuable consideration, degrade service quality, or display notifications/pop-ups in response to signals
- When signals conflict with existing privacy settings or incentive programs, businesses may request confirmation but must ultimately honor the signal unless affirmatively contradicted

**Website audit signals:**
- Check for presence of GPC HTTP header support (e.g., `Sec-GPC: 1`)
- Verify that receipt of GPC signal does not trigger friction (pop-ups, notification bars, service degradation)
- Confirm that profile tracking behavior changes appropriately after GPC signal is sent
- Look for unnecessary friction in processing (e.g., requiring login or additional information beyond what signal provides)
- Check if conflicting signals (GPC vs. behavioral tracking/retargeting) indicate non-compliance

**Observable indicators:**
- HTTP header `Sec-GPC: 1` present in requests when browser/extension sends signal
- No pop-ups, cookie banners, or notification overlays appear specifically in response to GPC signal
- Data sale/sharing restrictions apply immediately or within 15 business days
- No service degradation, feature restrictions, or quality reduction after GPC signal
- Third-party cookie behavior changes or is blocked after GPC signal received
- Advertising behavior shifts (reduced targeting, different ad categories)

---

## 11 CCR 7026 — Opt-Out Requests

**Key requirements:**
- Businesses must provide "two or more designated methods" for opt-out requests
- Online businesses must offer at least one interactive form or privacy policy-based method AND support preference signals
- Acceptable methods: toll-free numbers, email, in-person forms, mail, opt-out preference signals
- Methods must be "easy for consumers to execute" and require minimal steps
- Businesses cannot use cookie banners alone as opt-out mechanisms
- Businesses cannot require account creation or demand unnecessary information
- Authorized agents may submit requests on behalf of consumers with written permission
- No account verification or "verifiable consumer request" formality is required (identifying information may be requested only to process the opt-out)

**Website audit signals:**
- Verify presence of multiple opt-out methods accessible from privacy page or footer
- Check that at least one method is an interactive form (not just a phone number)
- Confirm that opt-out preference signals (GPC) are supported and honored
- Look for unnecessary friction (required login, account creation, extensive forms) in opt-out submission
- Verify that cookie consent banner does NOT claim to be the sole opt-out mechanism
- Check privacy policy for clarity on opt-out methods and their accessibility

**Timeline requirements:**
- Businesses must cease sales or sharing "no later than 15 business days" after receiving a valid opt-out request
- Third parties who received shared data must be notified of the opt-out
- Businesses must wait at least 12 months before re-requesting opt-in consent from consumers who have opted out
- Fraudulent requests may be denied only if documented with reasonable justification

**Restrictions & Compliance:**
- No fees or valuable consideration may be charged
- No service degradation or reduced functionality for opted-out consumers
- Cookie banners cannot serve as the sole opt-out mechanism
- Granular opt-out choices may be offered, but single comprehensive opt-out must remain available
