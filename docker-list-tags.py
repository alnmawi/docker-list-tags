#!/usr/bin/env python3
# Copyright (C) 2020 Marcin Wrzeszcz
#
# This file is part of docker-list-tags.
#
# docker-list-tags is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# docker-list-tags is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with docker-list-tags.  If not, see <http://www.gnu.org/licenses/>.

import argparse
import json
import re
import sys
import urllib.request
from urllib.error import HTTPError
from urllib.parse import urlencode


class Registry:
    def __init__(self, url="https://index.docker.io", token=None):
        self.url = url
        self.token = token

    def get_token(self, url, service, scope):
        params = urlencode({"service": service, "scope": scope})
        request = urllib.request.Request(url + "?" + params)
        response = urllib.request.urlopen(request)
        if response.code != 200:
            raise HTTPError(
                response.url,
                response.code,
                "Could not get auth token",
                response.headers,
                response.fp,
            )
        self.token = json.load(response)["token"]

    def api_call(self, path, method="GET", headers=None):
        headers = headers or {}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token

        request = urllib.request.Request(
            self.url + path, method=method, headers=headers
        )
        try:
            response = urllib.request.urlopen(request)
        except HTTPError as exception:
            if exception.code != 401:
                raise exception

            auth = exception.fp.getheader("WWW-Authenticate")
            match = re.search(r"Bearer\s+", auth)
            if not match:
                raise exception

            auth = auth[match.end() :]
            match = re.findall(r'(\w+)=(?:([^ ",]+)|"([^"]+)")', auth)
            match = {group[0]: group[1] or group[2] for group in match}
            self.get_token(match["realm"], match["service"], match["scope"])

            headers["Authorization"] = "Bearer " + self.token

            request = urllib.request.Request(
                self.url + path, method=method, headers=headers
            )
            response = urllib.request.urlopen(request)

        return response

    def list_tags(self, name):
        response = self.api_call("/v2/{}/tags/list".format(name))
        return json.load(response)["tags"]

    def get_manifests_list_digest(self, name, ref):
        response = self.api_call(
            "/v2/{}/manifests/{}".format(name, ref),
            method="HEAD",
            headers={
                "Accept": "application/vnd.docker.distribution.manifest.list.v2+json"
            },
        )
        return response.getheader("Docker-Content-Digest")

    def list_images(self, name):
        tags = self.list_tags(name)
        images = {}
        for tag in tags:
            digest = self.get_manifests_list_digest(name, tag)
            images.setdefault(digest, []).append(tag)

        return images


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "name", metavar="NAME[:TAG|@DIGEST]", help="image or repository to list"
    )
    parser.add_argument(
        "-a", "--all", action="store_true", help="list all images in repository"
    )
    parser.add_argument(
        "-t",
        "--token",
        help="custom authorization token",
    )
    parser.add_argument(
        "-u", "--url", default="https://index.docker.io", help="custom registry url"
    )

    args = parser.parse_args()

    reg = Registry(args.url, args.token)

    name, _, tag = args.name.partition("@")
    if not tag:
        name, _, tag = args.name.partition(":")
    if not tag:
        tag = "latest"
    if args.all:
        tag = None
    if "/" not in name:
        name = "library/" + name

    try:
        if tag:
            digest = reg.get_manifests_list_digest(name, tag)

        images = reg.list_images(name)

        if tag:
            print(" ".join(images[digest]))
        else:
            for digest, tags in images.items():
                print(digest + ": " + " ".join(tags))
    except HTTPError as exception:
        print(exception)
        data = exception.fp.read()
        if data:
            data = json.loads(data)
            for error in data["errors"]:
                print("{}: {}".format(error["code"], error["message"]))
                print("details: {!r}".format(error["detail"]))

        sys.exit(1)
