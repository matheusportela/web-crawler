import logging
import queue
import threading
import time
from urllib.parse import urlparse

from bs4 import BeautifulSoup
import reppy
import requests
import tldextract

from seeders import DuckDuckGoSeeder


logging.basicConfig(format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def get_domain(url):
    tld = tldextract.extract(url)
    return f'{tld.domain}.{tld.suffix}'


class Crawler:
    def __init__(self):
        self.name = 'Crawler'
        self.valid_url_queue = queue.Queue()
        self.candidate_url_queue = queue.Queue()
        self.num_workers = 3
        self.domain_locks = {}

    def crawl(self, urls):
        logger.debug(f'{self.name} - Starting crawler')

        for url in urls:
            self.enqueue_url(url)

        self.spawn_url_validator()
        self.spawn_workers()

        time.sleep(1)

        self.valid_url_queue.join()

    def enqueue_url(self, url):
        self.candidate_url_queue.put(url)

    def spawn_url_validator(self):
        logger.debug(f'{self.name} - Spawning URL validator')
        validator = URLValidatorThread(self.valid_url_queue, self.candidate_url_queue, self.domain_locks)
        validator.start()

    def spawn_workers(self):
        for worker_id in range(self.num_workers):
            logger.debug(f'{self.name} - Spawning crawler worker')
            worker = WorkerThread(worker_id, self.valid_url_queue, self.candidate_url_queue, self.domain_locks)
            worker.start()


class WorkerThread(threading.Thread):
    def __init__(self, worker_id, valid_url_queue, candidate_url_queue, domain_locks):
        super().__init__(daemon=True)
        self.name = f'Worker {worker_id}'
        self.valid_url_queue = valid_url_queue
        self.candidate_url_queue = candidate_url_queue
        self.domain_locks = domain_locks
        self.user_agent = 'mvp'

        logger.debug(f'{self.name} - Spawned')

    def run(self):
        for url in self.enqueued_valid_urls():
            self.crawl_url(url)

    def enqueued_valid_urls(self):
        while True:
            url = self.valid_url_queue.get()

            # Avoid simultaneous accesses to same domain
            lock = self.get_domain_lock(url)
            with lock:
                logger.debug(f'{self.name} - Domain locks: {self.domain_locks}')
                yield url

            self.valid_url_queue.task_done()

    def get_domain_lock(self, url):
        domain = get_domain(url)
        return self.domain_locks[domain]

    def crawl_url(self, url):
        logger.debug(f'{self.name} - Started crawling URL {url}')
        logger.info(url)

        if not self.is_robots_allowed(url):
            return

        page = self.fetch_page(url)
        if page is None:
            return

        candidate_urls = self.extract_urls(page)
        candidate_urls = self.normalize_urls(url, candidate_urls)
        candidate_urls = self.deduplicate_urls(candidate_urls)
        self.enqueue_candidate_urls(candidate_urls)

        logger.debug(f'{self.name} - Finished crawling URL {url}')

    def is_robots_allowed(self, url):
        try:
            robots = reppy.Robots.fetch(reppy.Robots.robots_url(url))
            return robots.allowed(url, self.user_agent)
        except reppy.exceptions.ReppyException as e:
            logger.debug(f'{self.name} - Error when reading robots for URL {url} - {e}')
            return

    def fetch_page(self, url):
        headers = {
            'User-Agent': self.user_agent,
        }

        try:
            response = requests.get(url, headers=headers)
            return response.content
        except requests.exceptions.RequestException as e:
            logger.debug(f'{self.name} - Error when crawling URL {url} - {e}')
            return None

    def extract_urls(self, page):
        soup = BeautifulSoup(page, 'html.parser')
        links = soup.find_all('a')
        urls = [link.get('href') for link in links]

        # Remove None from list
        urls = list(filter(lambda u: u != None, urls))
        return urls

    def normalize_urls(self, base_url, candidate_urls):
        return [self.normalize_url(base_url, candidate_url) for candidate_url in candidate_urls]

    def normalize_url(self, base_url, candidate_url):
        parsed_base_url = urlparse(base_url)
        parsed_url = urlparse(candidate_url)

        scheme = parsed_url.scheme or parsed_base_url.scheme
        domain = parsed_url.netloc or parsed_base_url.netloc
        path = parsed_url.path or parsed_base_url.path

        query = parsed_url.query or parsed_base_url.query
        query = f'?{query}' if query else ''

        normalized_url = f'{scheme}://{domain}{path}{query}'
        return normalized_url

    def deduplicate_urls(self, urls):
        return list(set(urls))

    def enqueue_candidate_urls(self, candidate_urls):
        for url in candidate_urls:
            self.candidate_url_queue.put(url)


class URLValidatorThread(threading.Thread):
    def __init__(self, valid_url_queue, candidate_url_queue, domain_locks):
        super().__init__(daemon=True)
        self.name = 'URLValidator'

        self.valid_url_queue = valid_url_queue
        self.candidate_url_queue = candidate_url_queue

        self.domain_locks = domain_locks

        self.validators = [
            TooManyDomainAccessesValidator(),
            URLAlreadyVisitedValidator(),
        ]

        logger.debug(f'{self.name} - Spawned')

    def run(self):
        while True:
            candidate_url = self.candidate_url_queue.get()
            self.process_candidate_url(candidate_url)

    def process_candidate_url(self, candidate_url):
        logger.debug(f'{self.name} - Validating URL {candidate_url}')

        if self.is_valid_url(candidate_url):
            for validator in self.validators:
                validator.update(candidate_url)

            self.ensure_domain_lock_exists(candidate_url)

            # Add to queue only *after* updating validators to avoid processing
            # URLs that are still being validated
            self.valid_url_queue.put(candidate_url)

    def is_valid_url(self, candidate_url):
        for validator in self.validators:
            if not validator.is_valid(candidate_url):
                logger.debug(f'{self.name} - Skipping URL {candidate_url} - {validator.__class__.__name__}')
                return False

        logger.debug(f'{self.name} - Enqueuing URL {candidate_url}')
        return True

    def ensure_domain_lock_exists(self, url):
        domain = get_domain(url)
        if domain not in self.domain_locks:
            self.domain_locks[domain] = threading.Lock()

        logger.debug(f'{self.name} - Domain locks: {self.domain_locks}')


class URLValidator:
    def is_valid(self, candidate_url):
        raise NotImplementedError

    def update(self, url):
        raise NotImplementedError


class URLAlreadyVisitedValidator(URLValidator):
    def __init__(self):
        self.visited_urls = set()

    def is_valid(self, candidate_url):
        return candidate_url not in self.visited_urls

    def update(self, url):
        self.visited_urls.add(url)


class TooManyDomainAccessesValidator(URLValidator):
    def __init__(self):
        self.domain_accesses = {}
        self.max_accesses = 3

    def is_valid(self, candidate_url):
        domain = get_domain(candidate_url)
        accesses = self.domain_accesses.get(domain, 0)
        return accesses < self.max_accesses

    def update(self, url):
        domain = get_domain(url)
        accesses = self.domain_accesses.get(domain, 0)
        accesses += 1
        self.domain_accesses[domain] = accesses


def main():
    query = 'dogs'
    logger.info(f'Crawling "{query}"')

    seeder = DuckDuckGoSeeder()
    urls = seeder.get_urls(query)
    logger.debug(urls)

    # urls = [
    #     'https://en.wikipedia.org/wiki/Dog',
    #     'https://en.wikipedia.org/wiki/Cat',
    #     'https://en.wikipedia.org/wiki/Parrot',
    #     'https://en.wikipedia.org/wiki/Turtle',
    #     'https://en.wikipedia.org/wiki/Armadillo',
    #     'https://en.wikipedia.org/wiki/Snake',
    #     'https://www.dictionary.com/browse/dogs',
    #     'https://www.adoptapet.com/',
    #     'https://en.wikipedia.org/wiki/Pet',
    #     'https://en.wikipedia.org/wiki/Brazil',
    #     'https://en.wikipedia.org/wiki/Tenis',
    #     'http://www.rescueme.org/',
    #     'https://www.petfinder.com/dogs/',
    # ]
    crawler = Crawler()
    crawler.crawl(urls)


if __name__ == '__main__':
    main()