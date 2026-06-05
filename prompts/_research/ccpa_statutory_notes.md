# CCPA/CPRA Statutory Research Notes

## ccpa_notice_at_collection
**Provision**: CCPA § 1798.100(b); CPRA expanded requirements for "at or before" collection point disclosure
**Website audit signal**: Presence of privacy notice/disclosure at data collection point (forms, account signup, tracking disclosure); notice must list categories of personal information collected, purposes, and "Do Not Sell or Share" link availability
**Common failure modes**: No notice visible at collection; notice hidden behind links/modals; incomplete disclosure of categories or purposes; missing "Do Not Sell or Share My Personal Information" link

## ccpa_privacy_policy_rights
**Provision**: CCPA § 1798.100(d); CPRA § 1798.150 require detailed privacy policy
**Website audit signal**: Privacy policy explicitly lists consumer rights (Know, Delete, Correct, Opt-Out of Sale/Share, Limit Sensitive PI, Non-Discrimination); describes processes for submitting requests; includes authorized agent language; accessible from homepage
**Common failure modes**: Rights omitted or vague in policy; no instructions for submitting requests; policy inaccessible; dated or generic boilerplate language

## ccpa_right_to_know_access
**Provision**: CCPA § 1798.100(a); Consumers may request specific personal information and categories collected, sources, business purposes, and third parties
**Website audit signal**: Website provides mechanism (portal, form, email) for submitting access requests; response timeline stated (45 days, extendable to 90); free requests at least twice yearly; verification method described
**Common failure modes**: No access request mechanism visible; processing fees charged; response timeline exceeds 90 days; requires unnecessary verification; limits on request frequency

## ccpa_right_to_delete
**Provision**: CCPA § 1798.105(a); Consumers may request deletion except where retention is legally mandated, required to complete transaction, or necessary for security/fraud prevention
**Website audit signal**: Deletion request process documented; exceptions clearly listed; 45-90 day response timeline stated; business describes retention necessity in specific contexts (e.g., fraud prevention, legal holds)
**Common failure modes**: Deletion button missing or buried; blanket refusal to delete; timeline violation; no mention of statutory exceptions; deletion only works after account deletion

## ccpa_right_to_correct
**Provision**: CPRA § 1798.100(d)-(e); Consumers may request correction of inaccurate personal information
**Website audit signal**: Website provides correction request mechanism; describes verification process to confirm accuracy request; timeline stated (45-90 days); clarifies inaccuracy definition and scope of correctable data
**Common failure modes**: No correction mechanism provided; requires excessive verification; ignores legitimate accuracy challenges; no timeline communicated; conflated with deletion rights

## ccpa_opt_out_sale_share
**Provision**: CCPA § 1798.120(a)-(b); CPRA § 1798.120(a) defines sharing as cross-context behavioral advertising; requires "clear and conspicuous" opt-out link
**Website audit signal**: "Do Not Sell/Share My Personal Information" link present and prominently visible (homepage, footer, or consistent location); link distinguishes between "sale" (CCPA) and "sharing" (CPRA); opt-out status honored within reasonable timeframe; GPC signal honored
**Common failure modes**: Link missing or hidden; unclear labeling; opt-out ignored in practice; no timeline for honoring opt-out; link only activates after login; conflates sale and sharing

## ccpa_gpc_signal
**Provision**: CPRA § 1798.120(d); Businesses must honor Global Privacy Control signal transmitted via compliant browser/device
**Website audit signal**: Website code respects "Sec-GPC: 1" HTTP header or JavaScript API (navigator.globalPrivacyControl); backend logs/honors GPC signal; audit trail shows non-sale practices after GPC detection; no nagging/dark patterns override GPC
**Common failure modes**: GPC signal ignored in backend; website requests additional opt-out despite GPC detected; cookie banners appear despite GPC; no code implementation of GPC header detection

## ccpa_limit_sensitive_pi
**Provision**: CPRA § 1798.100(d), 1798.121(a); Consumers may limit use of sensitive personal information (SSN, financial accounts, precise geolocation, genetic data, biometric, health, sexual orientation, race/ethnicity)
**Website audit signal**: Website identifies what constitutes sensitive PI; provides mechanism to limit sensitive data use to service provision only; privacy policy explicitly lists sensitive PI categories collected; limitation honored without friction
**Common failure modes**: Sensitive PI category not disclosed; no limit mechanism provided; business collects sensitive PI without stated necessity; limitation request ignored or violated

## ccpa_non_discrimination
**Provision**: CCPA § 1798.125(a)-(b); CPRA § 1798.125; Businesses cannot deny goods/services, charge different prices, or provide different quality for exercising CCPA rights, though may condition services on necessary data
**Website audit signal**: Website does not degrade service/pricing based on privacy choices; no "dark patterns" punishing opt-out; no forced consent to participate; same functionality available with/without data sharing; service remains operable post-opt-out
**Common failure modes**: Service disabled after opt-out; prices increase or quality degrades for privacy-conscious users; forced consent gates all features; upsell/nagging follows opt-out; essential functions locked behind data sharing

## ccpa_authorized_agent
**Provision**: CCPA § 1798.100(d); CPRA § 1798.140(ag) defines authorized agents; businesses may require agent authorization documentation
**Website audit signal**: Privacy policy acknowledges authorized agent requests; process documented for submitting agent-made requests; description of acceptable agent authorization proof (power of attorney, written permission); agent requests processed within same 45-90 day timeline
**Common failure modes**: Authorized agent requests rejected without cause; no process documented; excessive or non-standard authorization requirements; agent requests processed slower than consumer requests; policy silent on agents
