"""Turn an issue made from .github/ISSUE_TEMPLATE/profile.yml into _people/<shortname>.md and its photo.

Reads the issue from ISSUE_BODY and ISSUE_AUTHOR. An existing profile is updated: fields left
empty in the form keep their current values, and the page text is replaced only when About or
one of the questions is filled.
"""
import io
import os
import re
import sys
import urllib.request
from pathlib import Path

import yaml
from PIL import Image, ImageOps

FORM = Path(".github/ISSUE_TEMPLATE/profile.yml")
LABELS = {field["id"]: field["attributes"]["label"] for field in yaml.safe_load(FORM.read_text())["body"] if "id" in field}
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


def save_photo(text, path):
    url = re.search(r"https://[^\s)\"']+", text)
    if not url:
        raise ValueError("No image found in the Photo field.")
    with urllib.request.urlopen(url.group(0), timeout=30) as response:
        image = Image.open(io.BytesIO(response.read(20_000_000)))
    image = ImageOps.exif_transpose(image).convert("RGB")
    ImageOps.fit(image, (PHOTO_SIZE, PHOTO_SIZE)).save(path, quality=90)


def build_profile(fields, author):
    name = fields["name"]
    shortname = fields.get("shortname", name.split()[-1]).lower()
    if not re.fullmatch(r"[a-z0-9-]+", shortname):
        raise ValueError(f"Short name `{shortname}` can only use lowercase letters, digits and dashes.")
    github = fields.get("github", author).lstrip("@")

    path = Path(f"_people/{shortname}.md")
    front, body = {"layout": "person"}, ""
    if path.exists():
        _, header, body = path.read_text().split("---\n", 2)
        front = yaml.safe_load(header)
        if front.get("github") not in (None, "", github):
            raise ValueError(f"`_people/{shortname}.md` belongs to someone else, pick another short name.")

    front.update(name=name, shortname=shortname, github=github)
    for key in ("role", "institution", "email", "orcid", "website"):
        if key in fields:
            front[key] = fields[key]
    if "subsystems" in fields:
        front["subsystems"] = [line.strip() for line in fields["subsystems"].splitlines() if line.strip()]
    if "photo" in fields:
        photo = f"assets/images/people/{shortname}.jpg"
        save_photo(fields["photo"], photo)
        front["photo"] = "/" + photo
    front.update(active=True, verified=True)
    sections = [fields["about"]] if "about" in fields else []
    sections += [f"### {label}\n\n{fields[field_id]}" for field_id, label in LABELS.items() if field_id.startswith("question-") and field_id in fields]
    if sections:
        body = "\n\n".join(sections) + "\n"

    front = {key: value for key, value in front.items() if value is not None}
    path.write_text("---\n" + yaml.safe_dump(front, sort_keys=False, allow_unicode=True) + "---\n" + body)
    return front


def main():
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as output:
        try:
            front = build_profile(parse_issue(os.environ["ISSUE_BODY"]), os.environ.get("ISSUE_AUTHOR", ""))
        except (ValueError, OSError) as error:
            print(f"error={error}", file=output)
            sys.exit(str(error))
        print(f"shortname={front['shortname']}\nname={front['name']}", file=output)
    print(f"Wrote _people/{front['shortname']}.md")


if __name__ == "__main__":
    main()
