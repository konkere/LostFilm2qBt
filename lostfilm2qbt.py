#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import json
import pycurl
import calendar
from sys import exit
import qbittorrentapi
from time import sleep
from io import BytesIO
from time import gmtime
from os import path, getenv, mkdir
from configparser import ConfigParser
from bencoder import bencode, bdecode
from feedparser import parse as parse_feed


def announce_info(announce_key):
    pieces = ('tracker.php/', '/announce')
    bad = bytes(pieces[0] + pieces[1], 'UTF-8')
    if announce_key:
        good = bytes(pieces[0] + announce_key + pieces[1], 'UTF-8')
    else:
        good = False
    announce = {
        'bad': bad,
        'good': good,
    }
    return announce


def fix_announcers(torrent, announce):
    torrent_decode = bdecode(torrent)
    announcers = torrent_decode[b'announce-list']
    for ann_id, ann in enumerate(announcers):
        announce_fix = [ann[0].replace(announce['bad'], announce['good'])]
        announcers[ann_id] = announce_fix
    torrent_encode = bencode(torrent_decode)
    return torrent_encode


class Conf:

    def __init__(self):
        self.work_dir = path.join(getenv('HOME'), '.config', 'LostFilm2qBt')
        self.config_file = path.join(self.work_dir, 'settings.conf')
        self.download_roster = path.join(self.work_dir, 'download.list')
        self.config = ConfigParser()
        self.exist()
        self.config.read(self.config_file)
        self.roster = self.read_roster()
        self.source_rss = self.read_config('LostFilm', 'source')
        self.quality = f'[{self.read_config("LostFilm", "quality")}]'
        self.cookie = f'uid={self.read_config("LostFilm", "uid")}; usess={self.read_config("LostFilm", "usess")}'
        self.announce = announce_info(self.read_config('LostFilm', 'announcekey'))
        self.host = self.read_config('qBittorrent', 'host')
        self.username = self.read_config('qBittorrent', 'username')
        self.password = self.read_config('qBittorrent', 'password')
        self.category = self.read_config('qBittorrent', 'category')
        self.savepath = self.read_config('qBittorrent', 'savepath')
        self.entries_db_file = path.join(self.work_dir, 'entries.db')
        try:
            self.entries_db = json.load(open(self.entries_db_file))
        except FileNotFoundError:
            self.entries_db = {}
        self.pattern_show_name_season = r'^.+\((.+)\).+ \(S(\d{1,3})E\d{1,3}\) \[.+\]'
        self.pattern_movie_name = r'^.+\((.+)\).+\(Фильм\) \[.+\]'
        self.entries = []

    def exist(self):
        if not path.isdir(self.work_dir):
            mkdir(self.work_dir)
        if not path.exists(self.config_file):
            try:
                self.create_config()
            except FileNotFoundError as exc:
                print(exc)
        if not path.exists(self.download_roster):
            try:
                self.create_roster()
            except FileNotFoundError as exc:
                print(exc)

    def create_config(self):
        self.config.add_section('LostFilm')
        self.config.set('LostFilm', 'source', 'http://retre.org/rssdd.xml')
        self.config.set('LostFilm', 'quality', '1080p')
        self.config.set('LostFilm', 'uid', 'LostFilmUID')
        self.config.set('LostFilm', 'usess', 'LostFilmUSESS')
        self.config.set('LostFilm', 'announcekey', '')
        self.config.add_section('qBittorrent')
        self.config.set('qBittorrent', 'host', 'qBtHostURL:port')
        self.config.set('qBittorrent', 'username', 'qBtUsername')
        self.config.set('qBittorrent', 'password', 'qBtPassword')
        self.config.set('qBittorrent', 'category', 'shows')
        self.config.set('qBittorrent', 'savepath', '/path/to/shows/dir/')
        with open(self.config_file, 'w') as file:
            self.config.write(file)
        raise FileNotFoundError(f'Required to fill data in config: {self.config_file}')

    def read_config(self, section, setting):
        value = self.config.get(section, setting)
        return value

    def create_roster(self):
        shows = (
                'Best Show Name\n' +
                'Another Best Show Name/Y2022\n' +
                'Yet Another Best Show Name/S03-04\n' +
                'Also Best Show Name/S00-06/Y2022'
        )
        with open(self.download_roster, 'w') as file:
            file.write(shows)
        raise FileNotFoundError(
            f'Required to fill list of shows in: {self.download_roster}.\n'
            f'One line — one show.\n'
            f'At the end of line:\n'
            f'"/S__-__" or "S__" (optional season(s) for download),\n'
            f'"/Y____" (optional, for destination dir).'
        )

    def read_roster(self):
        roster = {}
        with open(self.download_roster) as file:
            for line in file:
                if line == '\n' or line == '':
                    continue
                elif '/y' in line.lower() and '/s' in line.lower():
                    pattern = r'(.+)\/[Ss](\d{1,2})-?(\d{1,2})?\/[Yy](\d+$)'
                    re_line = re.match(pattern, line)
                    show_name = re_line.group(1)
                    season_start = int(re_line.group(2))
                    season_end = int(re_line.group(3)) if re_line.group(3) else season_start
                    seasons = [season_start, season_end]
                    seasons.sort()
                    show_year = re_line.group(4)
                    roster[show_name] = {
                        'dir': f'{show_name} ({show_year})',
                        'seasons': seasons,
                    }
                elif '/s' in line.lower():
                    pattern = r'(.+)\/[Ss](\d{1,2})-?(\d{1,2})?'
                    re_line = re.match(pattern, line)
                    show_name = re_line.group(1)
                    season_start = int(re_line.group(2))
                    season_end = int(re_line.group(3)) if re_line.group(3) else season_start
                    seasons = [season_start, season_end]
                    seasons.sort()
                    roster[show_name] = {
                        'dir': show_name,
                        'seasons': seasons,
                    }
                elif '/y' in line.lower():
                    pattern = r'(.+)\/[Yy](\d+$)'
                    re_line = re.match(pattern, line)
                    show_name = re_line.group(1)
                    show_year = re_line.group(2)
                    roster[show_name] = {
                        'dir': f'{show_name} ({show_year})',
                        'seasons': [0, 99],
                    }
                else:
                    pattern = r'(^.+)'
                    show_name = re.match(pattern, line).group(1)
                    roster[show_name] = {
                        'dir': show_name,
                        'seasons': [0, 99]
                    }
        return roster


class ParserRSS:

    def __init__(self, settings):
        self.old_entries_delta = (2678400 * 3)  # one month x3
        self.old_entries_frontier = calendar.timegm(gmtime()) - self.old_entries_delta
        self.settings = settings
        self.feed = parse_feed(self.settings.source_rss)

    def source_online(self):
        if self.feed['status'] == 200:
            return True
        else:
            return False

    def clear_entries(self):
        shows_for_download = [show.lower() for show in self.settings.roster.keys()]
        for entry in self.feed['entries']:
            re_entry = re.match(self.settings.pattern_show_name_season, entry['title'])
            try:
                re_title = re_entry.group(1)
            except AttributeError:
                re_entry = re.match(self.settings.pattern_movie_name, entry['title'])
                re_title = re_entry.group(1)
                re_season = 0
            else:
                re_season = int(re_entry.group(2))
            if (
                    re_title.lower() in shows_for_download and
                    self.settings.roster[re_title]['seasons'][0] <= re_season <=
                    self.settings.roster[re_title]['seasons'][1] and
                    entry['tags'][0]['term'] == self.settings.quality and
                    entry['title'] not in self.settings.entries_db and
                    'E999' not in entry['title']
            ):
                self.new_entry_preparation(entry)
        if self.settings.entries:
            self.settings.entries.reverse()
            return True
        else:
            exit(0)

    def new_entry_preparation(self, entry):
        entry_name = entry['title']
        show_name = re.match(self.settings.pattern_show_name_season, entry['title']).group(1)
        entry_link = entry['link']
        entry_timestamp = calendar.timegm(entry['published_parsed'])
        entry_download_path = path.join(
            self.settings.savepath,
            self.settings.category,
            self.settings.roster[show_name]['dir']
        )
        self.settings.entries.append([entry_name, entry_timestamp, entry_link, entry_download_path])

    def clear_old_entries(self):
        old_entries = []
        for name, timestamp in self.settings.entries_db.items():
            if self.old_entries_frontier > timestamp:
                old_entries.append(name)
        for name in old_entries:
            del self.settings.entries_db[name]
        with open(self.settings.entries_db_file, 'w', encoding='utf8') as dump_file:
            json.dump(self.settings.entries_db, dump_file, ensure_ascii=False)


class Downloader:

    def __init__(self, settings):
        self.settings = settings
        self.qbt_client = qbittorrentapi.Client(
            host=self.settings.host,
            username=self.settings.username,
            password=self.settings.password,
            VERIFY_WEBUI_CERTIFICATE=False,
        )

    def start(self):
        for entry in self.settings.entries:
            self.add_torrent(self.torrent_download(entry[2]), entry[3])
            self.settings.entries_db[entry[0]] = entry[1]

    def torrent_download(self, url):
        buffer = BytesIO()
        curl = pycurl.Curl()
        curl.setopt(curl.COOKIE, self.settings.cookie)
        curl.setopt(curl.URL, url)
        curl.setopt(curl.USERAGENT, 'Mozilla/5.0')
        curl.setopt(curl.WRITEDATA, buffer)
        curl.setopt(curl.FOLLOWLOCATION, True)
        curl.perform()
        curl.close()
        torrent = buffer.getvalue()
        sleep(1)
        if self.settings.announce['bad'] in torrent and self.settings.announce['good']:
            torrent = fix_announcers(torrent, self.settings.announce)
        return torrent

    def add_torrent(self, torrent, savepath):
        self.qbt_client.torrents_add(
            torrent_files=torrent,
            savepath=savepath,
            category=self.settings.category,
        )


if __name__ == '__main__':
    config = Conf()
    parser = ParserRSS(config)
    if parser.source_online() and parser.clear_entries():
        download = Downloader(config)
        download.start()
        parser.clear_old_entries()
