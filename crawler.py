import concurrent.futures
import logging
import queue
import threading
from urllib.parse import urlparse

from bs4 import BeautifulSoup
import reppy
import requests
import tldextract

from seeders import DuckDuckGoSeeder


logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.DEBUG)


class Crawler:
    def __init__(self, urls):
        self.urls = urls
        self.num_workers = 3
        self.max_visits_per_domain = 3
        self.user_agent = 'mvp307'
        self.active_domains = set()
        self.crawled_urls = set()
        self.crawled_domains = {}

    def crawl(self):
        # while not self.is_crawl_finished():
        for _ in range(5):
            logger.debug(f'URLs: {self.urls[:5]}')
            crawl_urls = self.get_urls_to_crawl()
            logger.debug(f'Active domains: {self.active_domains}')
            returned_urls = self.crawl_pages(crawl_urls)
            self.update_crawled_urls(crawl_urls)
            self.update_urls_to_crawl(returned_urls)

    def is_crawl_finished(self):
        return len(self.urls) == 0

    def get_urls_to_crawl(self):
        crawl_urls = []
        self.active_domains = set()

        while self.urls:
            url = self.urls.pop(0)
            domain = self.get_domain(url)

            if domain in self.active_domains:
                logger.debug(f'URL {url} skipped because domain {domain} is active')
                self.urls.append(url)
                continue

            if url in crawl_urls:
                logger.debug(f'URL {url} skipped because it is already in the current list of crawled URLs')
                continue

            if self.is_domain_saturated(domain):
                logger.debug(f'URL {url} skipped because domain {domain} has been visited too many times')
                continue

            crawl_urls.append(url)
            self.active_domains.add(domain)
            self.update_crawled_domain_count(domain)

            if len(crawl_urls) == self.num_workers:
                break

        return crawl_urls

    def update_active_domains(self, urls):
        for url in urls:
            self.update_active_domain(url)

    def update_active_domain(self, url):
        domain = self.get_domain(url)
        self.active_domains.add(domain)

    def is_domain_active(self, domain):
        return domain in self.active_domains

    def clear_active_domains(self):
        self.active_domains = set()

    def get_domain(self, url):
        tld = tldextract.extract(url)
        return f'{tld.domain}.{tld.suffix}'

    def is_url_crawled(self, url):
        return url in self.crawled_urls

    def is_domain_saturated(self, domain):
        return self.crawled_domains.get(domain, 0) == self.max_visits_per_domain

    def update_crawled_domain_count(self, domain):
        count = self.crawled_domains.get(domain, 0)
        count += 1
        self.crawled_domains[domain] = count
        logger.debug(f'Domain {domain} visits: {count}')

    def update_crawled_urls(self, urls):
        for url in urls:
            self.crawled_urls.add(url)

    def update_urls_to_crawl(self, urls):
        for url in urls:
            if not self.is_url_crawled(url):
                self.urls.append(url)

    def crawl_pages(self, urls):
        logger.info(f'Crawling {len(urls)} pages')

        crawled_urls = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.num_workers) as executor:
            futures = [executor.submit(self.crawl_page, url) for url in urls]
            for future in concurrent.futures.as_completed(futures):
                try:
                    base_url, urls = future.result()
                except Exception as e:
                    logger.error(f'Error {e}')
                else:
                    logger.info(f'{base_url} has {len(urls)} URLs: {urls[:10]}')
                    crawled_urls.extend(urls)

        return crawled_urls

    def crawl_page(self, url):
        logger.debug(f'Crawling {url}')
        if not self.is_url_crawlable(url):
            logger.debug(f'Skipping {url} following robots.txt rules')
            return url, []

        page = self.fetch_page(url)
        urls = self.extract_urls(page)
        normalized_urls = list(set(self.normalize_urls(url, urls)))

        logger.info(f'Base URL: {url}')
        logger.info(f'URLs: {urls[:10]}')
        logger.info(f'Normalized URLs: {normalized_urls[:10]}')

        return url, normalized_urls

    def is_url_crawlable(self, url):
        robots = reppy.Robots.fetch(reppy.Robots.robots_url(url))
        return robots.allowed(url, self.user_agent)

    def fetch_page(self, url):
        headers = {
            'User-Agent': self.user_agent,
        }
        response = requests.get(url, headers=headers)
        return response.content

    def extract_urls(self, page):
        soup = BeautifulSoup(page, 'html.parser')
        links = soup.find_all('a')
        urls = [link.get('href') for link in links]
        urls = list(filter(lambda u: u != None, urls))
        return urls

    def normalize_urls(self, base_url, urls):
        return [self.normalize_url(base_url, url) for url in urls]

    def normalize_url(self, base_url, url):
        parsed_base_url = urlparse(base_url)
        parsed_url = urlparse(url)

        scheme = parsed_url.scheme or parsed_base_url.scheme
        domain = parsed_url.netloc or parsed_base_url.netloc
        path = parsed_url.path or parsed_base_url.path

        query = parsed_url.query or parsed_base_url.query
        query = f'?{query}' if query else ''

        normalized_url = f'{scheme}://{domain}{path}{query}'
        return normalized_url


def main():
    query = 'dogs'
    logger.info(f'Crawling "{query}"')

    # seeder = DuckDuckGoSeeder()
    # urls = seeder.get_urls(query)
    # logger.debug(urls)
    urls = [
        'https://en.wikipedia.org/wiki/Dog',
        'https://www.dictionary.com/browse/dogs',
        'https://www.adoptapet.com/',
        'http://www.rescueme.org/',
        'https://www.petfinder.com/dogs/',
    ]

    crawler = Crawler(urls)
    crawler.crawl()


if __name__ == '__main__':
    main()
