from pprint import pprint
from pathlib import Path
import subprocess
import argparse
import json
import yaml
import sys
import os
import re


run_cmd = lambda cmd, *args: subprocess.run([cmd, *args], capture_output=True, text=True)
ghregex = re.compile(".*github\.com/([^/]+)/([^/\s]+).*")


def extract_gh_url(original_url: str):
    m = ghregex.match(original_url)
    if not m: return original_url

    owner, rname = m.group(1), m.group(2)
    # Sometimes urls append .git in the end and we hope here that nobody is going to
    # have an actual repo/package which name ends with '.git'
    rname = rname.removesuffix(".git")
    return f"github.com/{owner}/{rname}".lower()


def acquire_dependencies(path: str, data, fatal: bool = False):
    # @NOTE: Lockfile ('nimble.lock) file is not always present because not all projects freeze their requirements properly,
    #        so to make this work with more codebases, we use 'nimble dump --json' later and download source repositories to
    #        retreive second degree dependencies.
    out = run_cmd("find", path, "-name", "nimble.lock")
    if out.stderr: print("Linux 'find' STDERR:", out.stderr, file=sys.stderr)

    lockfiles = []
    for fp in out.stdout.strip(" \n\r\t").split("\n"):
        fp = fp.strip(" \n\r\t")
        if not fp: continue

        lockfiles.append(fp)

    print("Lockfiles:", lockfiles, file=sys.stderr)
    if lockfiles:
        for lockfile in lockfiles:
            # if not os.path.exists(lockfile): continue
            with open(lockfile) as f:
                d = json.load(f)

            manifest = lockfile.removeprefix(str(path)).strip("/")
            for name, package in d["packages"].items():
                durl = extract_gh_url(package["url"])
                if durl == data["url"]: continue

                package_deps = {"name": name, "url": durl, "version": package["version"], "deps": [], "manifest": manifest}
                data["deps"].append(package_deps)

        # @TODO: Combine methods instead of binary one or another per project. Ideally, it should try to find lockfiles,
        #        and then search for .nimble files, and if found in both searches - give priority to the lockfile on the
        #        per directory basis.
        return

    # Alternative (non-lockfile) path:
    out = run_cmd("find", path, "-name", "*.nimble")
    if out.stderr: print("Linux 'find' STDERR:", out.stderr, file=sys.stderr)

    nimbles = []
    for fp in out.stdout.strip(" \n\r\t").split("\n"):
        # fp = fp.strip(" \n\r\t").removeprefix(str(path)).strip("/")
        fp = fp.strip(" \n\r\t")
        if not fp: continue

        nimbles.append(fp)

    if not nimbles:
        if out.stdout: print("STDOUT:", out.stdout, file=sys.stderr)
        print("No 'nimble.lock' nor '*.nimble' files found!", file=sys.stderr)
        # if fatal: exit(123)
        return

    for fp in nimbles:
        manifest = fp.removeprefix(str(path)).strip("/")

        pout = run_cmd("nimble", "dump", "--json", fp)
        if pout.stderr: print("Nimble 'dump' STDERR:", pout.stderr, file=sys.stderr)

        if pout.returncode != 0:
            print("ERROR running nimble 'dump' command:", pout.stdout, file=sys.stderr)
            continue

        d = yaml.safe_load(pout.stdout)

        for pdep in d["requires"]:
            # Name here can be direct github url, or a distributed nim package (@TODO: Gitlab or any other .git url?).
            pname = pdep["name"]
            m = ghregex.match(pname)
            if m:
                # We are assigning an upublished package a nickname - repo name.
                durl = extract_gh_url(pname)
                if durl == data["url"]: continue

                pname = m.group(2)
                data["deps"].append({"name": pname, "url": durl, "version": pdep["str"], "deps": [], "manifest": manifest})
            else:
                pout = run_cmd("nimble", "search", pname)
                if pout.stderr:
                    print("STDERR:", pout.stderr, file=sys.stderr)

                # @NOTE: There are errors parsing the file, because values don't use quotes in this output,
                #        and that causes 'yaml' parse to fail. We can circuimvent this for now with a hack,
                #        by omitting fields that contain error-prone yaml data, which we also don't use.
                poutput = "\n".join(line for line in pout.stdout.split("\n") if "description:" not in line)

                pdata = yaml.safe_load(poutput).get(pname)
                if not pdata:
                    print("Failed to process dependency:", file=sys.stderr)
                    pprint(pdep, file=sys.stderr)
                    pprint(pdata, file=sys.stderr)
                    data["deps"].append({"name": pname, "url": pname, "version": pdep["str"], "deps": [], "manifest": manifest})
                    continue

                durl = extract_gh_url(pdata["url"])
                if durl == data["url"]: continue

                data["deps"].append({"name": pname, "url": durl, "version": pdep["str"], "deps": [], "manifest": manifest})


def dir_path(path: str):
    if os.path.isdir(path): return path
    raise argparse.ArgumentTypeError(f"readable_dir:{path} is not a valid path")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate nimble dependency graph")
    parser.add_argument("repository", help="The GitHub repository url")
    parser.add_argument("-i", "--input", required=True, help="Path to the nimble project root directory", type=dir_path)
    parser.add_argument("-o", "--output", help="Output json file path")
    args = parser.parse_args()

    # Before we do anything, nimble wants us to update lists.
    out = run_cmd("nimble", "refresh")
    if out.stderr: print("Nimble refresh STDERR:", out.stderr, file=sys.stderr)

    data = {"url": args.repository, "deps": []}
    acquire_dependencies(args.input, data, fatal=True)
    if not args.output:
        print(json.dumps(data))
        exit(0)

    with open(args.output, "w+") as f:
        json.dump(f, data)

