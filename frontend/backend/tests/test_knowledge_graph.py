from app.services import knowledge_graph


def test_unknown_pair_does_not_trigger_network_lookup(monkeypatch):
    import requests

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("Decision-path knowledge lookup attempted network access")

    monkeypatch.setattr(requests, "get", fail_if_called)
    assert knowledge_graph.med_kg.check_interaction("Warfarin", "Metformin") is None


def test_known_interaction_comes_from_file_data():
    interaction = knowledge_graph.med_kg.check_interaction("Warfarin", "Aspirin")
    assert interaction is not None
    assert interaction["severity"] == "HIGH"

