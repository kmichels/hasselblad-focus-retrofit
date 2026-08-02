def test_version_and_main_exist(tool):
    assert isinstance(tool.VERSION, str)
    assert callable(tool.main)


def test_no_args_shows_help_and_exits_2(tool, capsys):
    rc = tool.main([])
    assert rc == 2
    assert "retrofit" in capsys.readouterr().err
