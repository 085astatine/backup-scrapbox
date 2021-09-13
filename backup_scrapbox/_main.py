# -*- config: utf-8 -*-

import argparse
import logging
import sys
from typing import Final, Optional
from ._env import Env, load_env
from ._download import download


_REQUEST_INTERVAL: Final[float] = 3.0


def backup_scrapbox(
        env: Env,
        *,
        logger: Optional[logging.Logger] = None,
        request_interval: float = _REQUEST_INTERVAL) -> None:
    logger = logger or logging.getLogger(__name__)
    logger.info('backup-scrapbox')
    # download backup
    download(env, logger, request_interval)


def main() -> None:
    # logger
    logger = logging.getLogger('backup-scrapbox')
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.formatter = logging.Formatter(
            fmt='%(asctime)s %(name)s:%(levelname)s:%(message)s')
    logger.addHandler(handler)
    # option
    option = _argument_parser().parse_args()
    if option.verbose:
        logger.setLevel(logging.DEBUG)
    logger.debug('option: %s', option)
    # .env
    try:
        env = load_env(option.env, logger=logger)
    except Exception as error:
        sys.stderr.write(f'invalid env file: {option.env}\n')
        sys.stderr.write('{0}\n'.format('\n'.join(
                ' ' * 4 + message
                for message in str(error).split('\n')
                if message)))
        sys.exit(1)
    # main
    backup_scrapbox(
            env,
            logger=logger,
            request_interval=option.request_interval)


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    # env
    parser.add_argument(
            '--env',
            dest='env',
            default='.env',
            metavar='DOTENV',
            help='env file (default .env)')
    # verbose
    parser.add_argument(
            '-v', '--verbose',
            dest='verbose',
            action='store_true',
            help='set log level to debug')
    # request interval
    parser.add_argument(
            '--request-interval',
            dest='request_interval',
            type=float,
            default=_REQUEST_INTERVAL,
            metavar='SECONDS',
            help=f'request interval seconds (default {_REQUEST_INTERVAL})')
    return parser
