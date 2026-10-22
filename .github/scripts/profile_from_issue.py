"""Turn an issue made from .github/ISSUE_TEMPLATE/profile.yml into _people/<shortname>.md and its photo.

Reads the issue from ISSUE_BODY and ISSUE_AUTHOR. The profile with `github:` equal to the issue
author is updated. Otherwise a new profile is made, named after the last name, or the full name
when the last name is taken. Each field comes from the form, else the existing profile, else the
author's public GitHub profile.
"""
import io
import json
import os
import re
import sys
import unicodedata
import urllib.request
from pathlib import Path

import yaml
from PIL import Image, ImageOps

FORM = [field for field in yaml.safe_load(Path(".github/ISSUE_TEMPLATE/profile.yml").read_text())["body"] if "id" in field]
LABELS = {field["id"]: field["attributes"]["label"] for field in FORM}
QUESTIONS = {line for field in FORM if field["id"] == "about" for line in field["attributes"]["value"].splitlines() if line}
PEOPLE = Path("_people")
PHOTO_SIZE = 256


def parse_issue(body):
    """Issue forms render each field as '### <label>' followed by its value."""
    ids = {label: field_id for field_id, label in LABELS.items()}
    fields = {}
    for section in re.split(r"^### ", body.replace("\r\n", "\n"), flags=re.M)[1:]:
        label, _, value = section.partition("\n")
        value = value.strip()
        if label.strip() in ids and value and value != "_No response_":
            fields[ids[label.strip()]] = value
    return fields


def drop_unanswered(text):
    """Remove template questions followed by another question or by nothing."""
    blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    following = blocks[1:] + [None]
    return "\n\n".join(block for block, next_block in zip(blocks, following)
                       if block not in QUESTIONS or (next_block is not None and next_block not in QUESTIONS))


def github_profile(login):
    request = urllib.request.Request(f"https://api.github.com/users/{login}")
    if os.environ.get("GITHUB_TOKEN"):
        request.add_header("Authorization", f"Bearer {os.environ['GITHUB_TOKEN']}")
    with urllib.request.urlopen(request, timeout=30) as response:
        user = json.load(response)
    website = user["blog"] if not user["blog"] or "://" in user["blog"] else "https://" + user["blog"]
    profile = {"name": user["name"] or login, "institution": (user["company"] or "").lstrip("@"),
               "website": website, "photo": user["avatar_url"], "about": user["bio"]}
    return {key: value.strip() for key, value in profile.items() if value and value.strip()}


def slug(text):
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def read_profile(path):
    header, body = path.read_text().removeprefix("---\n").split("\n---\n", 1)
    return yaml.safe_load(header), body


def profile_path(name, github):
    for path in PEOPLE.glob("*.md"):
        if read_profile(path)[0].get("github") == github:
            return path
    for shortname in filter(None, (slug(name.split()[-1]), slug(name))):
        path = PEOPLE / f"{shortname}.md"
        if not path.exists():
            return path
        front = read_profile(path)[0]
        if not front.get("github") and front.get("name") == name:
            return path
    raise ValueError("Could not pick a file name for your profile, please ask a maintainer.")


def save_photo(text, path):
    url = re.search(r"https://[^\s)\"']+", text)
    if not url:
        raise ValueError("No image found in the Photo field.")
    with urllib.request.urlopen(url.group(0), timeout=30) as response:
        image = Image.open(io.BytesIO(response.read(20_000_000)))
    image = ImageOps.exif_transpose(image).convert("RGB")
    ImageOps.fit(image, (PHOTO_SIZE, PHOTO_SIZE)).save(path, quality=90)


def build_profile(fields, github):
    defaults = github_profile(github)
    path = profile_path(fields.get("name", defaults["name"]), github)
    front, body = read_profile(path) if path.exists() else ({"layout": "person"}, "")

    for key in ("name", "institution", "role", "website"):
        value = fields.get(key) or front.get(key) or defaults.get(key)
        if value:
            front[key] = value
    front.update(shortname=path.stem, github=github)
    photo = fields.get("photo") or (not front.get("photo") and defaults.get("photo"))
    if photo:
        photo_path = f"assets/images/people/{path.stem}.jpg"
        save_photo(photo, photo_path)
        front["photo"] = "/" + photo_path
    front.update(active=True, verified=True)
    about = drop_unanswered(fields.get("about", "")) or (not body.strip() and defaults.get("about"))
    if about:
        body = about + "\n"

    front = {key: value for key, value in front.items() if value is not None}
    path.write_text("---\n" + yaml.safe_dump(front, sort_keys=False, allow_unicode=True) + "---\n" + body)
    return front


def main():
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as output:
        try:
            front = build_profile(parse_issue(os.environ["ISSUE_BODY"]), os.environ["ISSUE_AUTHOR"])
        except (ValueError, OSError) as error:
            print(f"error={error}", file=output)
            sys.exit(str(error))
        print(f"shortname={front['shortname']}\nname={front['name']}", file=output)
    print(f"Wrote _people/{front['shortname']}.md")


if __name__ == "__main__":
    main()
