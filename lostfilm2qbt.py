import re
import os
import json
import pycurl
import calendar
import feedparser
import configparser
import qbittorrentapi
from io import BytesIO
from time import gmtime


class Conf:

    def __init__(self):
        self.work_dir = os.path.join(os.getenv('HOME'), '.LostFilm2qBt')
        self.config_file = os.path.join(self.work_dir, 'settings.conf')
        self.download_roster = os.path.join(self.work_dir, 'download.list')
        self.config = configparser.ConfigParser()
        self.exist()
        self.config.read(self.config_file)
        self.roster = self.read_roster()
        self.source_rss = self.read_config('LostFilm', 'source')
        self.quality = f'[{self.read_config("LostFilm", "quality")}]'
        self.cookie = f'uid={self.read_config("LostFilm", "uid")}; usess={self.read_config("LostFilm", "usess")}'
        self.host = self.read_config('qBittorrent', 'host')
        self.username = self.read_config('qBittorrent', 'username')
        self.password = self.read_config('qBittorrent', 'password')
        self.category = self.read_config('qBittorrent', 'category')
        self.savepath = self.read_config('qBittorrent', 'savepath')
        self.entries_db_file = os.path.join(self.work_dir, 'entries.db')
        try:
            self.entries_db = json.load(open(self.entries_db_file))
        except FileNotFoundError:
            self.entries_db = {}
        self.pattern_show_name = r'^.+\((.+)\).+\(.+\).+\[.+\]'
        self.entries = []

    def exist(self):
        if not os.path.isdir(self.work_dir):
            os.mkdir(self.work_dir)
        if not os.path.exists(self.config_file):
            try:
                self.create_config()
            except FileNotFoundError as exc:
                print(exc)
        if not os.path.exists(self.download_roster):
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
        shows = 'Best Show Name/2022\nAnother Best Show Name'
        with open(self.download_roster, 'w') as file:
            file.write(shows)
        raise FileNotFoundError(
            f'Required to fill list of shows in: {self.download_roster}.\n'
            f'One line — one show.\n'
            f'At the end of line — "/YYYY" (optional, for destination dir).'
        )

    def read_roster(self):
        roster = {}
        with open(self.download_roster) as file:
            pattern_with_year = r'(.+)\/(\d+$)'
            pattern_without_year = r'(^.+)'
            for line in file:
                if '/' in line:
                    re_line = re.match(pattern_with_year, line)
                    show_name = re_line.group(1)
                    show_year = re_line.group(2)
                    roster[show_name] = f'{show_name} ({show_year})'
                else:
                    re_line = re.match(pattern_without_year, line).group(1)
                    roster[re_line] = re_line
        return roster


class ParserRSS:

    def __init__(self, settings):
        self.old_entries_delta = (2678400 * 3)  # one month x3
        self.old_entries_frontier = calendar.timegm(gmtime()) - self.old_entries_delta
        self.settings = settings
        self.feed = feedparser.parse(self.settings.source_rss)

    def source_online(self):
        if self.feed['status'] == 200:
            return True
        else:
            return False

    def clear_entries(self):
        for entry in self.feed['entries']:
            re_title = re.match(self.settings.pattern_show_name, entry['title']).group(1)
            if (
                    re_title in self.settings.roster and
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
        show_name = re.match(self.settings.pattern_show_name, entry['title']).group(1)
        entry_link = entry['link']
        entry_timestamp = calendar.timegm(entry['published_parsed'])
        entry_download_path = os.path.join(
            self.settings.savepath,
            self.settings.category,
            self.settings.roster[show_name]
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
        return torrent

    def add_torrent(self, torrent, path):
        self.qbt_client.torrents_add(
            torrent_files=torrent,
            savepath=path,
            category=self.settings.category,
        )


config = Conf()
parser = ParserRSS(config)
if parser.source_online() and parser.clear_entries():
    download = Downloader(config)
    download.start()
    parser.clear_old_entries()
