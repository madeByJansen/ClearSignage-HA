"""The release channels. Packaging lives on main; source branches live upstream."""

import argparse
import os
import shlex

CHANNELS = {
    "stable": {"name": "ClearVenue", "slug": "clearvenue", "branch": "prod", "package": "clearvenue"},
    "beta": {"name": "ClearVenue Beta", "slug": "clearvenue_beta", "branch": "beta", "package": "clearvenue-beta"},
    "dev": {"name": "ClearVenue Dev", "slug": "clearvenue_dev", "branch": "main", "package": "clearvenue-dev"},
}


def channel_settings(channel):
    if channel not in CHANNELS:
        raise ValueError(f"Unknown channel {channel!r}; choose dev, beta or stable")
    settings = dict(CHANNELS[channel])
    settings["addon_dir"] = settings["slug"]
    settings["image"] = "ghcr.io/madebyjansen/" + settings["package"]
    return settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", default=os.environ.get("CHANNEL", "stable"), choices=CHANNELS)
    parser.add_argument("--field", choices=["name", "slug", "branch", "package", "addon_dir", "image"])
    args = parser.parse_args()
    settings = channel_settings(args.channel)
    if args.field:
        print(settings[args.field])
    else:
        for key, value in {"CHANNEL": args.channel, "ADDON_DIR": settings["addon_dir"],
                           "SOURCE_BRANCH": settings["branch"], "PACKAGE": settings["package"],
                           "IMAGE": settings["image"]}.items():
            print(f"export {key}={shlex.quote(value)}")


if __name__ == "__main__":
    main()
