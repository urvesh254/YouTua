# coding: utf-8
from __future__ import unicode_literals

import itertools
import random
import re

from .common import InfoExtractor
from ..compat import (
    compat_str,
    compat_urllib_parse_unquote,
)
from ..utils import (
    determine_ext,
    ExtractorError,
    int_or_none,
    parse_age_limit,
    parse_duration,
    try_get,
    urljoin,
    url_or_none,
)


class NRKBaseIE(InfoExtractor):
    _GEO_COUNTRIES = ['NO']
    _CDN_REPL_REGEX = r'''(?x)://
        (?:
            nrkod\d{1,2}-httpcache0-47115-cacheod0\.dna\.ip-only\.net/47115-cacheod0|
            nrk-od-no\.telenorcdn\.net|
            minicdn-od\.nrk\.no/od/nrkhd-osl-rr\.netwerk\.no/no
        )/'''

    def _extract_nrk_formats(self, asset_url, video_id):
        if re.match(r'https?://[^/]+\.akamaihd\.net/i/', asset_url):
            return self._extract_akamai_formats(asset_url, video_id)
        asset_url = re.sub(r'(?:bw_(?:low|high)=\d+|no_audio_only)&?', '', asset_url)
        formats = self._extract_m3u8_formats(
            asset_url, video_id, 'mp4', 'm3u8_native', fatal=False)
        if not formats and re.search(self._CDN_REPL_REGEX, asset_url):
            formats = self._extract_m3u8_formats(
                re.sub(self._CDN_REPL_REGEX, '://nrk-od-%02d.akamaized.net/no/' % random.randint(0, 99), asset_url),
                video_id, 'mp4', 'm3u8_native', fatal=False)
        return formats

    def _raise_error(self, data):
        MESSAGES = {
            'ProgramRightsAreNotReady': 'Du kan dessverre ikke se eller høre programmet',
            'ProgramRightsHasExpired': 'Programmet har gått ut',
            'NoProgramRights': 'Ikke tilgjengelig',
            'ProgramIsGeoBlocked': 'NRK har ikke rettigheter til å vise dette programmet utenfor Norge',
        }
        message_type = data.get('messageType', '')
        # Can be ProgramIsGeoBlocked or ChannelIsGeoBlocked*
        if 'IsGeoBlocked' in message_type or try_get(data, lambda x: x['usageRights']['isGeoBlocked']) is True:
            self.raise_geo_restricted(
                msg=MESSAGES.get('ProgramIsGeoBlocked'),
                countries=self._GEO_COUNTRIES)
        message = data.get('endUserMessage') or MESSAGES.get(message_type, message_type)
        raise ExtractorError('%s said: %s' % (self.IE_NAME, message), expected=True)

    def _call_api(self, path, video_id, item=None, note=None, fatal=True, query=None):
        return self._download_json(
            urljoin('http://psapi.nrk.no/', path),
            video_id, note or 'Downloading %s JSON' % item,
            fatal=fatal, query=query)


class NRKIE(NRKBaseIE):
    _VALID_URL = r'''(?x)
                        (?:
                            nrk:|
                            https?://
                                (?:
                                    (?:www\.)?nrk\.no/video/(?:PS\*|[^_]+_)|
                                    v8[-.]psapi\.nrk\.no/mediaelement/
                                )
                            )
                            (?P<id>[^?\#&]+)
                        '''

    _TESTS = [{
        # video
        'url': 'http://www.nrk.no/video/PS*150533',
        'md5': 'f46be075326e23ad0e524edfcb06aeb6',
        'info_dict': {
            'id': '150533',
            'ext': 'mp4',
            'title': 'Dompap og andre fugler i Piip-Show',
            'description': 'md5:d9261ba34c43b61c812cb6b0269a5c8f',
            'duration': 262,
        }
    }, {
        # audio
        'url': 'http://www.nrk.no/video/PS*154915',
        # MD5 is unstable
        'info_dict': {
            'id': '154915',
            'ext': 'mp4',
            'title': 'Slik høres internett ut når du er blind',
            'description': 'md5:a621f5cc1bd75c8d5104cb048c6b8568',
            'duration': 20,
        }
    }, {
        'url': 'nrk:ecc1b952-96dc-4a98-81b9-5296dc7a98d9',
        'only_matching': True,
    }, {
        'url': 'nrk:clip/7707d5a3-ebe7-434a-87d5-a3ebe7a34a70',
        'only_matching': True,
    }, {
        'url': 'https://v8-psapi.nrk.no/mediaelement/ecc1b952-96dc-4a98-81b9-5296dc7a98d9',
        'only_matching': True,
    }, {
        'url': 'https://www.nrk.no/video/dompap-og-andre-fugler-i-piip-show_150533',
        'only_matching': True,
    }, {
        'url': 'https://www.nrk.no/video/humor/kommentatorboksen-reiser-til-sjos_d1fda11f-a4ad-437a-a374-0398bc84e999',
        'only_matching': True,
    }]

    def _extract_from_playback(self, video_id):
        path_templ = 'playback/%s/' + video_id

        def call_playback_api(item, query=None):
            return self._call_api(path_templ % item, video_id, item, query=query)
        # known values for preferredCdn: akamai, iponly, minicdn and telenor
        manifest = call_playback_api('manifest', {'preferredCdn': 'akamai'})

        if manifest.get('playability') == 'nonPlayable':
            self._raise_error(manifest['nonPlayable'])

        playable = manifest['playable']

        formats = []
        for asset in playable['assets']:
            if not isinstance(asset, dict):
                continue
            if asset.get('encrypted'):
                continue
            format_url = url_or_none(asset.get('url'))
            if not format_url:
                continue
            if asset.get('format') == 'HLS' or determine_ext(format_url) == 'm3u8':
                formats.extend(self._extract_nrk_formats(format_url, video_id))
        self._sort_formats(formats)

        data = call_playback_api('metadata')

        preplay = data['preplay']
        titles = preplay['titles']
        title = titles['title']
        alt_title = titles.get('subtitle')

        description = preplay.get('description')
        duration = parse_duration(playable.get('duration')) or parse_duration(data.get('duration'))

        thumbnails = []
        for image in try_get(
                preplay, lambda x: x['poster']['images'], list) or []:
            if not isinstance(image, dict):
                continue
            image_url = url_or_none(image.get('url'))
            if not image_url:
                continue
            thumbnails.append({
                'url': image_url,
                'width': int_or_none(image.get('pixelWidth')),
                'height': int_or_none(image.get('pixelHeight')),
            })

        return {
            'id': video_id,
            'title': title,
            'alt_title': alt_title,
            'description': description,
            'duration': duration,
            'thumbnails': thumbnails,
            'formats': formats,
        }

    def _real_extract(self, url):
        video_id = self._match_id(url)
        return self._extract_from_playback(video_id)


class NRKTVIE(NRKBaseIE):
    IE_DESC = 'NRK TV and NRK Radio'
    _EPISODE_RE = r'(?P<id>[a-zA-Z]{4}\d{8})'
    _VALID_URL = r'https?://(?:tv|radio)\.nrk(?:super)?\.no/(?:[^/]+/)*%s' % _EPISODE_RE
    _API_HOSTS = ('psapi-ne.nrk.no', 'psapi-we.nrk.no')
    _TESTS = [{
        'url': 'https://tv.nrk.no/program/MDDP12000117',
        'md5': 'c4a5960f1b00b40d47db65c1064e0ab1',
        'info_dict': {
            'id': 'MDDP12000117AA',
            'ext': 'mp4',
            'title': 'Alarm Trolltunga',
            'description': 'md5:46923a6e6510eefcce23d5ef2a58f2ce',
            'duration': 2223.44,
            'age_limit': 6,
        },
    }, {
        'url': 'https://tv.nrk.no/serie/20-spoersmaal-tv/MUHH48000314/23-05-2014',
        'md5': '8d40dab61cea8ab0114e090b029a0565',
        'info_dict': {
            'id': 'MUHH48000314AA',
            'ext': 'mp4',
            'title': '20 spørsmål 23.05.2014',
            'description': 'md5:bdea103bc35494c143c6a9acdd84887a',
            'duration': 1741,
            'series': '20 spørsmål',
            'episode': '23.05.2014',
        },
    }, {
        'url': 'https://tv.nrk.no/program/mdfp15000514',
        'info_dict': {
            'id': 'MDFP15000514CA',
            'ext': 'mp4',
            'title': 'Grunnlovsjubiléet - Stor ståhei for ingenting 24.05.2014',
            'description': 'md5:89290c5ccde1b3a24bb8050ab67fe1db',
            'duration': 4605.08,
            'series': 'Kunnskapskanalen',
            'episode': '24.05.2014',
        },
        'params': {
            'skip_download': True,
        },
    }, {
        # single playlist video
        'url': 'https://tv.nrk.no/serie/tour-de-ski/MSPO40010515/06-01-2015#del=2',
        'info_dict': {
            'id': 'MSPO40010515AH',
            'ext': 'mp4',
            'title': 'Sprint fri teknikk, kvinner og menn 06.01.2015',
            'description': 'md5:c03aba1e917561eface5214020551b7a',
        },
        'params': {
            'skip_download': True,
        },
        'expected_warnings': ['Failed to download m3u8 information'],
        'skip': 'particular part is not supported currently',
    }, {
        'url': 'https://tv.nrk.no/serie/tour-de-ski/MSPO40010515/06-01-2015',
        'info_dict': {
            'id': 'MSPO40010515AH',
            'ext': 'mp4',
            'title': 'Sprint fri teknikk, kvinner og menn 06.01.2015',
            'description': 'md5:c03aba1e917561eface5214020551b7a',
        },
        'expected_warnings': ['Failed to download m3u8 information'],
    }, {
        'url': 'https://tv.nrk.no/serie/anno/KMTE50001317/sesong-3/episode-13',
        'info_dict': {
            'id': 'KMTE50001317AA',
            'ext': 'mp4',
            'title': 'Anno 13:30',
            'description': 'md5:11d9613661a8dbe6f9bef54e3a4cbbfa',
            'duration': 2340,
            'series': 'Anno',
            'episode': '13:30',
            'season_number': 3,
            'episode_number': 13,
        },
        'params': {
            'skip_download': True,
        },
    }, {
        'url': 'https://tv.nrk.no/serie/nytt-paa-nytt/MUHH46000317/27-01-2017',
        'info_dict': {
            'id': 'MUHH46000317AA',
            'ext': 'mp4',
            'title': 'Nytt på Nytt 27.01.2017',
            'description': 'md5:5358d6388fba0ea6f0b6d11c48b9eb4b',
            'duration': 1796,
            'series': 'Nytt på nytt',
            'episode': '27.01.2017',
        },
        'params': {
            'skip_download': True,
        },
        'skip': 'ProgramRightsHasExpired',
    }, {
        'url': 'https://radio.nrk.no/serie/dagsnytt/NPUB21019315/12-07-2015#',
        'only_matching': True,
    }, {
        'url': 'https://tv.nrk.no/serie/lindmo/2018/MUHU11006318/avspiller',
        'only_matching': True,
    }, {
        'url': 'https://radio.nrk.no/serie/dagsnytt/sesong/201507/NPUB21019315',
        'only_matching': True,
    }]

    _api_host = None

    def _extract_from_mediaelement(self, video_id):
        api_hosts = (self._api_host, ) if self._api_host else self._API_HOSTS

        for api_host in api_hosts:
            data = self._download_json(
                'http://%s/mediaelement/%s' % (api_host, video_id),
                video_id, 'Downloading mediaelement JSON',
                fatal=api_host == api_hosts[-1])
            if not data:
                continue
            self._api_host = api_host
            break

        title = data.get('fullTitle') or data.get('mainTitle') or data['title']
        video_id = data.get('id') or video_id

        urls = []
        entries = []

        conviva = data.get('convivaStatistics') or {}
        live = (data.get('mediaElementType') == 'Live'
                or data.get('isLive') is True or conviva.get('isLive'))

        def make_title(t):
            return self._live_title(t) if live else t

        media_assets = data.get('mediaAssets')
        if media_assets and isinstance(media_assets, list):
            def video_id_and_title(idx):
                return ((video_id, title) if len(media_assets) == 1
                        else ('%s-%d' % (video_id, idx), '%s (Part %d)' % (title, idx)))
            for num, asset in enumerate(media_assets, 1):
                asset_url = asset.get('url')
                if not asset_url or asset_url in urls:
                    continue
                urls.append(asset_url)
                formats = self._extract_nrk_formats(asset_url, video_id)
                if not formats:
                    continue
                self._sort_formats(formats)

                entry_id, entry_title = video_id_and_title(num)
                duration = parse_duration(asset.get('duration'))
                subtitles = {}
                for subtitle in ('webVtt', 'timedText'):
                    subtitle_url = asset.get('%sSubtitlesUrl' % subtitle)
                    if subtitle_url:
                        subtitles.setdefault('no', []).append({
                            'url': compat_urllib_parse_unquote(subtitle_url)
                        })
                entries.append({
                    'id': asset.get('carrierId') or entry_id,
                    'title': make_title(entry_title),
                    'duration': duration,
                    'subtitles': subtitles,
                    'formats': formats,
                    'is_live': live,
                })

        if not entries:
            media_url = data.get('mediaUrl')
            if media_url and media_url not in urls:
                formats = self._extract_nrk_formats(media_url, video_id)
                if formats:
                    self._sort_formats(formats)
                    duration = parse_duration(data.get('duration'))
                    entries = [{
                        'id': video_id,
                        'title': make_title(title),
                        'duration': duration,
                        'formats': formats,
                        'is_live': live,
                    }]

        if not entries:
            self._raise_error(data)

        series = conviva.get('seriesName') or data.get('seriesTitle')
        episode = conviva.get('episodeName') or data.get('episodeNumberOrDate')

        season_number = None
        episode_number = None
        if data.get('mediaElementType') == 'Episode':
            _season_episode = data.get('scoresStatistics', {}).get('springStreamStream') or \
                data.get('relativeOriginUrl', '')
            EPISODENUM_RE = [
                r'/s(?P<season>\d{,2})e(?P<episode>\d{,2})\.',
                r'/sesong-(?P<season>\d{,2})/episode-(?P<episode>\d{,2})',
            ]
            season_number = int_or_none(self._search_regex(
                EPISODENUM_RE, _season_episode, 'season number',
                default=None, group='season'))
            episode_number = int_or_none(self._search_regex(
                EPISODENUM_RE, _season_episode, 'episode number',
                default=None, group='episode'))

        thumbnails = None
        images = data.get('images')
        if images and isinstance(images, dict):
            web_images = images.get('webImages')
            if isinstance(web_images, list):
                thumbnails = [{
                    'url': image['imageUrl'],
                    'width': int_or_none(image.get('width')),
                    'height': int_or_none(image.get('height')),
                } for image in web_images if image.get('imageUrl')]

        description = data.get('description')
        category = data.get('mediaAnalytics', {}).get('category')

        common_info = {
            'description': description,
            'series': series,
            'episode': episode,
            'season_number': season_number,
            'episode_number': episode_number,
            'categories': [category] if category else None,
            'age_limit': parse_age_limit(data.get('legalAge')),
            'thumbnails': thumbnails,
        }

        vcodec = 'none' if data.get('mediaType') == 'Audio' else None

        for entry in entries:
            entry.update(common_info)
            for f in entry['formats']:
                f['vcodec'] = vcodec

        points = data.get('shortIndexPoints')
        if isinstance(points, list):
            chapters = []
            for next_num, point in enumerate(points, start=1):
                if not isinstance(point, dict):
                    continue
                start_time = parse_duration(point.get('startPoint'))
                if start_time is None:
                    continue
                end_time = parse_duration(
                    data.get('duration')
                    if next_num == len(points)
                    else points[next_num].get('startPoint'))
                if end_time is None:
                    continue
                chapters.append({
                    'start_time': start_time,
                    'end_time': end_time,
                    'title': point.get('title'),
                })
            if chapters and len(entries) == 1:
                entries[0]['chapters'] = chapters

        return self.playlist_result(entries, video_id, title, description)

    def _real_extract(self, url):
        video_id = self._match_id(url)
        return self._extract_from_mediaelement(video_id)


class NRKTVEpisodeIE(InfoExtractor):
    _VALID_URL = r'https?://tv\.nrk\.no/serie/(?P<id>[^/]+/sesong/\d+/episode/\d+)'
    _TESTS = [{
        'url': 'https://tv.nrk.no/serie/hellums-kro/sesong/1/episode/2',
        'info_dict': {
            'id': 'MUHH36005220BA',
            'ext': 'mp4',
            'title': 'Kro, krig og kjærlighet 2:6',
            'description': 'md5:b32a7dc0b1ed27c8064f58b97bda4350',
            'duration': 1563,
            'series': 'Hellums kro',
            'season_number': 1,
            'episode_number': 2,
            'episode': '2:6',
            'age_limit': 6,
        },
        'params': {
            'skip_download': True,
        },
    }, {
        'url': 'https://tv.nrk.no/serie/backstage/sesong/1/episode/8',
        'info_dict': {
            'id': 'MSUI14000816AA',
            'ext': 'mp4',
            'title': 'Backstage 8:30',
            'description': 'md5:de6ca5d5a2d56849e4021f2bf2850df4',
            'duration': 1320,
            'series': 'Backstage',
            'season_number': 1,
            'episode_number': 8,
            'episode': '8:30',
        },
        'params': {
            'skip_download': True,
        },
        'skip': 'ProgramRightsHasExpired',
    }]

    def _real_extract(self, url):
        display_id = self._match_id(url)

        webpage = self._download_webpage(url, display_id)

        info = self._search_json_ld(webpage, display_id, default={})
        nrk_id = info.get('@id') or self._html_search_meta(
            'nrk:program-id', webpage, default=None) or self._search_regex(
            r'data-program-id=["\'](%s)' % NRKTVIE._EPISODE_RE, webpage,
            'nrk id')
        assert re.match(NRKTVIE._EPISODE_RE, nrk_id)

        info.update({
            '_type': 'url_transparent',
            'id': nrk_id,
            'url': 'nrk:%s' % nrk_id,
            'ie_key': NRKIE.ie_key(),
        })
        return info


class NRKTVSerieBaseIE(NRKBaseIE):
    def _extract_entries(self, entry_list):
        if not isinstance(entry_list, list):
            return []
        entries = []
        for episode in entry_list:
            nrk_id = episode.get('prfId') or episode.get('episodeId')
            if not nrk_id or not isinstance(nrk_id, compat_str):
                continue
            if not re.match(NRKTVIE._EPISODE_RE, nrk_id):
                continue
            entries.append(self.url_result(
                'nrk:%s' % nrk_id, ie=NRKIE.ie_key(), video_id=nrk_id))
        return entries

    _ASSETS_KEYS = ('episodes', 'instalments',)

    def _extract_assets_key(self, embedded):
        for asset_key in self._ASSETS_KEYS:
            if embedded.get(asset_key):
                return asset_key

    def _entries(self, data, display_id):
        for page_num in itertools.count(1):
            embedded = data.get('_embedded') or data
            if not isinstance(embedded, dict):
                break
            assets_key = self._extract_assets_key(embedded)
            if not assets_key:
                break
            # Extract entries
            entries = try_get(
                embedded,
                (lambda x: x[assets_key]['_embedded'][assets_key],
                 lambda x: x[assets_key]),
                list)
            for e in self._extract_entries(entries):
                yield e
            # Find next URL
            next_url_path = try_get(
                data,
                (lambda x: x['_links']['next']['href'],
                 lambda x: x['_embedded'][assets_key]['_links']['next']['href']),
                compat_str)
            if not next_url_path:
                break
            data = self._call_api(
                next_url_path, display_id,
                note='Downloading %s JSON page %d' % (assets_key, page_num),
                fatal=False)
            if not data:
                break


class NRKTVSeasonIE(NRKTVSerieBaseIE):
    _VALID_URL = r'https?://(?P<domain>tv|radio)\.nrk\.no/serie/(?P<serie>[^/]+)/(?:sesong/)?(?P<id>\d+)'
    _TESTS = [{
        'url': 'https://tv.nrk.no/serie/backstage/sesong/1',
        'info_dict': {
            'id': 'backstage/1',
            'title': 'Sesong 1',
        },
        'playlist_mincount': 30,
    }, {
        # no /sesong/ in path
        'url': 'https://tv.nrk.no/serie/lindmo/2016',
        'info_dict': {
            'id': 'lindmo/2016',
            'title': '2016',
        },
        'playlist_mincount': 29,
    }, {
        # weird nested _embedded in catalog JSON response
        'url': 'https://radio.nrk.no/serie/dickie-dick-dickens/sesong/1',
        'info_dict': {
            'id': 'dickie-dick-dickens/1',
            'title': 'Sesong 1',
        },
        'playlist_mincount': 11,
    }, {
        # 841 entries, multi page
        'url': 'https://radio.nrk.no/serie/dagsnytt/sesong/201509',
        'info_dict': {
            'id': 'dagsnytt/201509',
            'title': 'September 2015',
        },
        'playlist_mincount': 841,
    }, {
        # 180 entries, single page
        'url': 'https://tv.nrk.no/serie/spangas/sesong/1',
        'only_matching': True,
    }]

    @classmethod
    def suitable(cls, url):
        return (False if NRKTVIE.suitable(url) or NRKTVEpisodeIE.suitable(url)
                else super(NRKTVSeasonIE, cls).suitable(url))

    def _real_extract(self, url):
        domain, serie, season_id = re.match(self._VALID_URL, url).groups()
        display_id = '%s/%s' % (serie, season_id)

        data = self._call_api(
            '%s/catalog/series/%s/seasons/%s' % (domain, serie, season_id),
            display_id, 'season', query={'pageSize': 50})

        title = try_get(data, lambda x: x['titles']['title'], compat_str) or display_id
        return self.playlist_result(
            self._entries(data, display_id),
            display_id, title)


class NRKTVSeriesIE(NRKTVSerieBaseIE):
    _VALID_URL = r'https?://(?P<domain>(?:tv|radio)\.nrk|(?:tv\.)?nrksuper)\.no/serie/(?P<id>[^/]+)'
    _TESTS = [{
        # new layout, instalments
        'url': 'https://tv.nrk.no/serie/groenn-glede',
        'info_dict': {
            'id': 'groenn-glede',
            'title': 'Grønn glede',
            'description': 'md5:7576e92ae7f65da6993cf90ee29e4608',
        },
        'playlist_mincount': 90,
    }, {
        # new layout, instalments, more entries
        'url': 'https://tv.nrk.no/serie/lindmo',
        'only_matching': True,
    }, {
        'url': 'https://tv.nrk.no/serie/blank',
        'info_dict': {
            'id': 'blank',
            'title': 'Blank',
            'description': 'md5:7664b4e7e77dc6810cd3bca367c25b6e',
        },
        'playlist_mincount': 30,
    }, {
        # new layout, seasons
        'url': 'https://tv.nrk.no/serie/backstage',
        'info_dict': {
            'id': 'backstage',
            'title': 'Backstage',
            'description': 'md5:63692ceb96813d9a207e9910483d948b',
        },
        'playlist_mincount': 60,
    }, {
        # old layout
        'url': 'https://tv.nrksuper.no/serie/labyrint',
        'info_dict': {
            'id': 'labyrint',
            'title': 'Labyrint',
            'description': 'I Daidalos sin undersjøiske Labyrint venter spennende oppgaver, skumle robotskapninger og slim.',
        },
        'playlist_mincount': 3,
    }, {
        'url': 'https://tv.nrk.no/serie/broedrene-dal-og-spektralsteinene',
        'only_matching': True,
    }, {
        'url': 'https://tv.nrk.no/serie/saving-the-human-race',
        'only_matching': True,
    }, {
        'url': 'https://tv.nrk.no/serie/postmann-pat',
        'only_matching': True,
    }, {
        'url': 'https://radio.nrk.no/serie/dickie-dick-dickens',
        'info_dict': {
            'id': 'dickie-dick-dickens',
            'title': 'Dickie Dick Dickens',
            'description': 'md5:19e67411ffe57f7dce08a943d7a0b91f',
        },
        'playlist_mincount': 8,
    }, {
        'url': 'https://nrksuper.no/serie/labyrint',
        'only_matching': True,
    }]

    @classmethod
    def suitable(cls, url):
        return (
            False if any(ie.suitable(url)
                         for ie in (NRKTVIE, NRKTVEpisodeIE, NRKTVSeasonIE))
            else super(NRKTVSeriesIE, cls).suitable(url))

    def _real_extract(self, url):
        site, series_id = re.match(self._VALID_URL, url).groups()
        is_radio = site == 'radio.nrk'
        domain = 'radio' if is_radio else 'tv'

        size_prefix = 'p' if is_radio else 'embeddedInstalmentsP'
        series = self._call_api(
            '%s/catalog/series/%s' % (domain, series_id),
            series_id, 'serie', query={size_prefix + 'ageSize': 50})
        titles = try_get(series, [
            lambda x: x['titles'],
            lambda x: x[x['type']]['titles'],
            lambda x: x[x['seriesType']]['titles'],
        ]) or {}

        entries = []
        entries.extend(self._entries(series, series_id))
        embedded = series.get('_embedded') or {}
        linked_seasons = try_get(series, lambda x: x['_links']['seasons']) or []
        embedded_seasons = embedded.get('seasons') or []
        if len(linked_seasons) > len(embedded_seasons):
            for season in linked_seasons:
                season_name = season.get('name')
                if season_name and isinstance(season_name, compat_str):
                    entries.append(self.url_result(
                        'https://%s.nrk.no/serie/%s/sesong/%s'
                        % (domain, series_id, season_name),
                        ie=NRKTVSeasonIE.ie_key(),
                        video_title=season.get('title')))
        else:
            for season in embedded_seasons:
                entries.extend(self._entries(season, series_id))
        entries.extend(self._entries(
            embedded.get('extraMaterial') or {}, series_id))

        return self.playlist_result(
            entries, series_id, titles.get('title'), titles.get('subtitle'))


class NRKTVDirekteIE(NRKTVIE):
    IE_DESC = 'NRK TV Direkte and NRK Radio Direkte'
    _VALID_URL = r'https?://(?:tv|radio)\.nrk\.no/direkte/(?P<id>[^/?#&]+)'

    _TESTS = [{
        'url': 'https://tv.nrk.no/direkte/nrk1',
        'only_matching': True,
    }, {
        'url': 'https://radio.nrk.no/direkte/p1_oslo_akershus',
        'only_matching': True,
    }]


class NRKPlaylistBaseIE(InfoExtractor):
    def _extract_description(self, webpage):
        pass

    def _real_extract(self, url):
        playlist_id = self._match_id(url)

        webpage = self._download_webpage(url, playlist_id)

        entries = [
            self.url_result('nrk:%s' % video_id, NRKIE.ie_key())
            for video_id in re.findall(self._ITEM_RE, webpage)
        ]

        playlist_title = self. _extract_title(webpage)
        playlist_description = self._extract_description(webpage)

        return self.playlist_result(
            entries, playlist_id, playlist_title, playlist_description)


class NRKPlaylistIE(NRKPlaylistBaseIE):
    _VALID_URL = r'https?://(?:www\.)?nrk\.no/(?!video|skole)(?:[^/]+/)+(?P<id>[^/]+)'
    _ITEM_RE = r'class="[^"]*\brich\b[^"]*"[^>]+data-video-id="([^"]+)"'
    _TESTS = [{
        'url': 'http://www.nrk.no/troms/gjenopplev-den-historiske-solformorkelsen-1.12270763',
        'info_dict': {
            'id': 'gjenopplev-den-historiske-solformorkelsen-1.12270763',
            'title': 'Gjenopplev den historiske solformørkelsen',
            'description': 'md5:c2df8ea3bac5654a26fc2834a542feed',
        },
        'playlist_count': 2,
    }, {
        'url': 'http://www.nrk.no/kultur/bok/rivertonprisen-til-karin-fossum-1.12266449',
        'info_dict': {
            'id': 'rivertonprisen-til-karin-fossum-1.12266449',
            'title': 'Rivertonprisen til Karin Fossum',
            'description': 'Første kvinne på 15 år til å vinne krimlitteraturprisen.',
        },
        'playlist_count': 2,
    }]

    def _extract_title(self, webpage):
        return self._og_search_title(webpage, fatal=False)

    def _extract_description(self, webpage):
        return self._og_search_description(webpage)


class NRKTVEpisodesIE(NRKPlaylistBaseIE):
    _VALID_URL = r'https?://tv\.nrk\.no/program/[Ee]pisodes/[^/]+/(?P<id>\d+)'
    _ITEM_RE = r'data-episode=["\']%s' % NRKTVIE._EPISODE_RE
    _TESTS = [{
        'url': 'https://tv.nrk.no/program/episodes/nytt-paa-nytt/69031',
        'info_dict': {
            'id': '69031',
            'title': 'Nytt på nytt, sesong: 201210',
        },
        'playlist_count': 4,
    }]

    def _extract_title(self, webpage):
        return self._html_search_regex(
            r'<h1>([^<]+)</h1>', webpage, 'title', fatal=False)


class NRKSkoleIE(InfoExtractor):
    IE_DESC = 'NRK Skole'
    _VALID_URL = r'https?://(?:www\.)?nrk\.no/skole/?\?.*\bmediaId=(?P<id>\d+)'

    _TESTS = [{
        'url': 'https://www.nrk.no/skole/?page=search&q=&mediaId=14099',
        'md5': '18c12c3d071953c3bf8d54ef6b2587b7',
        'info_dict': {
            'id': '6021',
            'ext': 'mp4',
            'title': 'Genetikk og eneggede tvillinger',
            'description': 'md5:3aca25dcf38ec30f0363428d2b265f8d',
            'duration': 399,
        },
    }, {
        'url': 'https://www.nrk.no/skole/?page=objectives&subject=naturfag&objective=K15114&mediaId=19355',
        'only_matching': True,
    }]

    def _real_extract(self, url):
        video_id = self._match_id(url)

        nrk_id = self._download_json(
            'https://nrkno-skole-prod.kube.nrk.no/skole/api/media/%s' % video_id,
            video_id)['psId']

        return self.url_result('nrk:%s' % nrk_id)