import anlagen_copilot


def test_main_exists() -> None:
    assert callable(anlagen_copilot.main)
