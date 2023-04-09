import os
import re
import shutil

from Crypto.Cipher import AES
from concurrent.futures import ThreadPoolExecutor

import requests
from fake_useragent import UserAgent


class M3U8(object):
    def __init__(self, m3u8_url, proxy):
        self.m3u8_url = m3u8_url
        self.temp_dir = 'temp'
        self.output = 'm3u8.mp4'
        self.is_crypt = False
        self.to_crack = None
        self.session = requests.Session()
        self.proxy = proxy

    def set_session_property(self):
        headers = {'User-Agent': UserAgent().random}
        self.session.headers.update(headers)
        if self.proxy:
            proxy_list = self.proxy.split('://')
            protocol = proxy_list[0]
            ip_port = proxy_list[1]
            proxies = {f'{protocol}': f'{protocol}://{ip_port}'}
            self.session.proxies.update(proxies)

    def get_urls(self, url: str) -> tuple:
        """
        获取response中的urls, keys
        :param url: requests请求的url地址 (原m3u8_url和解析后m3u8_url)
        :return: 返回list, keys
        """
        response = self.session.get(url)
        lines = response.text.strip().split('\n')
        urls, keys = [], []
        for line in lines:
            if line.endswith('.ts'):
                urls.append(line)
            elif line.endswith('.m3u8'):
                urls.append(line)
            elif line.startswith('#EXT-X-KEY'):
                keys.append(line)
        return urls, keys

    def is_crack(self, m3u8_url: str, keys: list):
        """
        判断是否为加密视频
        :param m3u8_url: m3u8_url
        :param keys: #EXT-X-KEY
        :return:
        """
        if keys:
            print('\rstart crack...', end='')
            self.is_crypt = True
            ext_x_key = keys[0]
            uri = re.search('URI=\"(.*?)\"', ext_x_key).group(1)
            key_url = M3U8.parse_url(m3u8_url, uri)[0]
            key = self.session.get(key_url).content
            if re.search('IV=(.*)', ext_x_key):
                iv = re.search('IV=(.*)', ext_x_key).group(1).replace('0x', "")[:16].encode()
            else:
                iv = b'0000000000000000'
            self.to_crack = AES.new(key, AES.MODE_CBC, iv)
            print('\r' + 'start crack'.ljust(36, '.') + 'done\n', end='')

    @staticmethod
    def parse_url(m3u8_url: str, tail_url: str) -> tuple:
        """
        解析单行正确的url
        :param m3u8_url: 请求的地址,用来获取基准url
        :param tail_url: response的单行url
        :return: 正确的url, flag表示解析类型,基准url,url字符串去重
        """
        head_url = m3u8_url.rpartition('/')[0]
        end_with_str = ''
        for tail_str in tail_url.split('/'):
            if tail_str != '' and head_url.endswith(tail_str):
                end_with_str = tail_str
                break
        if end_with_str:
            url = head_url + tail_url.partition(end_with_str)[2]
            flag = 2
        else:
            if tail_url.startswith('/'):
                url = head_url + tail_url
                flag = 1
            else:
                url = head_url + '/' + tail_url
                flag = 0
        return url, flag, head_url, end_with_str

    def get_ts_urls(self) -> list:
        """
        获取ts_url列表
        :return: ts_list
        """
        print('\rparse m3u8 url...', end='')
        resp_tuple = self.get_urls(self.m3u8_url)
        urls = resp_tuple[0]
        if len(urls) == 1:
            m3u8_url = M3U8.parse_url(self.m3u8_url, urls[0])[0]
            m3u8_resp_tuple = self.get_urls(m3u8_url)
            ts_list = m3u8_resp_tuple[0]
        else:
            m3u8_url = self.m3u8_url
            m3u8_resp_tuple = resp_tuple
            ts_list = urls
        print('\r' + 'parse m3u8 url'.ljust(36, '.') + 'done\n', end='')
        keys = m3u8_resp_tuple[1]
        self.is_crack(m3u8_url, keys)
        print('\rfetch ts url...', end='')
        ts0 = ts_list[0]
        ts_urls = []
        if ts0.startswith('http'):
            ts_urls = ts_list
        else:
            ts0_tuple = M3U8.parse_url(m3u8_url, ts0)
            flag = ts0_tuple[1]
            head_url = ts0_tuple[2]
            end_with_str = ts0_tuple[3]
            if flag == 0:
                for ts_url in ts_list:
                    ts_u = head_url + '/' + ts_url
                    ts_urls.append(ts_u)
            elif flag == 1:
                for ts_url in ts_list:
                    ts_u = head_url + ts_url
                    ts_urls.append(ts_u)
            else:
                for ts_url in ts_list:
                    ts_u = head_url + ts_url.partition(end_with_str)[2]
                    ts_urls.append(ts_u)
        print('\r' + 'fetch ts url'.ljust(36, '.') + 'done\n', end='')
        return ts_urls

    def download(self, url: str, file_path: str, number: int, total: int):
        """
        下载单个文件
        :param url: 文件url位置
        :param file_path: 文件保存路径
        :param number: 已下载
        :param total: 总数
        :return:
        """
        response = self.session.get(url)
        if response.status_code == 200:
            with open(file_path, 'wb') as f:
                f.write(response.content)
                bar_num = int(number / total * 25)
                percent = bar_num * 4
                print('\r[{}/{}][{}{}]{}%'.format(number, total, '#' * bar_num,
                                                  '.' * (25 - bar_num), percent), end='')

    def thread_pool(self, urls: list):
        """
        开启线程池下载ts_list
        :param urls: ts文件 url list
        :return:
        """
        if not os.path.exists(self.temp_dir):
            os.mkdir(self.temp_dir)
        total = len(urls)
        with ThreadPoolExecutor(max_workers=8) as pool:
            for ts_url in urls:
                number = urls.index(ts_url) + 1
                ts_file_name = f'{number:0>5d}.ts'
                ts_file_path = os.path.join(self.temp_dir, ts_file_name)
                pool.submit(self.download, url=ts_url, file_path=ts_file_path, number=number, total=total)
        print('\r[{}/{}][{}]{}%\n'.format(total, total, '#' * 25, 100), end='')

    def merge_ts(self):
        """
        合并ts
        :return:
        """
        print('\rmerge ts...', end='')
        ts_list = os.listdir(self.temp_dir)
        ts_list.sort()
        with open(self.output, 'ab+') as f:
            for ts in ts_list:
                ts_path = os.path.join(self.temp_dir, ts)
                if self.is_crypt:
                    f.write(self.to_crack.decrypt(open(ts_path, 'rb').read()))
                else:
                    f.write(open(ts_path, 'rb').read())
        print('\r' + 'merge ts'.ljust(36, '.') + 'done\n', end='')

    def main(self):
        self.set_session_property()
        ts_urls = self.get_ts_urls()
        self.thread_pool(ts_urls)
        self.merge_ts()
        shutil.rmtree(self.temp_dir)


if __name__ == '__main__':
    m3u8_link = input('m3u8 url:')
    proxy_server = input('protocol://ip:port:')
    m3u8 = M3U8(m3u8_url=m3u8_link, proxy=proxy_server)
    m3u8.main()
