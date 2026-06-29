# Future Marketplace Direction

PathScout v0.2 does not implement a hosted marketplace, candidate database, recruiter workflow, or intro API.

The future product direction is an opt-in intro marketplace layered on top of trusted local discovery:

- Users run PathScout locally and decide which findings are worth acting on.
- Users explicitly opt into sharing selected profile and opportunity context.
- Startups, founders, or recruiters can request introductions only when the user has opted in.
- Monetization should attach to high-fit, consented introductions rather than access to a broad candidate database.
- Local config, suppressions, and raw observations should remain private unless the user deliberately exports or shares them.

This separation matters because the local tool has to earn trust before marketplace liquidity is useful. The v0.2 implementation should focus on stable findings, explainability, suppressions, and machine-readable artifacts.
