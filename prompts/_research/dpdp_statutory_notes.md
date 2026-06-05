# DPDP Statutory Research Notes

## dpdp_notice_clarity
**Act sections**: Section 6 (Consent Requirements)
**Rules**: DPDP Rules 2025 - Rule 6 (Notice Requirements)
**Audit signal**: Verify that a standalone privacy notice in plain language is displayed BEFORE seeking consent, available in all relevant Indian languages, and clearly describes what data is collected, why, and how the data principal can exercise their rights. The notice should be easily accessible and not buried in small print.

## dpdp_consent_specificity
**Act sections**: Section 6(1) - Consent must be "limited to such personal data as is necessary for such specified purpose"
**Rules**: DPDP Rules 2025 - Rule 6, Rule 8(2)
**Audit signal**: Check that consent requests are granular and purpose-specific (not bundled), that pre-ticked boxes are absent, and that consent cannot be coerced through terms that require waiving statutory rights. Each consent should map to a single, clearly articulated purpose.

## dpdp_withdrawal_parity
**Act sections**: Section 6(2) - "a Data Principal has the right to withdraw consent at any time, with the ease of doing so being comparable to the ease with which such consent was given"
**Rules**: DPDP Rules 2025 - Rule 8(2)(d)
**Audit signal**: Verify that withdrawal mechanism uses the same channel and method as the original consent, with no additional friction, penalties, or discrimination. Audit should confirm withdrawal is as simple as consent-giving (e.g., if consent was a one-click, withdrawal should be equally simple).

## dpdp_consent_manager
**Act sections**: Section 3 (Definitions), Sections 4-5 (Consent Manager role)
**Rules**: DPDP Rules 2025 - Rule 4 (Registration and Obligations of Consent Manager)
**Audit signal**: If a consent manager is in use, verify it is registered with the DPB, operates an interoperable, data-blind platform, and meets minimum net worth and certification requirements. Check that the platform does not read or store personal data routed through it, and that consents are recorded transparently.

## dpdp_data_principal_access
**Act sections**: Section 11 (Access Rights) - Data Principal has right to "obtain from a Data Fiduciary a summary of the personal data being processed and the processing activities"
**Rules**: DPDP Rules 2025 - Rule 14(1)
**Audit signal**: Verify that users can request and receive (within reasonable timeframe, typically 30 days) a summary of all personal data collected, identities of all data fiduciaries and processors, and descriptions of data shared. The response should be in plain language and accessible.

## dpdp_correction_erasure
**Act sections**: Section 12 - Data Principals have the right to "correction, completion, updating and erasure of personal data" for which they gave consent
**Rules**: DPDP Rules 2025 - Rule 14(2)
**Audit signal**: Check that users can request correction of inaccurate/misleading data, completion of incomplete data, or erasure (unless retention is legally mandated). System must notify user at least 48 hours before erasure is executed. Verify no unjustified refusals to correct or erase.

## dpdp_grievance_redressal
**Act sections**: Section 10 (Grievance Redressal Mechanism)
**Rules**: DPDP Rules 2025 - Rule 14(3)
**Audit signal**: Audit should confirm that every data fiduciary and consent manager has established a grievance redressal system that responds to grievances within a reasonable period not exceeding 90 days, in plain language, and that the system is publicly documented and accessible (e.g., via website contact form, email, phone).

## dpdp_nomination
**Act sections**: Section 13 (Nomination of Individual to Exercise Data Principal Rights)
**Rules**: DPDP Rules 2025 - Rule 14(4)
**Audit signal**: Verify that users can nominate individuals (e.g., family members, representatives) to exercise their rights on their behalf. Check that the system allows nomination, manages nominated individual authentication, and permits revocation of nomination. Particularly important for incapacitated individuals or minors.

## dpdp_child_data_guardian_consent
**Act sections**: Section 14 - Data Fiduciary must "obtain verifiable parental or lawful guardian consent before processing the personal data of a child"
**Rules**: DPDP Rules 2025 - Rule 5 (Child Data Protection) - Parental consent via age/identity verification through authorized entities or digital locker
**Audit signal**: For websites/apps targeting or collecting from children (or where age is uncertain), verify age-gating mechanism, that parental consent is obtained via verified channels (digital locker, authorized identity verifiers), and that behavioral monitoring or targeted advertising to children is prohibited.

## dpdp_data_minimization
**Act sections**: Section 6(1) - Consent limited to "such personal data as is necessary for such specified purpose"
**Rules**: DPDP Rules 2025 - Rule 8(1)
**Audit signal**: Review the data collection form and verify that only fields marked as "necessary for the specified purpose" are collected. Audit should flag optional fields, unused fields, or collection of data beyond the stated purpose as violations. Check consent text aligns with actual fields collected.

## dpdp_security_breach_notice_surface
**Act sections**: Section 8(6), 8(7) - Data Fiduciary must notify DPB and affected Data Principals of breaches
**Rules**: DPDP Rules 2025 - Rule 7 (Intimation of Personal Data Breach)
**Audit signal**: While difficult to audit directly on live sites, verify that privacy policy or terms acknowledge breach notification obligations. Audit should note if breach notification contact details or procedures are publicly documented, and whether a mechanism exists for users to verify breach status through a published portal or email notifications.
