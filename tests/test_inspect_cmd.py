from fixtures import build_3fr


def test_inspect_prints_fields(tool, tmp_path, capsys):
    p = build_3fr(tmp_path / "t.3FR", maker_f=89.48658, maker_m=0.00112)
    rc = tool.main(["inspect", str(p)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "89.48658" in out and "0.00112" in out
    assert "79.99" in out  # thin-lens estimate
    assert "X2D II 100C" in out


def test_inspect_bad_file_exits_1(tool, tmp_path, capsys):
    p = tmp_path / "junk.3FR"
    p.write_bytes(b"not a tiff")
    rc = tool.main(["inspect", str(p)])
    assert rc == 1
    assert "not a TIFF" in capsys.readouterr().out
