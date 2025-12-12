from backend.contracts.validation import validate_ta_contract


class _KPA:
    def __init__(self, hours, weight):
        self.hours = hours
        self.weight_pct = weight


class _Contract:
    def __init__(self):
        self.kpas = {
            "KPA1": _KPA(900, 20.0),
            "KPA2": _KPA(300, 20.0),
            "KPA3": _KPA(200, 20.0),
            "KPA4": _KPA(180, 20.0),
            "KPA5": _KPA(220, 20.0),
        }
        self.snapshot = {"norm_hours": 1700.0, "ta_warnings": ["extra note"]}
        self.valid = True
        self.validation_errors = []



def test_over_norm_hours_surfaces_warning():
    contract = _Contract()

    is_valid, errors, warnings = validate_ta_contract(contract, director_level=False)

    assert is_valid
    assert not errors
    assert any("Over-norm workload" in w for w in warnings)
    assert "extra note" in warnings
