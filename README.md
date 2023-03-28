# Lostfilm to qBittorrent (downloader)

Script for parse RSS from LostFilm web-site and download torrents via qBittorrent.

**Python 3.9** required.

After first run fill data in files (in ``$HOME/.config/LostFilm2qBt/`` directory):

1. ``settings.conf``:

1.1. ``uid`` and ``usess`` in section ``[LostFilm]``

1.2. ``announcekey`` in section ``[LostFilm]`` (optional, crutch for fix broken announcers)

1.3. ``host``, ``username``, ``password`` and ``savepath`` in section ``[qBittorrent]``

2. ``download.list``:

2.1. One line — one show. At the end of line: ``/S__-__`` or ``S__`` (optional season(s) for download), ``/Y____`` (optional, for destination dir).
