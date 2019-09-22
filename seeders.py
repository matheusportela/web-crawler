import logging

import requests
from bs4 import BeautifulSoup


logger = logging.getLogger(__name__)


class Seeder:
    def get_urls(self, query):
        raise NotImplementedError('Seeder must implement "get_urls" method')


class DuckDuckGoSeeder(Seeder):
    headers = {
        'Host': 'duckduckgo.com',
        'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; rv:68.0) Gecko/20100101 '
            'Firefox/68.0'),
        'Accept': 'text/html,application/xhtml+xml,application/xml',
        'Accept-Language': 'en-US,en',
        'Accept-Encoding': 'gzip, deflate',
        'Referer': 'https://duckduckgo.com/',
        'Content-Type': 'application/x-www-form-urlencoded',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'TE': 'Trailers',
    }

    def get_urls(self, query):
        logger.debug('Getting URLs from DuckDuckGo')
        page = self.search(query)
        urls = self.extract_urls(page)
        return urls

    def search(self, query):
        response = requests.post(
            'https://duckduckgo.com/lite/',
            data={'q': query, 'kl': 'us-en'},
            headers=self.headers,
            timeout=10,
        )
        response.raise_for_status()
        return response.content

    def extract_urls(self, page):
        soup = BeautifulSoup(page, 'html.parser')
        links = soup.find_all('a', ['result-link'])
        urls = [link.get('href') for link in links]
        return urls
