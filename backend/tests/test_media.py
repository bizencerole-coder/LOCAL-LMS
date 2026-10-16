import pytest

from app.media import (
    InvalidStorageKey,
    build_playback_url,
    resolve_media_path,
    sign_media_uri,
    validate_storage_key,
)


def test_signature_matches_the_nginx_documentation_example():
    # From the ngx_http_secure_link_module docs:
    #   echo -n '2147483647/s/link127.0.0.1 secret' | openssl md5 -binary | openssl base64 | tr +/ -_ | tr -d =
    assert sign_media_uri("/s/link", 2147483647, "127.0.0.1", "secret") == "_e4Nc3iduzkWRm01TBBNYw"


@pytest.mark.parametrize(
    "key",
    ["class12/cs/lesson-01.mp4", "a.mp4", "Class_12/Maths/Lesson.1.M4V", "x/y/z/v-2_final.mp4"],
)
def test_valid_storage_keys(key):
    assert validate_storage_key(key) == key


def test_backslashes_are_normalised():
    assert validate_storage_key("class12\\cs\\lesson.mp4") == "class12/cs/lesson.mp4"


@pytest.mark.parametrize(
    "key",
    [
        "",
        "/etc/passwd.mp4",
        "../secret.mp4",
        "class12/../../x.mp4",
        "class12/.hidden.mp4",
        "class 12/lesson.mp4",
        "class12//lesson.mp4",
        "class12/lesson.mkv",
        "class12/lesson",
        "class12/lesson.mp4?x=1",
        "class12/lessön.mp4",
        "a" * 501 + ".mp4",
    ],
)
def test_invalid_storage_keys(key):
    with pytest.raises(InvalidStorageKey):
        validate_storage_key(key)


def test_resolve_media_path_stays_under_root(tmp_path):
    assert resolve_media_path(tmp_path, "a/b.mp4") == tmp_path / "a" / "b.mp4"
    with pytest.raises(InvalidStorageKey):
        resolve_media_path(tmp_path, "../b.mp4")


def test_build_playback_url_shape():
    url = build_playback_url(
        base_url="http://192.168.10.10/",
        prefix="/media/",
        storage_key="class12/cs/a.mp4",
        sid="abc",
        expires=2000000000,
        secret="s" * 32,
    )
    assert url.startswith("http://192.168.10.10/media/class12/cs/a.mp4?expires=2000000000&sid=abc&md5=")
