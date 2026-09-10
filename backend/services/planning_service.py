"""Auditable advisory constraints, separate from installer assumptions."""
SOURCE = "https://services.vkg.ch/rest/public/georg/bs/publikation/documents/BSPUB-1394520214-197.pdf/content"


def planning_constraints(settings):
    factor = {"conservative": 1.5, "recommended": 1., "maximum": .5}[settings.mode]
    return {
        "profile": "CH_PLANNING_ADVISORY_2026_09",
        "status": "Not certified",
        "installer_assumptions_m": {key: round(getattr(settings, key)*factor, 3)
            for key in ("edge_margin", "obstacle_margin", "pv_margin")},
        "rules": [{"type": "rwa_clearance", "distance_m": 2., "status": "advisory",
                   "condition": "User-marked smoke / heat exhaust opening; no alternative clearance envelope assessed",
                   "source": SOURCE, "source_section": "VKF 2001-15, 2022 edition, section 3.2.3 and appendix page 14",
                   "note": "Retained in all packing modes. Opening operation, snow and site-specific arrangements require review."}],
        "not_automatically_verified": ["Structural and snow/wind loads", "Cantonal and municipal requirements",
            "Heritage restrictions", "Electrical design", "Fire-service access", "Roof mounting and projection"],
    }
