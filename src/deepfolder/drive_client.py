import re
from urllib.parse import urlparse, parse_qs


class DriveClient:
    def parse_folder_url(self, url: str) -> str:
        url = url.strip()

        if url.startswith("0A"):
            raise ValueError("Shared Drives not yet supported")

        match = re.search(r"/folders/([a-zA-Z0-9_-]+)", url)
        if match:
            folder_id = match.group(1)
            if folder_id.startswith("0A"):
                raise ValueError("Shared Drives not yet supported")
            return folder_id

        if "/" not in url and "?" not in url:
            if url.startswith("0A"):
                raise ValueError("Shared Drives not yet supported")
            return url

        raise ValueError("Invalid folder URL")
