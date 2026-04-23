import pytest

from deepfolder.drive_client import DriveClient


def test_parse_folder_url_simple_id():
    client = DriveClient()
    folder_id = client.parse_folder_url("1234567890abcdefg")
    assert folder_id == "1234567890abcdefg"


def test_parse_folder_url_with_drive_folders():
    client = DriveClient()
    folder_id = client.parse_folder_url("drive/folders/1234567890abcdefg")
    assert folder_id == "1234567890abcdefg"


def test_parse_folder_url_with_drive_folders_full_url():
    client = DriveClient()
    folder_id = client.parse_folder_url(
        "https://drive.google.com/drive/folders/1234567890abcdefg"
    )
    assert folder_id == "1234567890abcdefg"


def test_parse_folder_url_with_sharing_param():
    client = DriveClient()
    folder_id = client.parse_folder_url(
        "https://drive.google.com/drive/folders/1234567890abcdefg?usp=sharing"
    )
    assert folder_id == "1234567890abcdefg"


def test_parse_folder_url_with_drive_u_0():
    client = DriveClient()
    folder_id = client.parse_folder_url(
        "https://drive.google.com/drive/u/0/folders/1234567890abcdefg"
    )
    assert folder_id == "1234567890abcdefg"


def test_parse_folder_url_shared_drive_rejected():
    client = DriveClient()
    with pytest.raises(ValueError, match="Shared Drives not yet supported"):
        client.parse_folder_url("https://drive.google.com/drive/u/0/folders/0ACZ_XYZ")


def test_parse_folder_url_shared_drive_with_drive_id_rejected():
    client = DriveClient()
    with pytest.raises(ValueError, match="Shared Drives not yet supported"):
        client.parse_folder_url("0ADriveID123")
