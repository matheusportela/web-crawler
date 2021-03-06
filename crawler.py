from datetime import datetime
import heapq
import logging
import math
import queue
import threading
import time
from urllib.parse import urlparse

from bs4 import BeautifulSoup
import click
import reppy
import requests
import tldextract


logging.basicConfig(format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def get_domain(url):
    """Get domain from given URL."""
    tld = tldextract.extract(url)
    return f'{tld.domain}.{tld.suffix}'


def get_domain_and_subdomain(url):
    """Get domain and sub-domain from given URL."""
    tld = tldextract.extract(url)
    return f'{tld.subdomain}.{tld.domain}.{tld.suffix}'


class Crawler:
    """Crawler class, responsible for spawning URL validator and workers threads,
    as well as creating FIFO queues, priority queues and domain locks storage.
    """
    def __init__(self, bfs=False):
        self.name = 'Crawler'
        self.valid_url_queue = queue.Queue()
        self.candidate_url_queue = queue.Queue()
        self.url_priority_queue = URLPriorityQueue(bfs=bfs)
        self.num_workers = 80
        self.domain_locks = {}

    def crawl(self, urls):
        """Start crawling given a list of URLs."""
        logger.info(f'{self.name} - Starting crawler')

        self.print_header()

        for url in urls:
            self.enqueue_url(url)

        validator = self.spawn_url_validator()

        time.sleep(1)

        self.spawn_workers()

        time.sleep(1)

        validator.join()

    def enqueue_url(self, url):
        """Push a URL to the candidate URL queue with depth 1."""
        self.candidate_url_queue.put((url, 1))

    def spawn_url_validator(self):
        """Spawn URL validator thread."""
        validator = URLValidatorThread(self.valid_url_queue, self.candidate_url_queue, self.url_priority_queue, self.domain_locks)
        validator.start()
        return validator

    def spawn_workers(self):
        """Spawn worker threads."""
        for worker_id in range(self.num_workers):
            worker = WorkerThread(worker_id, self.valid_url_queue, self.candidate_url_queue, self.url_priority_queue, self.domain_locks)
            worker.start()

    def print_header(self):
        """Print header to output."""
        print('Timestamp\tPriority\tDepth\tSize\tURL')


class WorkerThread(threading.Thread):
    """Worker thread, responsible for acquiring domain lock, checking robots.txt,
    fetching URL pages, parsing HTML, extracting URLs, increasing crawling depth
    and pushing extracted URLs to candidate URL queue."""
    def __init__(self, worker_id, valid_url_queue, candidate_url_queue, url_priority_queue, domain_locks):
        super().__init__(daemon=True)
        self.name = f'Worker {worker_id}'
        self.valid_url_queue = valid_url_queue
        self.candidate_url_queue = candidate_url_queue
        self.url_priority_queue = url_priority_queue
        self.domain_locks = domain_locks
        self.user_agent = 'mvp'

        logger.info(f'{self.name} - Spawned')

    def run(self):
        """Crawl URL and output results."""
        for priority, url, depth in self.enqueued_valid_urls():
            page_size = self.crawl_url(url, depth)

            if page_size:
                self.output_results(priority, url, depth, page_size)

    def enqueued_valid_urls(self):
        """Get next URL from valid URLs queue."""
        while True:
            priority, url, depth = self.url_priority_queue.get()

            # Avoid simultaneous accesses to same domain
            lock = self.get_domain_lock(url)
            with lock:
                logger.debug(f'{self.name} - Domain locks: {self.domain_locks}')
                yield priority, url, depth

    def get_domain_lock(self, url):
        """Get domain lock for the given URL."""
        domain = get_domain(url)
        return self.domain_locks[domain]

    def crawl_url(self, url, depth):
        """Crawl URL."""
        logger.debug(f'{self.name} - Started crawling URL {url}')

        if not self.is_robots_allowed(url):
            return 0

        page = self.fetch_page(url)
        if page is None:
            return 0

        candidate_urls = self.extract_urls(page)
        candidate_urls = self.normalize_urls(url, candidate_urls)
        candidate_urls = self.deduplicate_urls(candidate_urls)
        self.enqueue_candidate_urls(candidate_urls, depth)

        logger.debug(f'{self.name} - Finished crawling URL {url}')

        return len(page)

    def is_robots_allowed(self, url):
        """Check robots.txt."""
        try:
            robots = reppy.Robots.fetch(reppy.Robots.robots_url(url))
            return robots.allowed(url, self.user_agent)
        except (reppy.exceptions.ReppyException, ValueError) as e:
            logger.debug(f'{self.name} - Error when reading robots for URL {url} - {e}')
            return
        except Exception as e:
            logger.exception(f'{self.name} - Error when reading robots for URL {url} - {e}')
            return

    def fetch_page(self, url):
        """Fetch HTML page for the given URL."""
        headers = {
            'User-Agent': self.user_agent,
        }

        try:
            response = requests.get(url, headers=headers, timeout=5)
            return response.content
        except requests.exceptions.RequestException as e:
            logger.warning(f'{self.name} - Error when crawling URL {url} - {e}')
            return
        except Exception as e:
            logger.exception(f'{self.name} - Error when crawling URL {url} - {e}')
            return

    def extract_urls(self, page):
        """Extract URLs from HTML page."""
        soup = BeautifulSoup(page, 'html.parser')
        links = soup.find_all('a')
        urls = [link.get('href') for link in links]

        # Remove None from list
        urls = list(filter(lambda u: u != None, urls))
        return urls

    def normalize_urls(self, base_url, candidate_urls):
        """Normalize candidate URLs."""
        return [self.normalize_url(base_url, candidate_url) for candidate_url in candidate_urls]

    def normalize_url(self, base_url, candidate_url):
        """Transform relative paths to absolute ones."""
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
        """Remove duplicated URLs from list."""
        return list(set(urls))

    def enqueue_candidate_urls(self, candidate_urls, depth):
        """Enqueue candidate URLs with increased crawling depth."""
        for url in candidate_urls:
            self.candidate_url_queue.put((url, depth + 1))

    def output_results(self, priority, url, depth, page_size):
        """Print crawling results for the given URL."""
        output = []
        output.append(f'{datetime.now().isoformat()}')
        output.append(f'{-priority}')
        output.append(f'{depth}')
        output.append(f'{page_size}')
        output.append(f'{url}')
        print('\t'.join(output))


class URLValidatorThread(threading.Thread):
    """Checks whether extracted URL should be crawled or not."""
    def __init__(self, valid_url_queue, candidate_url_queue, url_priority_queue, domain_locks):
        super().__init__(daemon=True)
        self.name = 'URLValidator'

        self.valid_url_queue = valid_url_queue
        self.candidate_url_queue = candidate_url_queue
        self.url_priority_queue = url_priority_queue

        self.domain_locks = domain_locks

        self.validators = [
            TooManyDomainAccessesValidator(),
            URLAlreadyVisitedValidator(),
        ]

        logger.info(f'{self.name} - Spawned')

    def run(self):
        """Process URLs in candidate URL queue."""
        while True:
            candidate_url, depth = self.candidate_url_queue.get()
            self.process_candidate_url(candidate_url, depth)

    def process_candidate_url(self, candidate_url, depth):
        """Checks whether URL is valid. If so, creates domain lock when necessary
        and pushes URL to priority queue."""
        logger.debug(f'{self.name} - Validating URL {candidate_url}')

        if self.is_valid_url(candidate_url):
            for validator in self.validators:
                validator.update(candidate_url)

            self.ensure_domain_lock_exists(candidate_url)

            # Add to queue only *after* updating validators to avoid processing
            # URLs that are still being validated
            # self.valid_url_queue.put(candidate_url)
            self.url_priority_queue.put(candidate_url, depth)

    def is_valid_url(self, candidate_url):
        """Checks whether URL is valid using validators."""
        for validator in self.validators:
            if not validator.is_valid(candidate_url):
                logger.debug(f'{self.name} - Skipping URL {candidate_url} - {validator.__class__.__name__}')
                return False

        logger.debug(f'{self.name} - Enqueuing URL {candidate_url}')
        return True

    def ensure_domain_lock_exists(self, url):
        """Create domain lock when necessary."""
        domain = get_domain(url)
        if domain not in self.domain_locks:
            self.domain_locks[domain] = threading.Lock()


class URLValidator:
    """Abstract class to URL validators used by validator thread."""
    def is_valid(self, candidate_url):
        raise NotImplementedError

    def update(self, url):
        raise NotImplementedError


class URLAlreadyVisitedValidator(URLValidator):
    """Validates whether given URL has already been visited."""
    def __init__(self):
        self.visited_urls = set()

    def is_valid(self, candidate_url):
        """Validates whether given URL has already been visited."""
        return candidate_url not in self.visited_urls

    def update(self, url):
        """Update list of visited URLs."""
        self.visited_urls.add(url)


class TooManyDomainAccessesValidator(URLValidator):
    """Validates whether domain has been visited too many times."""
    def __init__(self):
        self.domain_accesses = {}
        self.max_accesses = 50

    def is_valid(self, candidate_url):
        """Validates whether domain has been visited too many times."""
        domain = get_domain(candidate_url)
        accesses = self.domain_accesses.get(domain, 0)
        return accesses < self.max_accesses

    def update(self, url):
        """Update counting of domain visits."""
        domain = get_domain(url)
        accesses = self.domain_accesses.get(domain, 0)
        accesses += 1
        self.domain_accesses[domain] = accesses


class URLPriorityQueue:
    """URL priority queue using novelty and importance scores."""
    def __init__(self, bfs=False):
        self.priority_queue = PriorityQueue()

        self.queue_lock = threading.Lock()

        self.url_counter = 0
        self.url_id_lock = threading.Lock()

        if bfs:
            self.novelty_scorer = BFSScorer()
            self.importance_scorer = BFSScorer()
        else:
            self.novelty_scorer = NoveltyScorer()
            self.importance_scorer = ImportanceScorer()

        self.current_urls = set()

    def empty(self):
        """Checks whether priority queue is empty."""
        return self.priority_queue.empty()

    def get(self):
        """Gets highest priority URL, block when none is available."""
        while True:
            try:
                return self.pop()
            except KeyError:
                logger.debug('URLPriorityQueue - Queue is empty... Waiting')
                time.sleep(0.01)

    def pop(self):
        """Gets highest priority URL thread-safely."""
        with self.queue_lock:
            result_url = None
            result_depth = None

            while result_url is None:
                priority, (url, depth) = self.priority_queue.pop()
                updated_priority = self.calculate_url_priority(url)

                logger.debug(f'URLPriorityQueue - recalculated priority {-priority} -> {-updated_priority} for URL {url}')

                if priority == updated_priority:
                    result_url = url
                    result_depth = depth
                else:
                    self.priority_queue.put(updated_priority, (url, depth))

            logger.debug(f'URLPriorityQueue - Priority: {-priority} URL: {result_url}')

            # Update novelty score whenever URL is returned to be visited
            self.novelty_scorer.update(result_url)

            # Bookkeeping
            self.current_urls.remove(result_url)

        return priority, result_url, result_depth

    def put(self, url, depth):
        """Put URL into queue thread-safely."""
        with self.queue_lock:
            if not self.is_url_enqueued(url):
                self.enqueue(url, depth)

            # Update importance score whenever a link to the URL is enqueued to be visited
            self.importance_scorer.update(url)
            priority = self.calculate_url_priority(url)
            self.priority_queue.update(priority, (url, depth))

    def is_url_enqueued(self, url):
        """Checks whether URL is already in queue."""
        return url in self.current_urls

    def enqueue(self, url, depth):
        """Calculate score and put URL into queue."""
        priority = self.calculate_url_priority(url)
        url_id = self.calculate_url_id()
        self.priority_queue.put(priority, (url, depth))
        self.current_urls.add(url)

    def calculate_url_priority(self, url):
        """Calculate URL priority score."""
        novelty_score = self.novelty_scorer.score(url)
        importance_score = self.importance_scorer.score(url)
        url_score = novelty_score + importance_score
        # Negative to transform min-heap (queue.PriorityQueue) into max-heap
        return -url_score

    def calculate_url_id(self):
        """Calculate URL ID, tie-breaking in priority queue."""
        with self.url_id_lock:
            url_id = self.url_counter
            self.url_counter += 1

        return url_id


class PriorityQueue:
    """Thread-safe priority queue."""

    # Reference: https://docs.python.org/3.7/library/heapq.html#priority-queue-implementation-notes
    def __init__(self):
        self.queue = []
        self.entries = {}
        self.entry_id_counter = 0
        self.lock = threading.Lock()

    def put(self, priority, value):
        """Put value into priority queue thread-safely."""
        with self.lock:
            entry_id = self.entry_id_counter
            self.entry_id_counter += 1

            entry = [priority, entry_id, value, False]
            self.entries[value] = entry
            heapq.heappush(self.queue, entry)

    def update(self, priority, value):
        """Update value from priority queue thread-safely."""
        self.remove(value)
        self.put(priority, value)

    def remove(self, value):
        """Remove value from priority queue thread-safely."""
        with self.lock:
            entry = self.entries.pop(value)
            entry[-1] = True

    def pop(self):
        """Get value from priority queue thread-safely."""
        with self.lock:
            while self.queue:
                entry = heapq.heappop(self.queue)
                if not entry[-1]:
                    del self.entries[entry[2]]
                    return entry[0], entry[2]
            raise KeyError('priority queue is empty')

    def empty(self):
        """Check whether priority queue is empty."""
        return self.queue == []


class Scorer:
    """Abstract class to calculate URL score."""
    def score(self, url):
        raise NotImplementedError

    def update(self, url):
        raise NotImplementedError


class NoveltyScorer(Scorer):
    """URL novelty score."""
    def __init__(self):
        self.domain_and_subdomain_visits = {}
        self.lock = threading.Lock()
        self.initial_score = 10
        self.min_score = 0
        self.step = 0.1

    def score(self, url):
        """Calculate novelty score based on the domain."""
        domain_and_subdomain = get_domain_and_subdomain(url)
        return self.domain_and_subdomain_visits.get(domain_and_subdomain, self.initial_score)

    def update(self, url):
        """Update domain novelty score."""
        logger.debug(f'NoveltyScorer - updating {url}')

        domain_and_subdomain = get_domain_and_subdomain(url)

        with self.lock:
            score = self.domain_and_subdomain_visits.get(domain_and_subdomain, self.initial_score)
            score -= self.step
            self.domain_and_subdomain_visits[domain_and_subdomain] = max(self.min_score, score)

        logger.debug(f'NoveltyScorer - updating {url} score to {score}')


class ImportanceScorer(Scorer):
    """URL importance score."""
    def __init__(self):
        self.page_references = {}
        self.domain_and_subdomain_references = {}
        self.lock = threading.Lock()
        self.initial_score = 0
        self.max_score = math.inf
        self.domain_step = 0.01
        self.page_step = 1

    def score(self, url):
        """Calculate URL importance score based on the domain and URL."""
        domain_and_subdomain = get_domain_and_subdomain(url)
        page_score = self.page_references.get(url, self.initial_score)
        domain_and_subdomain_score = self.domain_and_subdomain_references.get(domain_and_subdomain, self.initial_score)
        score = page_score + domain_and_subdomain_score
        return score

    def update(self, url):
        """Update URL importance score."""
        logger.debug(f'ImportanceScorer - updating {url}')

        domain_and_subdomain = get_domain_and_subdomain(url)

        with self.lock:
            page_score = self.page_references.get(url, self.initial_score)
            domain_and_subdomain_score = self.domain_and_subdomain_references.get(domain_and_subdomain, self.initial_score)
            page_score += self.page_step
            domain_and_subdomain_score += self.domain_step
            self.page_references[url] = min(self.max_score, page_score)
            self.domain_and_subdomain_references[domain_and_subdomain] = min(self.max_score, domain_and_subdomain_score)

        logger.debug(f'ImportanceScorer - updating {url} page score to {page_score}')
        logger.debug(f'ImportanceScorer - updating {url} domain score to {domain_and_subdomain_score}')


class BFSScorer(Scorer):
    """BFS score, constant for all URLs."""
    def score(self, url):
        return 1

    def update(self, _):
        pass


class Seeder:
    """Abstract class for seeders."""
    def get_urls(self, query):
        raise NotImplementedError('Seeder must implement "get_urls" method')


class DuckDuckGoSeeder(Seeder):
    """Get seed URLs from DuckDuckGo's first page of results."""

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
        """Get seed URLs from DuckDuckGo's first page of results."""
        logger.debug('Getting URLs from DuckDuckGo')
        page = self.search(query)
        urls = self.extract_urls(page)
        return urls

    def search(self, query):
        """Request results from DuckDuckGo."""
        response = requests.post(
            'https://duckduckgo.com/lite/',
            data={'q': query, 'kl': 'us-en'},
            headers=self.headers,
            timeout=10,
        )
        response.raise_for_status()
        return response.content

    def extract_urls(self, page):
        """Parse and extract URLs from DuckDuckGo."""
        soup = BeautifulSoup(page, 'html.parser')
        links = soup.find_all('a', ['result-link'])
        urls = [link.get('href') for link in links]
        return urls


@click.command(
    name='crawl',
    short_help='crawl websites using text query',
    context_settings={'help_option_names': ['-h', '--help']})
@click.option(
    '--bfs', '-b', is_flag=True, default=False,
    help='Runs BFS crawler. Without this flag, the crawler runs in prioritized mode.')
@click.argument('query')
def crawl(query, bfs):
    print(f'Crawling "{query}"')

    seeder = DuckDuckGoSeeder()
    urls = seeder.get_urls(query)
    logger.debug(urls)

    crawler = Crawler(bfs=bfs)
    crawler.crawl(urls)


if __name__ == '__main__':
    crawl()
