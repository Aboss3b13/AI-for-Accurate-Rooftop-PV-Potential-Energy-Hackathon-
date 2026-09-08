def capacity(panel_count, power_w, annual_specific_yield=None):
    kwp = panel_count * power_w / 1000
    return {
        "additional_kwp": round(kwp, 3),
        "annual_energy_kwh": round(kwp * annual_specific_yield)
        if annual_specific_yield is not None
        else None,
    }
