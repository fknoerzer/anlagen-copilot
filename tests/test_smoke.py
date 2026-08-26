import anlagen_copilot.cli as cli


def test_main_exists() -> None:
    assert callable(cli.main)
