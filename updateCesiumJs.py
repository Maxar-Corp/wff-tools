#!/usr/bin/env python3

# Copyright 2022, Maxar Technologies
# Written by erik.dahlstrom@maxar.com, bjorn.blissing@maxar.com

# To update the CesiumJS for 3ts.py follow these steps
#
# First clean the old release from the wff-tools repo, keeping only the bucket.css stylesheet
# 1. cd <wff-tools-repo-path>/3tj/resources/Cesium/
# 2. rm -r !(bucket.css)
#
# Update Cesium from git repo
# 1. git clone https://github.com/CesiumGS/cesium
# 2. cd cesium (the cloned root dir)
# 3. npm install
# 4. npm run release
# 5. cp -r Build/Cesium/* <wff-tools-repo-path>/resources/Cesium/
# 6. cp <wff-tools-repo-path>/resources/style/bucket.css <wff-tools-repo-path>/resources/Cesium/

import os
import sys
import shutil
import subprocess
import argparse
import logging
import platform


def getScriptPath():
    return os.path.dirname(os.path.realpath(sys.argv[0]))


def getResourcesPath():
    return os.path.join(getScriptPath(), "resources")


def getCesiumRootPath():
    return os.path.join(getResourcesPath(), "Cesium")
    
def getStylePath():
    return os.path.join(getResourcesPath(), "style")


def removeOldCesiumFiles(allowDelete):
    rootPath = getCesiumRootPath()
    if os.path.exists(rootPath):
        for entry in os.scandir(rootPath):
            absPath = os.path.join(rootPath, entry.name)
            if entry.is_file() and entry.name != "bucket.css":
                if allowDelete:
                    os.remove(absPath)
                else:
                    logging.info(f'Will remove {absPath}')
            if entry.is_dir():
                if allowDelete:
                    shutil.rmtree(absPath)
                else:
                    logging.info(f'Will remove dir {absPath}')


def copyCesiumRelease(srcRootPath, dstRootPath):
    if not os.path.exists(dstRootPath):
        logging.debug(f'Create director: {dstRootPath}')
        os.makedirs(dstRootPath)

    for entry in os.scandir(srcRootPath):
        absPath = os.path.join(srcRootPath, entry.name)
        logging.debug(f'Copy {absPath} to {dstRootPath}')
        if entry.is_file() and entry.name != "bucket.css":
            shutil.copy(absPath, os.path.join(dstRootPath, entry.name))
        if entry.is_dir():
            shutil.copytree(absPath, os.path.join(dstRootPath, entry.name))
    # Add the bucket.css file if missing
    bucketDstPath = os.path.join(getCesiumRootPath(), "bucket.css")
    if not os.path.exists(bucketDstPath):
        bucketSrcPath = os.path.join(getStylePath(), "bucket.css")
        shutil.copy(bucketSrcPath, bucketDstPath)
        logging.debug(f'Copy {bucketSrcPath} to {bucketDstPath}')


def isGitRepoDirty(gitRepoPath):
    output = subprocess.check_output(
        ["git", "-C", gitRepoPath, "diff", "--stat"], universal_newlines=True)
    return output != ''


def setup_logging(verbosity):
    base_loglevel = 30
    verbosity = min(verbosity, 2)
    loglevel = base_loglevel - (verbosity * 10)
    logging.basicConfig(level=loglevel,
                        format='%(message)s')


if __name__ == '__main__':
    example_text = '''Example usage:
  Update Cesium first time (full clone):
    %(prog)s --clone --run-npm-install

  Update a previously cloned cesium repo:
    %(prog)s --update

  Use a manually managed cesium repo (e.g for local testing of a fix in cesium):
    %(prog)s --no-clone --no-update --build-cesium-release --copy-cesium-build
  '''

    parser = argparse.ArgumentParser(
        epilog=example_text,
        description="Updates Cesium for use with the wff-tools",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('-v', '--verbose',
                        action='count',
                        dest='verbosity',
                        default=1,
                        help="verbose output (repeat for increased verbosity)")
    parser.add_argument('-q', '--quiet',
                        action='store_const',
                        const=-1,
                        default=0,
                        dest='verbosity',
                        help="quiet output (show errors only)")
    parser.add_argument('-d', '--clean', dest='cleanOldCesiumFiles',
                        help='Delete old Cesium files in the wff-tools repo', action='store_true', default=True)
    parser.add_argument('-nd', '--no-clean', dest='cleanOldCesiumFiles',
                        help='Don\'t delete old Cesium files in the wff-tools repo', action='store_false', default=False)
    parser.add_argument('-c', '--clone', dest='cloneCesiumRepo',
                        action='store_true', help='Clone the Cesium github repo', default=False)
    parser.add_argument('-nc', '--no-clone', dest='cloneCesiumRepo',
                        action='store_false', help='Don\'t clone the Cesium github repo', default=True)
    parser.add_argument('-cb', '--cesium-branch', dest='cesiumRepoBranch',
                        help='Clone the specified branch from the Cesium GitHub repo', default='main')
    parser.add_argument('-cs', '--cesium-sha', dest='cesiumRepoSHA',
                        help='Clone the specified commit SHA from the Cesium GitHub repo')
    parser.add_argument('-u', '--update', dest='updateCesiumRepo',
                        help='Run git pull on the Cesium repo', action='store_true', default=True)
    parser.add_argument('-nu', '--no-update', dest='updateCesiumRepo',
                        help='Don\'t run git pull on the Cesium repo', action='store_false', default=False)

    parser.add_argument('-ni', '--run-npm-install', dest='runNpmInstall',
                        help='Run npm install in Cesium repo', action='store_true', default=False)
    parser.add_argument('-nni', '--no-run-npm-install', dest='runNpmInstall',
                        help='Don\'t run npm install in Cesium repo', action='store_false', default=True)
    parser.add_argument('-bc', '--build-cesium-release', dest='runBuildCesiumRelease',
                        help='Run \'npm run release\' in Cesium repo', action='store_true', default=True)
    parser.add_argument('-nbc', '--no-build-cesium-release', dest='runBuildCesiumRelease',
                        help='Don\'t run \'npm run release\' in Cesium repo', action='store_false', default=False)

    parser.add_argument('-cp', '--copy-cesium-build', dest='copyCesiumRelease',
                        help='Copy the cesium build to wff-tools repo', action='store_true', default=True)
    parser.add_argument('-ncp', '--no-copy-cesium-build', dest='copyCesiumRelease',
                        help='Don\'t copy the cesium build to wff-tools repo', action='store_false', default=False)

    parser.add_argument('-cr', '--cesium-repo-path', dest='cesiumRepoPath',
                        help='Path to local Cesium repo clone (defaults to /tmp/cesium)', default='/tmp/cesium')
    try:
        args = parser.parse_args()
        if len(sys.argv) == 1:
            parser.print_help()
            sys.exit(0)
    except Exception:
        parser.print_help()
        sys.exit(0)

    setup_logging(args.verbosity)

    logging.debug(args)

    if shutil.which("npm") is None:
        logging.error('NodeJS is not found, it is required to build cesium.')
        logging.error(
            'Make sure npm and node are possible to run in the shell, e.g running \'module add nodejs\'')
        exit(-1)
    if shutil.which("git") is None:
        logging.error(
            'git is not found. Make sure git is possible to run in the shell')
        exit(-1)

    try:
        if args.cleanOldCesiumFiles:
            logging.info('Deleting the old Cesium resources...')
            if args.verbosity > 1:
                # list the files that will be removed
                removeOldCesiumFiles(False)
            removeOldCesiumFiles(True)

        if args.cloneCesiumRepo:
            if not os.path.exists(args.cesiumRepoPath):
                if args.cesiumRepoBranch:
                    logging.info(f'Cloning Cesium git repo at branch: {args.cesiumRepoBranch}...')
                    subprocess.run(
                        ["git", "clone", "--branch", args.cesiumRepoBranch, "https://github.com/CesiumGS/cesium", args.cesiumRepoPath])                
                else:
                    logging.info('Cloning Cesium git repo ...')
                    subprocess.run(
                        ["git", "clone", "https://github.com/CesiumGS/cesium", args.cesiumRepoPath])
                # Use specific commit SHA, will result in a detached head
                if args.cesiumRepoSHA:
                    logging.info(f'Checkout specific SHA: {args.cesiumRepoSHA}...')
                    wd = os.getcwd()
                    os.chdir(args.cesiumRepoPath)
                    subprocess.run(["git", "reset", "--hard", args.cesiumRepoSHA])
                    os.chdir(wd)
            else:
                raise Exception(
                    f'The path {args.cesiumRepoPath} already exists, either run this script with --update or delete the old clone')

        if args.updateCesiumRepo:
            if not os.path.exists(args.cesiumRepoPath):
                raise Exception(
                    f'The path {args.cesiumRepoPath} is missing, run this script with --clone')
            logging.info('Updating cesium repo...')
            subprocess.run(["git", "-C", args.cesiumRepoPath, "pull"])
            subprocess.run(["git", "-C", args.cesiumRepoPath, "status"])

        if args.runNpmInstall:
            if platform.system() == 'Windows':
                wd = os.getcwd()
                os.chdir(args.cesiumRepoPath)
                logging.info(f'Running npm install for windows in {os.getcwd()}...')
                subprocess.run("npm install", shell=True)
                os.chdir(wd)
            else:
                logging.info(f'Running npm install in {args.cesiumRepoPath}...')
                subprocess.run(["npm", "--prefix", args.cesiumRepoPath, "install"])

        if args.runBuildCesiumRelease:
            if platform.system() == 'Windows':
                wd = os.getcwd()
                os.chdir(args.cesiumRepoPath)
                logging.info(
                    f'Building cesium release for windows in {args.cesiumRepoPath}...')
                subprocess.run("npm run release", shell=True)
                os.chdir(wd)
            else:
                logging.info(
                    f'Building cesium release in {args.cesiumRepoPath}...')
                subprocess.run(
                    ["npm", "--prefix", args.cesiumRepoPath, "run", "release"])

        if args.copyCesiumRelease:
            cesiumBuildOutputPath = os.path.join(
                args.cesiumRepoPath, "Build", "Cesium")
            if not os.path.exists(cesiumBuildOutputPath):
                raise Exception(
                    f'Cesium build directory not found, expected {cesiumBuildOutputPath}')
            else:
                logging.info('Copying cesium build files...')
                copyCesiumRelease(cesiumBuildOutputPath, getCesiumRootPath())
    except Exception as e:
        logging.error(f'### Error: {e}')
        exit(-1)
