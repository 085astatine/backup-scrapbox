import logging
import pathlib
import subprocess
from typing import Optional
from ._env import Env
from ._git import Git, Commit
from ._json import BackupJSON, jsonschema_backup, parse_json, save_json
from ._utility import format_timestamp


def export(
        env: Env,
        destination: pathlib.Path,
        logger: logging.Logger) -> None:
    git = env.git(logger=logger)
    # check if the destination exists
    if not destination.exists():
        logger.error(
                f'export directory "{destination.as_posix()}" does not exist')
        return
    # commits
    commits = git.commits()
    if commits:
        logger.info(
                f'{len(commits)} commits:'
                f' {format_timestamp(commits[0].timestamp)}'
                f' ~ {format_timestamp(commits[-1].timestamp)}')
    else:
        logger.info('there are no commits')
    # export
    for commit in commits:
        logger.info(f'export {format_timestamp(commit.timestamp)}')
        _export(env.project,
                git,
                commit,
                destination,
                logger)


def _export(
        project: str,
        git: Git,
        commit: Commit,
        destination: pathlib.Path,
        logger: logging.Logger) -> None:
    # get backup.json
    command = ['git', 'show', '-z', f'{commit.hash}:{project}.json']
    try:
        process = git.execute(command)
    except subprocess.CalledProcessError:
        logger.warning('skip commit: %s', commit.hash)
        return
    backup_json: Optional[BackupJSON] = parse_json(
            process.stdout,
            schema=jsonschema_backup())
    # save backup.json
    backup_json_path = destination.joinpath(f'{commit.timestamp}.json')
    save_json(backup_json_path, backup_json)
    logger.debug('save %s', backup_json_path)
    # save backup.info.json
    info_json_path = destination.joinpath(f'{commit.timestamp}.info.json')
    info_json = commit.backup_info()
    if info_json is not None:
        save_json(info_json_path, info_json)
