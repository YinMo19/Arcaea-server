import os
from functools import lru_cache
from json import loads
from time import time

from flask import url_for

from .constant import Constant
from .error import NoAccess
from .user import User
from .util import get_file_md5, md5


@lru_cache(maxsize=8192)
def get_song_file_md5(song_id: str, file_name: str) -> str:
    path = os.path.join(Constant.SONG_FILE_FOLDER_PATH, song_id, file_name)
    if not os.path.isfile(path):
        return None
    return get_file_md5(path)


def initialize_songfile():
    '''初始化歌曲数据的md5信息'''
    get_song_file_md5.cache_clear()
    x = DownloadList()
    x.url_flag = False
    x.add_songs()
    del x


@lru_cache()
def get_only_3_song_ids():
    '''初始化只能下载byd相关的歌曲id'''
    if not os.path.isfile(Constant.SONGLIST_FILE_PATH):
        return []
    only_3_song_ids = []
    data = []
    with open(Constant.SONGLIST_FILE_PATH, 'r', encoding='utf-8') as f:
        data = loads(f.read())['songs']
    for x in data:
        if 'remote_dl' not in x or 'remote_dl' in x and not x['remote_dl']:
            if any(i['ratingClass'] == 3 for i in x['difficulties']):
                only_3_song_ids.append(x['id'])
    return only_3_song_ids


class UserDownload:
    '''
        用户下载类\ 
        properties: `user` - `User`类或子类的实例
    '''

    def __init__(self, c=None, user=None) -> None:
        self.c = c
        self.user = user

        self.song_id: str = None
        self.file_name: str = None

        self.token: str = None
        self.token_time: int = None

    def clear_user_download(self) -> None:
        self.c.execute(
            '''delete from user_download where user_id = :a and time <= :b''', {'a': self.user.user_id, 'b': int(time()) - 24*3600})

    @property
    def is_limited(self) -> bool:
        '''是否达到用户最大下载量'''
        if self.user is None:
            self.select_for_check()
        self.c.execute(
            '''select count(*) from user_download where user_id = :a''', {'a': self.user.user_id})
        y = self.c.fetchone()
        return y is not None and y[0] > Constant.DOWNLOAD_TIMES_LIMIT

    @property
    def is_valid(self) -> bool:
        '''链接是否有效且未过期'''
        if self.token_time is None:
            self.select_for_check()
        return int(time()) - self.token_time <= Constant.DOWNLOAD_TIME_GAP_LIMIT

    def insert_user_download(self) -> None:
        '''记录下载信息'''
        self.c.execute('''insert into user_download values(:a,:b,:c)''', {
                       'a': self.user.user_id, 'c': self.token, 'b': int(time())})

    def select_for_check(self) -> None:
        '''利用token、song_id、file_name查询其它信息'''
        self.c.execute('''select user_id, time from download_token where song_id=? and file_name=? and token = ? limit 1;''',
                       (self.song_id, self.file_name, self.token))

        x = self.c.fetchone()
        if not x:
            raise NoAccess('The token `%s` is not valid.' % self.token)
        self.user = User()
        self.user.user_id = x[0]
        self.token_time = x[1]

    def generate_token(self) -> None:
        self.token_time = int(time())
        self.token = md5(str(self.user.user_id) + self.song_id +
                         self.file_name + str(self.token_time))

    def insert_download_token(self) -> None:
        '''将数据插入数据库，让这个下载链接可用'''
        self.c.execute('''insert into download_token values(:a,:b,:c,:d,:e)''', {
            'a': self.user.user_id, 'b': self.song_id, 'c': self.file_name, 'd': self.token, 'e': self.token_time})

    @property
    def url(self) -> str:
        '''生成下载链接'''
        if self.token is None:
            self.generate_token()
            self.insert_download_token()
        if Constant.DOWNLOAD_LINK_PREFIX:
            prefix = Constant.DOWNLOAD_LINK_PREFIX
            if prefix[-1] != '/':
                prefix += '/'
            return prefix + self.song_id + '/' + self.file_name + '?t=' + self.token
        else:
            return url_for('download', file_path=self.song_id + '/' + self.file_name, t=self.token, _external=True)

    @property
    def hash(self) -> str:
        return get_song_file_md5(self.song_id, self.file_name)


class DownloadList(UserDownload):
    '''
        下载列表类\ 
        properties: `user` - `User`类或子类的实例
    '''

    def __init__(self, c=None, user=None) -> None:
        super().__init__(c, user)

        self.song_ids: list = None
        self.url_flag: bool = None

        self.downloads: list = []
        self.urls: dict = {}

    def clear_download_token_from_song(self, song_id: str) -> None:
        self.c.execute('''delete from download_token where user_id=:a and song_id=:b''', {
            'a': self.user.user_id, 'b': song_id})

    def add_one_song(self, song_id: str) -> None:
        if self.url_flag:
            self.clear_download_token_from_song(song_id)
        dir_list = os.listdir(os.path.join(
            Constant.SONG_FILE_FOLDER_PATH, song_id))

        re = {}
        for i in dir_list:
            if os.path.isfile(os.path.join(Constant.SONG_FILE_FOLDER_PATH, song_id, i)) and i in ['0.aff', '1.aff', '2.aff', '3.aff', 'base.ogg', '3.ogg', 'video.mp4', 'video_audio.ogg']:
                if song_id in get_only_3_song_ids() and i not in ['3.aff', '3.ogg']:
                    continue
                x = UserDownload(self.c, self.user)
                # self.downloads.append(x) # 这实际上没有用
                x.song_id = song_id
                x.file_name = i
                if i == 'base.ogg':
                    if 'audio' not in re:
                        re['audio'] = {}

                    re['audio']["checksum"] = x.hash
                    if self.url_flag:
                        re['audio']["url"] = x.url
                elif i == '3.ogg':
                    if 'audio' not in re:
                        re['audio'] = {}

                    if self.url_flag:
                        re['audio']['3'] = {"checksum": x.hash, "url": x.url}
                    else:
                        re['audio']['3'] = {"checksum": x.hash}
                elif i == 'video.mp4' or i == 'video_audio.ogg':
                    if 'additional_files' not in re:
                        re['additional_files'] = []

                    if self.url_flag:
                        re['additional_files'].append(
                            {"checksum": x.hash, "url": x.url, 'file_name': i})
                    else:
                        re['additional_files'].append(
                            {"checksum": x.hash, 'file_name': i})
                else:
                    if 'chart' not in re:
                        re['chart'] = {}

                    if self.url_flag:
                        re['chart'][i[0]] = {"checksum": x.hash, "url": x.url}
                    else:
                        re['chart'][i[0]] = {"checksum": x.hash}

        self.urls.update({song_id: re})

    def add_songs(self, song_ids: list = None) -> None:
        '''添加一个或多个歌曲到下载列表，若`song_ids`为空，则添加所有歌曲'''
        if song_ids is not None:
            self.song_ids = song_ids

        x = self.song_ids if self.song_ids else os.listdir(
            Constant.SONG_FILE_FOLDER_PATH)
        for i in x:
            if os.path.isdir(os.path.join(Constant.SONG_FILE_FOLDER_PATH, i)):
                self.add_one_song(i)
