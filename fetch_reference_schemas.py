"""Fetch the published IFC releases that the change log compares against.

The EXPRESS schemas and property set definitions of the earlier IFC releases
are published in buildingSMART/Standards-builds, the repository behind
standards.buildingsmart.org. This script copies the releases older than the
version being built into <repo>/reference_schemas, where change_log.py reads
them. The lists of deprecated entities are not published there; they are kept
in reference_data/ next to this script.

    python fetch_reference_schemas.py <repo> [<Standards-builds checkout>]

Without a checkout, or when the checkout does not hold the releases (a fork
that publishes somewhere else), only the files that are needed are downloaded
from GitHub. What is already in reference_schemas is left alone.
"""
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

CODE_DIR = os.path.dirname(os.path.abspath(__file__))
STANDARDS_BUILDS = "https://github.com/buildingSMART/Standards-builds"

# Every published version, oldest first: the version, the names change_log.py
# knows it by (schema, deprecated entities, property set folder) and where the
# schema and the property sets are in Standards-builds. The property sets are
# in one or more folders of XML files, or in a zip.
RELEASES = [
    ((2, 3), "IFC2X3_TC1.exp", "deprecated_entities_Ifc2.3.0.1.json", "psd_IFC2x3",
     "IFC/RELEASE/IFC2x3/TC1/EXPRESS/IFC2X3_TC1.exp",
     ["IFC/RELEASE/IFC2x3/TC1/PSD"]),
    ((4, 0), "IFC4_ADD2_TC1.exp", "deprecated_entities_Ifc4.0.2.2.json", "psd_IFC4_ADD2_TC1",
     "IFC/RELEASE/IFC4/ADD2_TC1/EXPRESS/IFC4.exp",
     ["IFC/RELEASE/IFC4/ADD2_TC1/HTML/psd", "IFC/RELEASE/IFC4/ADD2_TC1/HTML/qto"]),
    ((4, 1), "IFC4x1.exp", "deprecated_entities_Ifc4.0.2.2.json", "psd_IFC4x1",
     "IFC/RELEASE/IFC4_1/FINAL/EXPRESS/IFC4x1.exp",
     ["IFC/RELEASE/IFC4_1/FINAL/HTML/psd", "IFC/RELEASE/IFC4_1/FINAL/HTML/qto"]),
    ((4, 2), "IFC4x2.exp", "deprecated_entities_Ifc4.2.0.1.json", "psd_IFC4x2",
     "IFC/RELEASE/IFC4_2/FINAL/EXPRESS/IFC4x2.exp",
     ["IFC/RELEASE/IFC4_2/FINAL/HTML/psd", "IFC/RELEASE/IFC4_2/FINAL/HTML/qto"]),
    ((4, 3), "IFC4X3_ADD2.exp", "deprecated_entities_Ifc4.3.2.0.json", "psd_IFC4x3",
     "IFC/RELEASE/IFC4_3/HTML/IFC4X3_ADD2.exp",
     ["IFC/RELEASE/IFC4_3/HTML/annex-a-psd.zip"]),
]


def is_complete(release, target):
    _, schema, deprecated, psd, _, _ = release
    return (
        os.path.isfile(os.path.join(target, schema))
        and os.path.isfile(os.path.join(target, deprecated))
        and os.path.isdir(os.path.join(target, psd))
    )


def holds(checkout, releases):
    return all(
        os.path.exists(os.path.join(checkout, path))
        for _, _, _, _, schema_path, psd_paths in releases
        for path in [schema_path] + psd_paths
    )


def clone(releases, directory):
    """Shallow clone of Standards-builds that downloads only the files of these releases."""
    patterns = []
    for _, _, _, _, schema_path, psd_paths in releases:
        patterns.append("/" + schema_path)
        patterns.extend("/" + p + ("" if p.endswith(".zip") else "/") for p in psd_paths)
    git = ["git", "-C", directory]
    subprocess.check_call(["git", "clone", "--quiet", "--depth", "1", "--filter=blob:none", "--no-checkout", STANDARDS_BUILDS, directory])
    # A sparse checkout set up by hand: the sparse-checkout command and its
    # defaults differ between git versions, the configuration underneath does not.
    subprocess.check_call(git + ["config", "core.sparseCheckout", "true"])
    subprocess.check_call(git + ["config", "core.sparseCheckoutCone", "false"])
    os.makedirs(os.path.join(directory, ".git", "info"), exist_ok=True)
    with open(os.path.join(directory, ".git", "info", "sparse-checkout"), "w") as f:
        f.write("\n".join(patterns) + "\n")
    subprocess.check_call(git + ["checkout", "--quiet", "HEAD"])


def remove(directory):
    """Delete a clone. Git marks its object files read-only, which stops rmtree on Windows."""
    def make_writable(function, path, _):
        os.chmod(path, stat.S_IWRITE)
        function(path)
    shutil.rmtree(directory, onerror=make_writable)


def copy_file(source, target):
    # under another name first, so that a file that exists is complete
    shutil.copyfile(source, target + ".partial")
    os.replace(target + ".partial", target)


def copy_property_sets(sources, directory):
    """All property set XML files of a release in one flat folder."""
    for source in sources:
        if source.endswith(".zip"):
            with zipfile.ZipFile(source) as archive:
                for member in sorted(archive.namelist()):
                    if member.lower().endswith(".xml"):
                        write(os.path.join(directory, os.path.basename(member)), archive.read(member))
        else:
            for parent, folders, names in os.walk(source):
                folders.sort()
                for name in sorted(names):
                    if name.lower().endswith(".xml"):
                        with open(os.path.join(parent, name), "rb") as f:
                            write(os.path.join(directory, name), f.read())


def write(filename, data):
    if os.path.exists(filename):
        raise RuntimeError(f"{os.path.basename(filename)} occurs twice in the same release")
    with open(filename, "wb") as f:
        f.write(data)


def copy_release(release, checkout, target):
    _, schema, deprecated, psd, schema_path, psd_paths = release
    if not os.path.isfile(os.path.join(target, schema)):
        copy_file(os.path.join(checkout, schema_path), os.path.join(target, schema))
    if not os.path.isfile(os.path.join(target, deprecated)):
        copy_file(os.path.join(CODE_DIR, "reference_data", deprecated), os.path.join(target, deprecated))
    if not os.path.isdir(os.path.join(target, psd)):
        # filled next to its final place and renamed, so a folder that exists is complete
        partial = os.path.join(target, psd + ".partial")
        shutil.rmtree(partial, ignore_errors=True)
        os.makedirs(partial)
        copy_property_sets([os.path.join(checkout, p) for p in psd_paths], partial)
        os.rename(partial, os.path.join(target, psd))
    return len(os.listdir(os.path.join(target, psd)))


def fetch(repo_dir, checkout=None):
    os.environ["REPO_DIR"] = repo_dir
    from version import version_tuple

    target = os.path.join(repo_dir, "reference_schemas")
    os.makedirs(target, exist_ok=True)
    releases = [r for r in RELEASES if r[0] < tuple(version_tuple[:2])]
    missing = [r for r in releases if not is_complete(r, target)]
    if not missing:
        print(f"reference_schemas: {len(releases)} releases present")
        return

    temporary = None
    try:
        if checkout and holds(checkout, missing):
            origin = os.path.abspath(checkout)
        else:
            if checkout:
                print(f"{checkout} does not hold the releases")
            temporary = checkout = tempfile.mkdtemp(prefix="standards-builds-")
            origin = STANDARDS_BUILDS
            clone(missing, checkout)
        for release in missing:
            count = copy_release(release, checkout, target)
            print(f"reference_schemas: {release[1]} and {count} property sets from {origin}")
    finally:
        if temporary:
            remove(temporary)


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    fetch(os.path.abspath(sys.argv[1]), *sys.argv[2:])
