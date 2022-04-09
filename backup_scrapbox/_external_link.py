import asyncio
import dataclasses
import logging
import pathlib
import time
from typing import Any, Literal, Optional
import aiohttp
from ._backup import ExternalLink, Location, jsonschema_location
from ._json import save_json


@dataclasses.dataclass
class ResponseLog:
    status_code: int
    content_type: Optional[str]


def jsonschema_response_log() -> dict[str, Any]:
    schema = {
        'type': 'object',
        'required': ['status_code', 'content_type'],
        'additionalProperties': False,
        'properties': {
            'status_code': {'type': 'integer'},
            'content_type': {'type': ['string', 'null']},
        },
    }
    return schema


@dataclasses.dataclass
class ExternalLinkLog:
    url: str
    locations: list[Location]
    access_timestamp: int
    response: Literal['error'] | ResponseLog


def jsonschema_external_link_log() -> dict[str, Any]:
    schema = {
        'type': 'object',
        'required': ['url', 'response'],
        'additionalProperties': False,
        'properties': {
            'url': {'type': 'string'},
            'access_timestamp': {'type': 'integer'},
            'locations': {
                'type': 'array',
                'items': jsonschema_location(),
            },
            'response': {
                'oneOf': [
                    {'type': 'string', 'enum': ['error']},
                    jsonschema_response_log(),
                ],
            },
        },
    }
    return schema


def jsonschema_external_link_logs() -> dict[str, Any]:
    schema = {
        'type': 'array',
        'items': jsonschema_external_link_log(),
    }
    return schema


def save_external_links(
        links: list[ExternalLink],
        *,
        parallel_limit: int = 5,
        timeout_seconds: float = 30.0,
        logger: Optional[logging.Logger] = None) -> None:
    logger = logger or logging.getLogger(__name__)
    # request
    logs = asyncio.run(_request_external_links(
            links,
            parallel_limit,
            timeout_seconds,
            logger))
    # save
    save_path = pathlib.Path('links.json')
    save_json(
            save_path,
            [dataclasses.asdict(log) for log in logs],
            schema=jsonschema_external_link_logs())


async def _request_external_links(
        links: list[ExternalLink],
        parallel_limit: int,
        timeout_seconds: float,
        logger: logging.Logger) -> list[ExternalLinkLog]:
    # timeout
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    # semaphore
    semaphore = asyncio.Semaphore(parallel_limit)

    # parallel requests
    async def _parallel_request(
            session: aiohttp.ClientSession,
            index: int,
            link: ExternalLink,
            logger: logging.Logger) -> ExternalLinkLog:
        async with semaphore:
            return await _request(session, index, link, logger)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        tasks = [
                _parallel_request(session, i, link, logger)
                for i, link in enumerate(links)]
        return await asyncio.gather(*tasks)


async def _request(
        session: aiohttp.ClientSession,
        index: int,
        link: ExternalLink,
        logger: logging.Logger) -> ExternalLinkLog:
    logger.debug(f'request({index}): url={link.url}')
    # access timestamp
    access_timestamp = int(time.time())
    # request
    try:
        async with session.get(link.url) as response:
            logger.debug(f'request({index}): status={response.status}')
            response_log = ResponseLog(
                    status_code=response.status,
                    content_type=response.headers.get('content-type'))
            logger.debug(f'request({index}): response={response_log}')
            return ExternalLinkLog(
                url=link.url,
                locations=link.locations,
                access_timestamp=access_timestamp,
                response=response_log)
    except (asyncio.TimeoutError, aiohttp.ClientError) as error:
        logger.debug(f'request({index}): '
                     f'error={error.__class__.__name__}({error})')
        return ExternalLinkLog(
                url=link.url,
                locations=link.locations,
                access_timestamp=access_timestamp,
                response='error')
