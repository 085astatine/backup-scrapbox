from __future__ import annotations
import dataclasses
import logging
import pathlib
import re
from typing import Any, Generator, Literal, Optional, Tuple, TypedDict
import jsonschema
from ._json import load_json, save_json


PageOrder = Literal['as-is', 'created-asc', 'created-desc']
InternalLinkType = Literal['page', 'word']


class BackupInfoJSON(TypedDict):
    id: str
    backuped: int
    totalPages: int
    totalLinks: int


def jsonschema_backup_info() -> dict[str, Any]:
    schema = {
      'type': 'object',
      'required': ['id', 'backuped'],
      'additionalProperties': False,
      'properties': {
        'id': {'type': 'string'},
        'backuped': {'type': 'integer'},
        'totalPages': {'type': 'integer'},
        'totalLinks': {'type': 'integer'},
      },
    }
    return schema


class BackupPageLineJSON(TypedDict):
    text: str
    created: int
    updated: int


def jsonschema_backup_page_line() -> dict[str, Any]:
    schema = {
      'type': 'object',
      'requred': ['text', 'created', 'updated'],
      'additionalProperties': False,
      'properties': {
        'text': {'type': 'string'},
        'created': {'type': 'integer'},
        'updated': {'type': 'integer'},
      },
    }
    return schema


class BackupPageJSON(TypedDict):
    title: str
    created: int
    updated: int
    id: str
    lines: list[str] | list[BackupPageLineJSON]
    linksLc: list[str]


def page_lines(page: BackupPageJSON) -> Generator[str, None, None]:
    for line in page['lines']:
        match line:
            case str():
                yield line
            case {'text': text}:
                yield text


def jsonschema_backup_page() -> dict[str, Any]:
    schema = {
      'type': 'object',
      'required': ['title', 'created', 'updated', 'lines'],
      'additionalProperties': False,
      'properties': {
        'title': {'type': 'string'},
        'created': {'type': 'integer'},
        'updated': {'type': 'integer'},
        'id': {'type': 'string'},
        'lines': {
          'oneOf': [
            {
              'type': 'array',
              'items': {'type': 'string'},
            },
            {
              'type': 'array',
              'items': jsonschema_backup_page_line(),
            },
          ],
        },
        'linksLc': {
          'type': 'array',
          'items': {'type': 'string'},
        },
      },
    }
    return schema


class BackupJSON(TypedDict):
    name: str
    displayName: str
    exported: int
    pages: list[BackupPageJSON]


def jsonschema_backup() -> dict[str, Any]:
    schema = {
      'type': 'object',
      'required': ['name', 'displayName', 'exported', 'pages'],
      'additionalProperties': False,
      'properties': {
        'name': {'type': 'string'},
        'displayName': {'type': 'string'},
        'exported': {'type': 'integer'},
        'pages': {
          'type': 'array',
          'items': jsonschema_backup_page(),
        },
      },
    }
    return schema


@dataclasses.dataclass
class Location:
    title: str
    line: int


def jsonschema_location() -> dict[str, Any]:
    schema = {
        'type': 'object',
        'required': ['title', 'line'],
        'additionalProperties': False,
        'properties': {
            'title': {'type': 'string'},
            'line': {'type': 'integer'},
        },
    }
    return schema


@dataclasses.dataclass
class InternalLinkNode:
    name: str
    type: InternalLinkType


@dataclasses.dataclass
class InternalLink:
    node: InternalLinkNode
    to_links: list[InternalLinkNode]


@dataclasses.dataclass
class ExternalLink:
    url: str
    locations: list[Location]


class Backup:
    def __init__(
            self,
            project: str,
            directory: pathlib.Path,
            backup: BackupJSON,
            info: Optional[BackupInfoJSON]) -> None:
        self._project = project
        self._directory = directory
        self._backup = backup
        self._info = info
        # JSON Schema validation
        jsonschema.validate(
                instance=self._backup,
                schema=jsonschema_backup())
        if self._info is not None:
            jsonschema.validate(
                    instance=self._info,
                    schema=jsonschema_backup_info())

    @property
    def project(self) -> str:
        return self._project

    @property
    def directory(self) -> pathlib.Path:
        return self._directory

    @property
    def timestamp(self) -> int:
        return self._backup['exported']

    @property
    def data(self) -> BackupJSON:
        return self._backup

    @property
    def info(self) -> Optional[BackupInfoJSON]:
        return self._info

    def page_titles(self) -> list[str]:
        return sorted(page['title'] for page in self._backup['pages'])

    def internal_links(self) -> list[InternalLink]:
        # page
        pages = dict(
                (_normalize_page_title(page), page)
                for page in self.page_titles())
        # links
        links: list[InternalLink] = []
        for page in self._backup['pages']:
            to_links = sorted(
                    (InternalLinkNode(
                            name=pages.get(link, link),
                            type=('page'
                                  if _normalize_page_title(link) in pages
                                  else 'word'))
                        for link in page['linksLc']),
                    key=lambda node: node.name)
            links.append(InternalLink(
                    node=InternalLinkNode(name=page['title'], type='page'),
                    to_links=to_links))
        links.sort(key=lambda link: link.node.name)
        return links

    def external_links(self) -> list[ExternalLink]:
        # regex
        regex = re.compile(r'https?://[^\s\]]+')
        # links
        links: list[ExternalLink] = []
        for page in self._backup['pages']:
            for line, location in _filter_code(page):
                for url in regex.findall(line):
                    found = next(
                            (link for link in links if link.url == url),
                            None)
                    if found is not None:
                        found.locations.append(location)
                    else:
                        links.append(ExternalLink(
                                url=url,
                                locations=[location]))
        links.sort(key=lambda link: link.url)
        return links

    def sort_pages(
            self,
            order: Optional[PageOrder] = None) -> None:
        match order:
            case None | 'as-is':
                pass
            case 'created-asc':
                self._backup['pages'].sort(key=lambda page: page['created'])
            case 'created-desc':
                self._backup['pages'].sort(key=lambda page: - page['created'])

    def save_files(self) -> list[pathlib.Path]:
        files: list[pathlib.Path] = []
        # {project}.json
        backup_path = self.directory.joinpath(
                f'{_escape_filename(self.project)}.json')
        files.append(backup_path)
        # {project}.info.json
        if self._info is not None:
            files.append(backup_path.with_suffix('.info.json'))
        # pages
        page_directory = self.directory.joinpath('pages')
        for page in self._backup['pages']:
            files.append(page_directory.joinpath(
                    f'{_escape_filename(page["title"])}.json'))
        return files

    def save(
            self,
            *,
            logger: Optional[logging.Logger] = None) -> None:
        logger = logger or logging.getLogger(__name__)
        # {project}.json
        backup_path = self.directory.joinpath(
                f'{_escape_filename(self.project)}.json')
        logger.debug(f'save "{backup_path.as_posix()}"')
        save_json(backup_path, self._backup)
        # {project}.info.json
        if self._info is not None:
            info_path = backup_path.with_suffix('.info.json')
            logger.debug(f'save "{info_path.as_posix()}"')
            save_json(info_path, self._info)
        # pages
        page_directory = self.directory.joinpath('pages')
        for page in self._backup['pages']:
            page_path = page_directory.joinpath(
                    f'{_escape_filename(page["title"])}.json')
            logger.debug(f'save "{page_path.as_posix()}"')
            save_json(page_path, page)

    @classmethod
    def load(
            cls,
            project: str,
            directory: pathlib.Path) -> Optional[Backup]:
        # {project}.json
        backup_path = directory.joinpath(f'{_escape_filename(project)}.json')
        backup: Optional[BackupJSON] = load_json(
                backup_path,
                schema=jsonschema_backup())
        if backup is None:
            return None
        # {project}.info.json
        info_path = backup_path.with_suffix('.info.json')
        info: Optional[BackupInfoJSON] = load_json(
                info_path,
                schema=jsonschema_backup_info())
        return cls(
                project,
                directory,
                backup,
                info)


@dataclasses.dataclass
class DownloadedBackup:
    timestamp: int
    backup_path: pathlib.Path
    info_path: Optional[pathlib.Path]

    def load_backup(self) -> Optional[BackupJSON]:
        return load_json(
                self.backup_path,
                schema=jsonschema_backup())

    def load_info(self) -> Optional[BackupInfoJSON]:
        if self.info_path is None:
            return None
        return load_json(
                self.info_path,
                schema=jsonschema_backup_info())

    def load(
            self,
            project: str,
            directory: pathlib.Path) -> Optional[Backup]:
        backup = self.load_backup()
        info = self.load_info()
        if backup is None:
            return None
        return Backup(
                project,
                directory,
                backup,
                info)


class BackupStorage:
    def __init__(self, directory: pathlib.Path) -> None:
        self._directory = directory

    def backup_path(self, timestamp: int) -> pathlib.Path:
        return self._directory.joinpath(f'{timestamp}.json')

    def info_path(self, timestamp: int) -> pathlib.Path:
        return self._directory.joinpath(f'{timestamp}.info.json')

    def exists(self, timestamp: int) -> bool:
        return self.backup_path(timestamp).exists()

    def backups(self) -> list[DownloadedBackup]:
        backups: list[DownloadedBackup] = []
        for path in self._directory.iterdir():
            # check if the path is file
            if not path.is_file():
                continue
            # check if the filename is '{timestamp}.json'
            filename_match = re.match(
                    r'^(?P<timestamp>\d+)\.json$',
                    path.name)
            if filename_match is None:
                continue
            timestamp = int(filename_match.group('timestamp'))
            # info path
            info_path = self.info_path(timestamp)
            backups.append(DownloadedBackup(
                    timestamp=timestamp,
                    backup_path=path,
                    info_path=info_path if info_path.exists() else None))
        # sort by old...new
        return sorted(backups, key=lambda backup: backup.timestamp)


def _escape_filename(text: str) -> str:
    table: dict[str, int | str | None] = {
            ' ': '_',
            '#': '%23',
            '%': '%25',
            '/': '%2F'}
    return text.translate(str.maketrans(table))


def _normalize_page_title(title: str) -> str:
    return title.lower().replace(' ', '_')


def _filter_code(
        page: BackupPageJSON) -> Generator[Tuple[str, Location], None, None]:
    title = page['title']
    # regex
    code_block = re.compile(r'(?P<indent>(\t| )*)code:.+')
    cli_notation = re.compile(r'(\t| )*(\$|%) .+')
    code_snippets = re.compile(r'`.*?`')
    indent = re.compile(r'(\t| )*')
    # code block
    code_block_indent_level: Optional[int] = None
    # iterate lines
    for i, line in enumerate(page_lines(page)):
        # in code block
        if code_block_indent_level is not None:
            indent_match = indent.match(line)
            indent_level = (
                    len(indent_match.group())
                    if indent_match is not None
                    else 0)
            # end code block
            if indent_level <= code_block_indent_level:
                code_block_indent_level = None
            else:
                continue
        # start code_block
        if code_block_match := code_block.match(line):
            code_block_indent_level = len(code_block_match.group('indent'))
            continue
        # CLI notation
        if cli_notation.match(line):
            continue
        # code snippets
        line = code_snippets.sub(' ', line)
        yield line, Location(title=title, line=i)
