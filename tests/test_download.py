from pathlib import Path

from scele import api


class _Response:
    url = "https://scele.example/webservice/pluginfile.php/1/mod_resource/content/0/file.txt?token=T"
    headers = {
        "content-disposition": 'attachment; filename="file.txt"',
        "content-length": "6",
    }

    def __init__(self):
        self.closed = False

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):
        assert chunk_size == 8192
        yield b"abc"
        yield b""
        yield b"def"

    def close(self):
        self.closed = True


class _Http:
    def __init__(self, response):
        self.response = response

    def get(self, url, params, stream, timeout):
        assert url == (
            "https://scele.example/webservice/pluginfile.php"
            "/1/mod_resource/content/0/file.txt?token=T"
        )
        assert params == {"forcedownload": "1"}
        assert stream is True
        assert timeout == 120
        return self.response


class _Session:
    base = "https://scele.example"
    token = "T"

    def __init__(self, response):
        self.http = _Http(response)

    def pluginfile_url(self, file_url):
        from scele.session import SceleSession

        return SceleSession.pluginfile_url(self, file_url)


def test_download_reports_progress_and_closes_response(tmp_path: Path):
    response = _Response()
    progress = []

    destination = api.download(
        _Session(response),
        "/pluginfile.php/1/mod_resource/content/0/file.txt",
        tmp_path,
        progress=lambda downloaded, total: progress.append((downloaded, total)),
    )

    assert destination == tmp_path / "file.txt"
    assert destination.read_bytes() == b"abcdef"
    assert progress == [(0, 6), (3, 6), (6, 6)]
    assert response.closed is True


class _EvilResponse(_Response):
    headers = {
        "content-disposition": 'attachment; filename="../../../../etc/evil.txt"',
        "content-length": "6",
    }


def test_download_strips_path_traversal_from_filename(tmp_path: Path):
    destination = api.download(
        _Session(_EvilResponse()),
        "/pluginfile.php/1/mod_resource/content/0/file.txt",
        tmp_path,
    )

    assert destination == (tmp_path / "evil.txt").resolve()
    assert destination.read_bytes() == b"abcdef"
