# Copyright Materialize, Inc. and contributors. All rights reserved.
#
# Use of this software is governed by the Business Source License
# included in the LICENSE file at the root of this repository.
#
# As of the Change Date specified in that file, in accordance with
# the Business Source License, use of this software will be governed
# by the Apache License, Version 2.0.

import os
from pathlib import Path

from ci import tarball_uploader
from ci.deploy.deploy_util import rust_version
from materialize import mzbuild, spawn, ui
from materialize.rustc_flags import Sanitizer

from . import deploy_util


def main() -> None:
    bazel = ui.env_is_truthy("CI_BAZEL_BUILD")
    bazel_remote_cache = os.getenv("CI_BAZEL_REMOTE_CACHE")
    bazel_lto = ui.env_is_truthy("CI_BAZEL_LTO")

    repo = mzbuild.Repository(
        Path("."),
        coverage=False,
        sanitizer=Sanitizer.none,
        bazel=bazel,
        bazel_remote_cache=bazel_remote_cache,
        bazel_lto=bazel_lto,
    )
    target = f"{repo.rd.arch}-unknown-linux-gnu"

    print("--- Building mz-debug")
    # The bin/ci-builder uses target-xcompile as the volume and
    # is where the binary release will be available.
    path = Path("target-xcompile") / "release" / "mz-debug"
    spawn.runv(
        ["cargo", "build", "--bin", "mz-debug", "--release"],
        env=dict(os.environ, RUSTUP_TOOLCHAIN=rust_version()),
    )
    mzbuild.chmod_x(path)

    print(f"--- Uploading {target} binary tarball")
    uploader = tarball_uploader.TarballUploader(
        package_name="mz-debug",
        version=deploy_util.MZ_DEBUG_VERSION,
    )
    uploader.deploy_tarball(target, path)


if __name__ == "__main__":
    main()
